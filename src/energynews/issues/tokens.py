"""AllowedTokens: numbers, URLs and quotable phrases present in a digest snapshot."""
from __future__ import annotations
from dataclasses import dataclass
import re
from .language import numbers_in

URL = re.compile(r"https?://[^\s)\]>\"']+")


@dataclass(frozen=True)
class AllowedTokens:
    numbers: frozenset[str]
    urls: frozenset[str]
    phrases: tuple[str, ...]  # snapshot text exempt from the advisory scan (e.g. copied headlines)


def _walk(o, out: list[str]):
    if isinstance(o, dict):
        for v in o.values():
            _walk(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk(v, out)
    elif o is not None:
        out.append(str(o))


def allowed_tokens(payload: dict) -> AllowedTokens:
    strings: list[str] = []
    _walk(payload, strings)
    urls, nums = set(), set()
    for s in strings:
        urls.update(u.rstrip(".,") for u in URL.findall(s))
        nums |= numbers_in(URL.sub(" ", s))
        for m in re.finditer(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?", s):
            for g in m.groups():
                if g:
                    nums.add(g.lstrip("0") or "0")
                    nums.add(g)
    phrases = []
    for item in payload.get("feed", []):
        phrases += [item.get("title", ""), item.get("summary", "")]
        phrases += [x.get("title", "") for x in item.get("sources", [])] + [x.get("excerpt", "") for x in item.get("sources", [])]
        phrases += [f.get("context", "") for f in item.get("figures", [])]
    for v in payload.get("trends", {}).get("all", []):
        phrases += [v.get("name", ""), v.get("thesis", "")] + [m.get("story_title", "") for m in v.get("timeline", [])] + [m.get("action", "") for m in v.get("timeline", [])]
    phrases = tuple(sorted({p for p in phrases if p and len(p) >= 12}, key=len, reverse=True))
    return AllowedTokens(frozenset(nums), frozenset(urls), phrases)
