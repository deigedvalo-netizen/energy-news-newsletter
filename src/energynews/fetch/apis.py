"""News API adapters (FR-1, FR-2): GDELT DOC 2.0 (no key), Guardian Open Platform and NewsData.io (keys from env).

Keys come only from environment variables (GitHub secrets) and are redacted from every status/reason string, because run
reports are published on the public site. Each adapter returns FetchResult and never raises.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import os
import time
from urllib.parse import urlsplit
import httpx
from ..models import RawItem, Source

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GUARDIAN_URL = "https://content.guardianapis.com/search"
NEWSDATA_URL = "https://newsdata.io/api/1/latest"
GDELT_PAUSE_S = 6.0  # GDELT asks for at most one request every 5 seconds
GDELT_DOMAIN_CHUNK = 8
GDELT_RETRY_S = (0, 20, 45)
_last_gdelt = [0.0]


def _redact(text: str, *secrets: str | None) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def _web(url: str | None) -> bool:
    if not url:
        return False
    p = urlsplit(url.strip())
    return p.scheme in ("http", "https") and bool(p.netloc)


def _domain_ok(url: str, domains: list[str]) -> bool:
    if not domains:
        return True
    host = urlsplit(url).netloc.lower().split(":")[0]
    return any(host == d or host.endswith("." + d) for d in domains)


def _or(terms: list[str]) -> str:
    return terms[0] if len(terms) == 1 else "(" + " OR ".join(terms) + ")"


def _gdelt_time(s: str | None) -> datetime | None:
    try:
        return datetime.strptime(s or "", "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def fetch_gdelt(src: Source, http: httpx.Client, sleep=time.sleep) -> tuple[list[RawItem], list[str]]:
    opt = src.options or {}
    domains = [d.lower() for d in opt.get("domains") or []]
    params = {"timespan": "2d", "maxrecords": 250, **opt.get("params", {})}
    chunks = [domains[i:i + GDELT_DOMAIN_CHUNK] for i in range(0, len(domains), GDELT_DOMAIN_CHUNK)] or [[]]
    items, errors, seen = [], [], set()
    for q in opt["queries"]:
        for chunk in chunks:
            query = q.strip() + (" " + _or([f"domain:{d}" for d in chunk]) if chunk else "") + " sourcelang:english"
            wait = GDELT_PAUSE_S - (time.monotonic() - _last_gdelt[0])
            if _last_gdelt[0] and wait > 0:
                sleep(wait)
            r, last = None, ""
            for backoff in GDELT_RETRY_S:  # GDELT throttles shared cloud IPs: back off, then give up for this run
                if backoff:
                    sleep(backoff)
                _last_gdelt[0] = time.monotonic()
                try:
                    r = http.get(GDELT_URL, params={"query": query, "mode": "artlist", "format": "json", "sort": "datedesc", **params}, timeout=45)
                except httpx.TransportError as ex:
                    r, last = None, type(ex).__name__
                    continue
                if r.status_code != 429:
                    break
                last = "HTTP 429"
            if r is None or r.status_code == 429:
                errors.append(f"{last} after {len(GDELT_RETRY_S)} tries")
                return items, errors
            if r.status_code >= 400:
                errors.append(f"HTTP {r.status_code}")
                continue
            try:
                data = r.json()
            except ValueError:  # GDELT answers query errors and rate limits in plain text
                errors.append(r.text.strip()[:120] or "empty response")
                continue
            for a in data.get("articles") or []:
                url, title = a.get("url"), (a.get("title") or "").strip()
                if not title or not _web(url) or not _domain_ok(url, domains) or url in seen:
                    continue
                seen.add(url)
                items.append(RawItem(src.source_id, url, title, "", a.get("seendate"), _gdelt_time(a.get("seendate"))))
    return items, errors


def fetch_guardian(src: Source, http: httpx.Client, key: str, now: datetime) -> tuple[list[RawItem], list[str]]:
    opt = src.options or {}
    base = {"api-key": key, "page-size": 50, "order-by": "newest", "show-fields": "trailText",
            "from-date": (now - timedelta(days=2)).date().isoformat(), **opt.get("params", {})}
    items, errors, seen = [], [], set()
    for q in opt["queries"]:
        r = http.get(GUARDIAN_URL, params={**base, "q": q}, timeout=30)
        if r.status_code >= 400:
            errors.append(f"HTTP {r.status_code}")
            continue
        resp = (r.json() or {}).get("response") or {}
        if resp.get("status") != "ok":
            errors.append(str(resp.get("message", "error"))[:120])
            continue
        for a in resp.get("results") or []:
            url, title = a.get("webUrl"), (a.get("webTitle") or "").strip()
            if not title or not _web(url) or url in seen:
                continue
            seen.add(url)
            items.append(RawItem(src.source_id, url, title, (a.get("fields") or {}).get("trailText", "") or "",
                                 a.get("webPublicationDate")))
    return items, errors


def _newsdata_time(s: str | None) -> datetime | None:
    try:
        return datetime.strptime(s or "", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)  # NewsData pubDate is UTC
    except ValueError:
        return None


def fetch_newsdata(src: Source, http: httpx.Client, key: str) -> tuple[list[RawItem], list[str]]:
    opt = src.options or {}
    domains = [d.lower() for d in opt.get("domains") or []]
    pages = int(opt.get("params", {}).get("pages", 2))
    base = {"apikey": key, "language": "en", "removeduplicate": 1,
            **{k: v for k, v in opt.get("params", {}).items() if k != "pages"}}
    items, errors, seen = [], [], set()
    for q in opt["queries"]:
        page = None
        for _ in range(max(1, pages)):
            params = {**base, "q": q, **({"page": page} if page else {})}
            r = http.get(NEWSDATA_URL, params=params, timeout=30)
            try:
                data = r.json()
            except ValueError:
                data = {}
            if r.status_code >= 400 or data.get("status") != "success":
                res = data.get("results")
                msg = res.get("message") if isinstance(res, dict) else None
                errors.append(f"HTTP {r.status_code}: {str(msg or r.text)[:100]}")
                break
            for a in data.get("results") or []:
                url, title = a.get("link"), (a.get("title") or "").strip()
                if not title or not _web(url) or not _domain_ok(url, domains) or url in seen:
                    continue
                seen.add(url)
                items.append(RawItem(src.source_id, url, title, a.get("description") or "", a.get("pubDate"),
                                     _newsdata_time(a.get("pubDate"))))
            page = data.get("nextPage")
            if not page:
                break
    return items, errors


def fetch_api_source(src: Source, http: httpx.Client, now: datetime | None = None, sleep=time.sleep):
    from .fetcher import FetchResult
    now = now or datetime.now(timezone.utc)
    env = (src.options or {}).get("api_key_env")
    key = os.environ.get(env, "").strip() if env else ""
    if env and not key:
        return FetchResult(status="SKIPPED", reason=f"no {env} secret set")
    try:
        if src.access_method == "API_GDELT":
            items, errors = fetch_gdelt(src, http, sleep)
        elif src.access_method == "API_GUARDIAN":
            items, errors = fetch_guardian(src, http, key, now)
        elif src.access_method == "API_NEWSDATA":
            items, errors = fetch_newsdata(src, http, key)
        else:
            return FetchResult(status="FAILED", reason=f"unknown API {src.access_method}")
    except Exception as ex:  # never raise per source (ADR-009); httpx errors include the URL, so redact
        return FetchResult(status="FAILED", reason=_redact(f"{type(ex).__name__}: {ex}", key)[:200])
    reason = _redact("; ".join(dict.fromkeys(errors)), key)[:200] or None
    if not items and errors:
        return FetchResult(status="FAILED", reason=reason)
    return FetchResult(items=items, reason=reason)
