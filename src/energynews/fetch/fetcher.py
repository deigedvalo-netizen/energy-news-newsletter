"""Fetcher (FR-2): RSS polling with robots.txt, conditional GET and per-source isolation."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib import robotparser
from urllib.parse import urljoin, urlsplit
import calendar
import feedparser
import httpx
from ..models import RawItem, Source

USER_AGENT = "energynews-bot/0.1 (+https://github.com/deigedvalo-netizen/energy-news-newsletter)"


@dataclass
class SourceHealth:
    source_id: str
    etag: str | None = None
    last_modified: str | None = None
    consecutive_failures: int = 0
    last_status: str | None = None
    reason: str | None = None


@dataclass
class FetchResult:
    items: list[RawItem] = field(default_factory=list)
    status: str = "OK"  # OK | NOT_MODIFIED | FAILED | ROBOTS_DISALLOWED | SKIPPED
    reason: str | None = None
    etag: str | None = None
    last_modified: str | None = None


class Robots:
    def __init__(self, http: httpx.Client):
        self.http, self.cache = http, {}

    def allowed(self, url: str) -> bool:
        p = urlsplit(url)
        if p.scheme not in ("http", "https") or not p.netloc:
            return False  # never fetch relative or non-web URLs
        base = f"{p.scheme}://{p.netloc}"
        if base not in self.cache:
            rp = robotparser.RobotFileParser()
            try:
                r = self.http.get(base + "/robots.txt", timeout=15)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except Exception:  # network or URL errors: treat as no robots.txt
                rp.parse([])
            self.cache[base] = rp
        return self.cache[base].can_fetch(USER_AGENT, url)


def _parsed_time(entry) -> datetime | None:
    for k in ("published_parsed", "updated_parsed"):
        t = entry.get(k)
        if t:
            return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    return None


def fetch_source(src: Source, state: SourceHealth, http: httpx.Client, robots: Robots) -> FetchResult:
    if src.access_method.startswith("API_"):
        from .apis import fetch_api_source  # documented APIs: keyed/rate-limited access instead of robots.txt
        return fetch_api_source(src, http)
    try:
        if not robots.allowed(src.url):
            return FetchResult(status="ROBOTS_DISALLOWED", reason="robots.txt disallows feed url")
        headers = {}
        if state.etag:
            headers["If-None-Match"] = state.etag
        if state.last_modified:
            headers["If-Modified-Since"] = state.last_modified
        r = http.get(src.url, headers=headers, timeout=30, follow_redirects=True)
        if r.status_code == 304:
            return FetchResult(status="NOT_MODIFIED", etag=state.etag, last_modified=state.last_modified)
        if r.status_code >= 400:
            return FetchResult(status="FAILED", reason=f"HTTP {r.status_code}")
        if src.access_method == "HTML_LIST":
            from .html_list import parse_listing
            items = parse_listing(r.text, src, str(r.url))
            if not items:
                return FetchResult(status="FAILED", reason="SELECTOR_NO_MATCH")
            return FetchResult(items=items, etag=r.headers.get("ETag"), last_modified=r.headers.get("Last-Modified"))
        feed = feedparser.parse(r.content)
        if feed.bozo and not feed.entries:
            return FetchResult(status="FAILED", reason=f"unparseable feed: {feed.get('bozo_exception')}")
        items = []
        for e in feed.entries:
            link = e.get("link")
            if not link or not e.get("title"):
                continue
            link = urljoin(str(r.url), link.strip())  # some feeds (e.g. EIA) use relative links
            if urlsplit(link).scheme not in ("http", "https"):
                continue
            items.append(RawItem(src.source_id, link, e.get("title", "").strip(), e.get("summary", "") or "",
                                 e.get("published") or e.get("updated"), _parsed_time(e)))
        return FetchResult(items=items, etag=r.headers.get("ETag"), last_modified=r.headers.get("Last-Modified"))
    except httpx.HTTPError as ex:
        return FetchResult(status="FAILED", reason=f"{type(ex).__name__}: {ex}")
    except Exception as ex:  # never raise per source (ADR-009)
        return FetchResult(status="FAILED", reason=f"{type(ex).__name__}: {ex}")
