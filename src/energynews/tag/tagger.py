"""Deterministic Tagger (FR-4, ADR-014): commodities, topic and organizations; no LLM."""
from __future__ import annotations
from ..models import Article, Flag
from .organizations import OrganizationIndex
from .taxonomy import keyword_classify


def tag_article(a: Article, text: str, orgs: OrganizationIndex) -> list[Flag]:
    comms, topic = keyword_classify(text, a.title)
    if not comms:
        if a.status == "OK":
            a.status = "NOT_RELEVANT"
        return []
    a.commodities, a.topic = frozenset(comms), topic
    a.organizations = orgs.tag(text)
    return []
