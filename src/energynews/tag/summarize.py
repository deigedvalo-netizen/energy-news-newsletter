"""Extractive summaries (FR-11)."""
from __future__ import annotations
import re

BOUNDARY = re.compile(r"[.!?]\s+(?=[A-Z0-9\"'(])")
ABBREV = re.compile(r"(?:\b[A-Z]\.){1,3}$|\b(?:Inc|Corp|Co|Ltd|Mr|Ms|Dr|St|vs|etc|No|Jan|Feb|Aug|Sept|Sep|Oct|Nov|Dec)\.$")


def split_sentences(text: str) -> list[str]:
    out, start = [], 0
    for m in BOUNDARY.finditer(text):
        chunk = text[start:m.start() + 1]
        if ABBREV.search(chunk):
            continue
        out.append(chunk.strip())
        start = m.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def first_sentence(text: str, limit: int = 280) -> str:
    parts = split_sentences((text or "").strip())
    return (parts[0] if parts else "")[:limit]
