"""FigureExtractor (FR-6): verbatim figure spans from allowed text; conflicts flagged; no arithmetic."""
from __future__ import annotations
from collections import defaultdict
import re
from ..models import Article, ExtractedFigure, Flag
from .summarize import split_sentences

NUM_UNIT = re.compile(
    r"(?<![\w.])[$€£]?\d[\d,]*(?:\.\d+)?\s?(?:million|billion|thousand|mln|bln)?\s?"
    r"(?:barrels per day|barrels a day|barrels|bpd|b/d|bcf|billion cubic feet|cubic feet|mmbtu|tonnes|tons|gallons|"
    r"cents per gallon|per gallon|a gallon|per barrel|a barrel|percent|%|rigs|allowances|credits|tCO2e?|mtpa|MW|GW)(?![\w])", re.I)
KEYWORDS = ["inventor", "stock", "storage", "production", "output", "export", "import", "cut", "quota", "demand", "capacity",
            "consumption", "injection", "withdrawal", "refin", "allowance", "credit", "removal", "auction", "offtake", "purchase"]
UNIT_RX = re.compile(r"[a-z%/][a-z%/0-9 ]*$", re.I)
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def extract_figures(a: Article, text: str, max_figures: int = 6) -> list[Flag]:
    seen = set()
    for sent in split_sentences(text):
        low = sent.lower()
        kw = next((k for k in KEYWORDS if k in low), None)
        if not kw:
            continue
        for m in NUM_UNIT.finditer(sent):
            span = m.group(0).strip()
            ctx = sent.strip()
            if len(ctx) > 220:
                s = max(0, m.start() - 100)
                ctx = sent[s:s + 220].strip()
            if span not in text or (span, ctx) in seen:
                continue
            seen.add((span, ctx))
            um = UNIT_RX.search(span)
            a.figures.append(ExtractedFigure(a.article_id, span, ctx, um.group(0).strip().lower() if um else "", kw))
            if len(a.figures) >= max_figures:
                return []
    return []


def conflicting_figures(cluster_id: str, articles: list[Article]) -> tuple[list[Flag], bool]:
    groups = defaultdict(set)
    for a in articles:
        for f in a.figures:
            m = NUM.search(f.span)
            if m and f.keyword:
                groups[(f.keyword, f.unit)].add((m.group(0).replace(",", ""), a.source_id))
    for (kw, unit), vals in groups.items():
        by_value = defaultdict(set)
        for v, s in vals:
            by_value[v].add(s)
        if len(by_value) > 1 and len({s for _, s in vals}) > 1:
            return [Flag("CONFLICTING_FIGURES", cluster_id, f"'{kw}' in {unit or 'units'}: values {sorted(by_value)}")], True
    return [], False
