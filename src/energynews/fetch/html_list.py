"""HTML_LIST adapter (FR-2): official listing pages without RSS.

Generic and selector-light: items are anchors whose href matches the source's link_pattern; the title is the anchor text
(or the nearest heading); the date is the nearest <time datetime> or a recognisable date string in the enclosing block.
Items without a parseable date become UNDATED downstream rather than guessed.
"""
from __future__ import annotations
from datetime import datetime, timezone
from urllib.parse import urljoin
import re
from bs4 import BeautifulSoup
from ..models import RawItem, Source

MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december"
DATE_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
    (re.compile(rf"\b({MONTHS})\.?\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.I), "mdy"),
    (re.compile(rf"\b(\d{{1,2}})\s+({MONTHS})\.?,?\s+(\d{{4}})\b", re.I), "dmy"),
    (re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b"), "dd/mm/yyyy"),
]
MONTH_NUM = {m[:3]: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date_text(text: str) -> datetime | None:
    for rx, kind in DATE_PATTERNS:
        m = rx.search(text or "")
        if not m:
            continue
        try:
            if kind == "ymd":
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif kind == "mdy":
                mo, d, y = MONTH_NUM[m.group(1).lower()[:3]], int(m.group(2)), int(m.group(3))
            elif kind == "dmy":
                d, mo, y = int(m.group(1)), MONTH_NUM[m.group(2).lower()[:3]], int(m.group(3))
            else:
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            # Date-only listings: noon UTC so the story lands on the stated calendar day in US and EU time zones.
            return datetime(y, mo, d, 12, 0, tzinfo=timezone.utc)
        except (ValueError, KeyError):
            continue
    return None


def _block(a):
    node = a
    for _ in range(4):
        if node.parent is None:
            break
        node = node.parent
        if node.name in ("li", "article", "tr") or (node.name == "div" and len(node.get_text(" ", strip=True)) > len(a.get_text(" ", strip=True)) + 8):
            return node
    return node


def parse_listing(html: str, src: Source, page_url: str) -> list[RawItem]:
    soup = BeautifulSoup(html, "html.parser")
    rx = re.compile(src.link_pattern)
    seen, items = set(), []
    for a in soup.find_all("a", href=True):
        href = urljoin(src.base_url or page_url, a["href"].strip())
        path = href
        if not rx.search(path):
            continue
        title = a.get_text(" ", strip=True)
        block = _block(a)
        if len(title) < 12:
            h = block.find(["h2", "h3", "h4"]) if block else None
            title = h.get_text(" ", strip=True) if h else title
        if len(title) < 12 or href in seen:
            continue
        seen.add(href)
        when = None
        t = block.find("time") if block else None
        if t is not None and t.get("datetime"):
            try:
                when = datetime.fromisoformat(t["datetime"].replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(hour=12, tzinfo=timezone.utc)
            except ValueError:
                when = None
        if when is None and block is not None:
            when = parse_date_text(block.get_text(" ", strip=True))
        summary = ""
        if block is not None:
            p = block.find("p")
            summary = p.get_text(" ", strip=True) if p else ""
        items.append(RawItem(src.source_id, href, title, summary, when.isoformat() if when else None, when.astimezone(timezone.utc) if when else None))
    return items
