"""ArticleExtractor (FR-3)."""
from __future__ import annotations
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
import re
import httpx
from ..fetch.urls import canonicalize_url
from ..models import Article, RawItem, Source

TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")


def clean_text(s: str) -> str:
    return WS.sub(" ", html.unescape(TAG.sub(" ", s or ""))).strip()


def excerpt_of(text: str, limit: int = 300) -> str:
    text = clean_text(text)
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > limit * 0.6 else cut).rstrip() + "…"


def parse_published(item: RawItem) -> datetime | None:
    if item.published_parsed:
        return item.published_parsed.astimezone(timezone.utc)
    if not item.published:
        return None
    s = item.published.strip()
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        return None  # ambiguous zone -> treat as undated rather than guess
    return d.astimezone(timezone.utc)


def fetch_body(url: str, http: httpx.Client) -> str:
    import trafilatura
    try:
        r = http.get(url, timeout=30, follow_redirects=True)
        if r.status_code >= 400:
            return ""
        return trafilatura.extract(r.text, include_comments=False, include_tables=False) or ""
    except Exception:
        return ""


def extract_article(item: RawItem, src: Source, http: httpx.Client | None, now: datetime,
                    excerpt_chars: int = 300, robots=None) -> tuple[Article, str]:
    """Returns (article, transient body text). Body is never persisted (NFR-4)."""
    url = canonicalize_url(item.url)
    summary = clean_text(item.summary)
    body = ""
    if src.tos_status == "ALLOWED" and http is not None and (robots is None or robots.allowed(item.url)):
        body = fetch_body(item.url, http)
    text = body or summary
    published = parse_published(item)
    a = Article(
        article_id=hashlib.sha256(url.encode()).hexdigest()[:16],
        source_id=src.source_id, canonical_url=url, title=clean_text(item.title),
        published_at=published, excerpt=excerpt_of(summary or body, excerpt_chars),
        content_hash=hashlib.sha256((item.title + "\n" + text).encode()).hexdigest(),
        status="OK" if published else "UNDATED", fetched_at=now,
    )
    return a, clean_text(item.title) + ". " + text
