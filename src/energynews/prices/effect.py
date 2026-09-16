"""PriceEffectCalculator (FR-8): pure Decimal functions; correlation only; never interpolates."""
from __future__ import annotations
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from ..models import Cluster, PriceEffect
from .calendar import TradingCalendar, event_day

Q4 = Decimal("0.0001")
Q2 = Decimal("0.01")


def day_move(p_t: Decimal, p_prev: Decimal) -> Decimal:
    return p_t / p_prev - 1


def sigma20(prices: dict[date, Decimal], before: date) -> Decimal | None:
    ds = sorted(d for d in prices if d < before)[-21:]
    if len(ds) < 21:
        return None
    rets = [prices[ds[i]] / prices[ds[i - 1]] - 1 for i in range(1, 21)]
    mean = sum(rets) / 20
    var = sum((r - mean) ** 2 for r in rets) / 19
    return var.sqrt() if var > 0 else None


def zscore(move: Decimal, sigma: Decimal | None) -> Decimal | None:
    return (move / sigma).quantize(Q2, ROUND_HALF_UP) if sigma else None


def compute_price_effect(cluster: Cluster, benchmark: str, bcfg: dict, prices: dict[date, Decimal], cal: TradingCalendar) -> PriceEffect:
    T = event_day(cluster.first_published_at, bcfg["settle_tz"], bcfg["settle_time"], cal)
    prev = cal.prev_trading_day(T)
    eff = PriceEffect(cluster.cluster_id, benchmark, T, "OK", prev_day=prev)
    latest = max(prices) if prices else None
    if T not in prices:
        eff.status = "PENDING" if latest is not None and T > latest else "PRICE_MISSING"
        return eff
    if prev not in prices:
        eff.status = "PRICE_MISSING"
        return eff
    eff.p_t, eff.p_prev = prices[T], prices[prev]
    mv = day_move(eff.p_t, eff.p_prev)
    eff.day_move = mv.quantize(Q4, ROUND_HALF_UP)
    nxt = cal.next_trading_day(T)
    eff.two_day_move = (prices[nxt] / eff.p_prev - 1).quantize(Q4, ROUND_HALF_UP) if nxt in prices else ("PENDING" if latest is None or nxt > latest else None)
    s = sigma20(prices, T)
    eff.sigma20 = s.quantize(Decimal("0.000001"), ROUND_HALF_UP) if s else None
    eff.z = zscore(mv, s)
    return eff


def mark_confounded(effects: list[PriceEffect]) -> list[PriceEffect]:
    groups = defaultdict(list)
    for e in effects:
        groups[(e.benchmark, e.event_day)].append(e)
    for g in groups.values():
        if len(g) > 1:
            ids = sorted(e.cluster_id for e in g)
            for e in g:
                e.confounded_with = [i for i in ids if i != e.cluster_id]
    return effects


def fmt_pct(v: Decimal | None) -> str | None:
    if v is None or isinstance(v, str):
        return v
    p = (v * 100).quantize(Q2, ROUND_HALF_UP)
    return f"{'+' if p >= 0 else ''}{p}%"


def fmt_z(z: Decimal | None) -> str | None:
    return None if z is None else f"z {'+' if z >= 0 else ''}{z}"
