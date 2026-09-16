"""Shared tier weighting and recency decay (FR-7, FR-9)."""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from ..models import Article, Cluster, Source

DEFAULT_TIER_WEIGHTS = {1: 3, 2: 2, 3: 1}


def decay(age_hours: Decimal, half_life_hours: int = 72) -> Decimal:
    return Decimal(2) ** (-(max(Decimal(0), age_hours) / Decimal(half_life_hours)))


def age_hours(now: datetime, t: datetime) -> Decimal:
    return Decimal(str((now - t).total_seconds())) / Decimal(3600)


def cluster_weight(cluster: Cluster, articles: dict[str, Article], sources: dict[str, Source], now: datetime,
                   tier_weights: dict[int, int] | None = None, half_life_hours: int = 72) -> Decimal:
    w = tier_weights or DEFAULT_TIER_WEIGHTS
    earliest: dict[str, datetime] = {}
    for aid in cluster.article_ids:
        a = articles[aid]
        if a.source_id not in earliest or a.published_at < earliest[a.source_id]:
            earliest[a.source_id] = a.published_at
    total = Decimal(0)
    for sid, t in sorted(earliest.items()):
        total += Decimal(w[sources[sid].tier]) * decay(age_hours(now, t), half_life_hours)
    return total
