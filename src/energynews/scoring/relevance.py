"""RelevanceRanker (FR-9): news-only formula (ADR-016)."""
from decimal import Decimal, ROUND_HALF_UP

TIER_SCORE = {1: Decimal("1.0"), 2: Decimal("0.66"), 3: Decimal("0.33")}


def relevance(cluster_weight: Decimal, best_tier: int) -> int:
    v = Decimal(100) * (Decimal("0.6") * min(cluster_weight / 10, Decimal(1)) + Decimal("0.4") * TIER_SCORE[best_tier])
    return int(v.quantize(Decimal(1), ROUND_HALF_UP))
