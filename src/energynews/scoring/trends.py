"""TrendEngine (FR-7, ADR-015): status, trajectory, hotness and hottest topics from the validated ledger. Pure."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from ..models import TOPIC_LABELS
from .weights import DEFAULT_TIER_WEIGHTS, age_hours, decay

Q2 = Decimal("0.01")


def _when(m: dict) -> datetime:
    if m.get("story_published_at"):
        return datetime.fromisoformat(m["story_published_at"])
    return datetime.fromisoformat(f"{m['date']}T12:00:00+00:00")


def compute_trends(ledger: dict | None, now: datetime, confirm_companies: int = 2, status_days: int = 30,
                   window_days: int = 7, tier_weights: dict[int, int] | None = None, half_life_hours: int = 72) -> list[dict]:
    w = tier_weights or DEFAULT_TIER_WEIGHTS
    cur_start, prev_start, status_start = now - timedelta(days=window_days), now - timedelta(days=2 * window_days), now - timedelta(days=status_days)
    views = []
    for t in (ledger or {}).get("trends", []):
        ms = [m for m in t["mentions"] if _when(m) <= now]
        ver = [m for m in ms if m.get("verified")]
        cur = [m for m in ver if _when(m) > cur_start]
        prev = [m for m in ver if prev_start < _when(m) <= cur_start]
        recent = [m for m in ver if _when(m) > status_start]
        comp_cur, comp_prev = {m["company_key"] for m in cur}, {m["company_key"] for m in prev}
        comp_recent = {m["company_key"] for m in recent}
        first = min((_when(m) for m in ver), default=None)
        if not recent:
            trajectory = "DORMANT"
        elif first and first > cur_start:
            trajectory = "NEW"
        elif len(comp_cur) > len(comp_prev) or (len(comp_cur) == len(comp_prev) and len(cur) > len(prev)):
            trajectory = "RISING"
        elif len(comp_cur) < len(comp_prev) or (len(comp_cur) == len(comp_prev) and len(cur) < len(prev)):
            trajectory = "FADING"
        else:
            trajectory = "STEADY"
        status = "CONFIRMED" if len(comp_recent) >= confirm_companies else ("EMERGING" if comp_recent else "DORMANT")
        stories = {}
        for m in cur:
            stories.setdefault(m["story_url"], m)
        hot = Decimal(3 * len(comp_cur))
        for url, m in sorted(stories.items()):
            hot += Decimal(w.get(int(m.get("tier", 3)), 1)) * decay(age_hours(now, _when(m)), half_life_hours)
        names = {}
        for m in sorted(recent, key=_when, reverse=True):
            names.setdefault(m["company_key"], m.get("company_name", m["company"]))
        latest = max((_when(m) for m in ver), default=None)
        views.append({
            "trend_id": t["trend_id"], "name": t["name"], "thesis": t["thesis"], "commodities": t["commodities"],
            "status": status, "trajectory": trajectory, "hotness": str(hot.quantize(Q2, ROUND_HALF_UP)),
            "companies_current": len(comp_cur), "companies_previous": len(comp_prev),
            "mentions_current": len(cur), "mentions_previous": len(prev), "companies_30d": len(comp_recent),
            "companies": list(names.values()), "first_seen": first.date().isoformat() if first else t.get("first_seen"),
            "latest_mention": latest.isoformat() if latest else None,
            "only_company_releases": bool(recent) and all(m.get("source_type") == "NEWSROOM" for m in recent),
            "timeline": [{"date": m["date"], "company": m.get("company_name", m["company"]), "action": m["action"], "story_url": m["story_url"],
                          "story_title": m.get("story_title", ""), "outlet": m.get("outlet", ""), "verified": bool(m.get("verified")),
                          "reason": m.get("reason")} for m in sorted(ms, key=_when, reverse=True)],
        })
    views.sort(key=lambda v: (-Decimal(v["hotness"]), -(datetime.fromisoformat(v["latest_mention"]).timestamp() if v["latest_mention"] else 0), v["trend_id"]))
    return views


def hottest(views: list[dict], n: int = 5, commodity: str | None = None) -> list[dict]:
    out = [v for v in views if v["status"] == "CONFIRMED" and v["trajectory"] != "DORMANT" and (commodity is None or commodity in v["commodities"])]
    return out[:n]


def candidate_groups(items: list[dict], min_companies: int = 2) -> list[dict]:
    """(topic, commodity) groups whose qualifying stories name >= 2 distinct companies. Hints for the author."""
    groups: dict[tuple, dict] = defaultdict(lambda: {"companies": {}, "stories": []})
    for it in items:
        comps = {o["org_id"]: o["name"] for o in it.get("organizations", []) if o["org_type"] == "COMPANY"}
        if not comps:
            continue
        for com in it["commodities"]:
            g = groups[(it["topic"], com)]
            g["companies"].update(comps)
            g["stories"].append({"cluster_id": it["cluster_id"], "title": it["title"], "url": it["sources"][0]["url"], "companies": sorted(comps.values())})
    out = []
    for (topic, com), g in groups.items():
        if len(g["companies"]) >= min_companies:
            out.append({"topic": topic, "topic_label": TOPIC_LABELS[topic], "commodity": com, "companies": sorted(g["companies"].values()),
                        "stories": g["stories"][:8]})
    out.sort(key=lambda g: (-len(g["companies"]), g["commodity"], g["topic"]))
    return out


def most_active_companies(items: list[dict], top: int = 15) -> list[dict]:
    counts: dict[str, dict] = {}
    for it in items:
        for o in it.get("organizations", []):
            if o["org_type"] != "COMPANY":
                continue
            c = counts.setdefault(o["org_id"], {"name": o["name"], "stories": 0, "commodities": set()})
            c["stories"] += 1
            c["commodities"].update(it["commodities"])
    ranked = sorted(counts.values(), key=lambda c: (-c["stories"], c["name"]))[:top]
    return [{"name": c["name"], "stories": c["stories"], "commodities": sorted(c["commodities"])} for c in ranked]
