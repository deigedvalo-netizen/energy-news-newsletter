"""DigestBuilder (FR-9, FR-10, FR-16): snapshot JSON (validator source of truth) + compact Markdown for the author."""
from __future__ import annotations
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from ..models import TOPIC_LABELS, Article, Cluster, Source
from ..scoring.relevance import relevance
from ..scoring.trends import candidate_groups, hottest, most_active_companies

SCHEMA_VERSION = "digest.v2"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def local(dt: datetime, tz: str) -> str:
    return dt.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M CT")


def next_release(rel: dict, now: datetime, tz_out: str) -> dict:
    tz = ZoneInfo(rel["tz"])
    hh, mm = map(int, rel["time"].split(":"))
    d = now.astimezone(tz).date()
    for i in range(8):
        cand = d + timedelta(days=i)
        if cand.weekday() == rel["weekday"]:
            at = datetime(cand.year, cand.month, cand.day, hh, mm, tzinfo=tz)
            if at > now:
                out = at.astimezone(ZoneInfo(tz_out))
                return {"id": rel["id"], "name": rel["name"], "commodities": rel["commodities"], "at": at.isoformat(),
                        "at_local": f"{WEEKDAYS[out.weekday()]} {out.strftime('%Y-%m-%d %H:%M')} CT"}
    return {}


def build_payload(*, now: datetime, settings, sources: dict[str, Source], articles: dict[str, Article], clusters: list[Cluster],
                  weights: dict[str, Decimal], trend_views: list[dict], conflicts: set[str], flags: list[dict], run: dict,
                  references: list[Source]) -> dict:
    tz = settings["timezone"]
    cfg_c = settings["commodities"]
    window_start = now - timedelta(days=settings["window_days"])
    threshold = settings["feed"]["relevance_threshold"]
    trend_by_url: dict[str, set] = {}
    for v in trend_views:
        for m in v["timeline"]:
            trend_by_url.setdefault(m["story_url"], set()).add(v["trend_id"])

    items = []
    for c in clusters:
        if not (window_start <= c.first_published_at <= now):
            continue
        members = sorted(c.article_ids, key=lambda i: (sources[articles[i].source_id].tier, articles[i].published_at, i))
        rel = relevance(weights[c.cluster_id], c.best_tier)
        if rel < threshold:
            continue
        srcs, seen, figs, fseen = [], set(), [], set()
        for aid in members:
            a = articles[aid]
            s = sources[a.source_id]
            if a.canonical_url not in seen:
                seen.add(a.canonical_url)
                srcs.append({"outlet": s.name, "tier": s.tier, "source_type": s.source_type, "title": a.title, "url": a.canonical_url,
                             "excerpt": a.excerpt, "organizations": a.organizations,
                             "published_at": a.published_at.isoformat(), "published_local": local(a.published_at, tz)})
            for f in a.figures:
                if (f.span, a.source_id) not in fseen:
                    fseen.add((f.span, a.source_id))
                    figs.append({"span": f.span, "context": f.context, "outlet": s.name, "url": a.canonical_url})
        linked = sorted(set().union(*(trend_by_url.get(x["url"], set()) for x in srcs)))
        items.append({
            "cluster_id": c.cluster_id, "title": c.title, "summary": c.summary,
            "first_published_at": c.first_published_at.isoformat(), "published_local": local(c.first_published_at, tz),
            "commodities": sorted(x.value for x in c.commodities), "topic": c.topic, "topic_label": TOPIC_LABELS[c.topic],
            "organizations": c.organizations, "distinct_source_count": c.distinct_source_count, "best_tier": c.best_tier,
            "relevance": rel, "relevance_inputs": {"cluster_weight": str(weights[c.cluster_id].quantize(Decimal("0.01"))), "best_tier": c.best_tier},
            "figures": figs[:6], "sources": srcs, "trend_ids": linked,
            "flags": ["CONFLICTING_FIGURES"] if c.cluster_id in conflicts else [],
        })
    items.sort(key=lambda i: (i["first_published_at"], i["cluster_id"]), reverse=True)

    n = settings["trends"]["hottest_n"]
    calendar = sorted((r for r in (next_release(x, now, tz) for x in settings.raw.get("release_calendar", [])) if r), key=lambda r: r["at"])
    active = most_active_companies(items)
    groups = candidate_groups(items)
    tabs = [{"id": "all", "label": "All"}] + [{"id": v["slug"], "commodity": k, "label": v["label"]} for k, v in cfg_c.items()]
    refs = settings.raw.get("site", {}).get("reference_links", {})
    payload = {
        "schema": SCHEMA_VERSION, "generated_at": now.isoformat(), "data_as_of": now.isoformat(), "data_as_of_local": local(now, tz),
        "timezone": tz, "window_days": settings["window_days"], "relevance_threshold": threshold, "page_size": settings["feed"]["page_size"],
        "stale_after_hours": settings["freshness"]["stale_after_hours"], "analysis_max_age_hours": settings["analysis"]["max_age_hours"],
        "site": {"title": settings["site"]["title"], "banner": settings["site"]["banner"]},
        "tabs": tabs, "feed": items,
        "trends": {"all": trend_views, "hottest": hottest(trend_views, n),
                   **{k: hottest(trend_views, n, k) for k in cfg_c}},
        "candidate_groups": groups, "most_active_companies": active, "calendar": calendar,
        "reference_links": refs,
        "sources": {s.source_id: {"name": s.name, "tier": s.tier, "source_type": s.source_type, "tos_status": s.tos_status} for s in sources.values()},
        "flags": flags, "run": run,
        "disclaimer": "Private preview for a small readership. Generated automatically from public news sources. Unverified, informational only. Not investment advice.",
    }
    payload["synopsis"] = build_synopsis(payload, settings)
    return payload


def build_synopsis(p: dict, settings) -> dict:
    cfg_c = settings["commodities"]
    days = p["window_days"]
    per = {}
    for com, cc in cfg_c.items():
        items = [i for i in p["feed"] if com in i["commodities"]]
        hot = p["trends"].get(com, [])
        s = []
        label = cc["label"]
        if not items:
            s.append(f"{label}: no qualifying stories in the last {days} days.")
        else:
            s.append(f"{label}: {len(items)} qualifying stor{'y' if len(items) == 1 else 'ies'} in the last {days} days.")
            lead = max(items, key=lambda i: (i["relevance"], i["first_published_at"]))
            s.append(f"Highest-relevance story: “{lead['title']}” ({lead['sources'][0]['outlet']}, {lead['published_local']}).")
        if hot:
            t = hot[0]
            s.append(f"Hottest trend: {t['name']} ({t['trajectory']}, {t['companies_current']} compan{'y' if t['companies_current'] == 1 else 'ies'} this week vs {t['companies_previous']} last week).")
        comps = [c["name"] for c in p["most_active_companies"] if com in c["commodities"]][:3]
        if comps:
            s.append("Most active companies: " + ", ".join(comps) + ".")
        nxt = next((r for r in p["calendar"] if com in r["commodities"]), None)
        if nxt:
            s.append(f"Next scheduled release: {nxt['name']}, {nxt['at_local']}.")
        per[com] = {"label": label, "stories": len(items), "sentences": s}
    overall = [f"{len(p['feed'])} qualifying stor{'y' if len(p['feed']) == 1 else 'ies'} from reputable sources in the last {days} days."]
    if p["trends"]["hottest"]:
        overall.append("Hottest trends: " + "; ".join(f"{t['name']} ({t['trajectory']})" for t in p["trends"]["hottest"][:3]) + ".")
    overall.append("Stories by commodity: " + ", ".join(f"{v['label']} {v['stories']}" for v in per.values()) + ".")
    return {"label": "Automated synopsis (data only, no interpretation)", "overall": {"sentences": overall}, "commodities": per}


def build_markdown(p: dict, settings, max_bytes: int) -> str:
    cfg_c = settings["commodities"]
    head = [f"# Energy news digest — data as of {p['data_as_of_local']}",
            f"schema {p['schema']} · {len(p['feed'])} qualifying stories (last {p['window_days']} days, relevance >= {p['relevance_threshold']}).",
            "Only link URLs that appear in this digest. Story ids like [c:abc123] are for reference.", ""]
    trends = ["## Current trends (validated ledger)", ""]
    if p["trends"]["all"]:
        trends.append("| trend_id | name | status | trajectory | companies this wk / last wk | hotness | commodities | companies |")
        trends.append("|---|---|---|---|---|---|---|---|")
        for v in p["trends"]["all"]:
            if v["trajectory"] == "DORMANT":
                continue
            trends.append(f"| {v['trend_id']} | {v['name']} | {v['status']} | {v['trajectory']} | {v['companies_current']} / {v['companies_previous']} | {v['hotness']} | {', '.join(v['commodities'])} | {', '.join(v['companies'][:6])} |")
    else:
        trends.append("No trends recorded yet. Start the ledger from the candidate groups below.")
    trends.append("")
    groups = ["## Candidate trend groups (hints: stories naming 2+ companies)", ""]
    for g in p["candidate_groups"][:12]:
        groups.append(f"- **{g['topic_label']} · {cfg_c[g['commodity']]['label']}** — companies: {', '.join(g['companies'][:10])}")
        for st in g["stories"][:5]:
            groups.append(f"  - [c:{st['cluster_id']}] {st['title']} ({', '.join(st['companies'])}) {st['url']}")
    if not p["candidate_groups"]:
        groups.append("None today.")
    groups.append("")
    active = ["## Most active companies (last 7 days)", ""] + [f"- {c['name']}: {c['stories']} stories ({', '.join(cfg_c[x]['label'] for x in c['commodities'])})" for c in p["most_active_companies"]] + [""]
    cal = ["## Scheduled releases", ""] + [f"- {r['at_local']} — {r['name']}" for r in p["calendar"]] + [""]

    def story_md(i: dict) -> str:
        lines = [f"### [c:{i['cluster_id']}] {i['title']}",
                 f"{i['published_local']} · relevance {i['relevance']} · {i['topic_label']} · {', '.join(cfg_c[c]['label'] for c in i['commodities'])}"
                 + (f" · trends: {', '.join(i['trend_ids'])}" if i["trend_ids"] else "")]
        orgs = [o["name"] for o in i["organizations"]]
        if orgs:
            lines.append("Organizations: " + ", ".join(orgs))
        if i["summary"]:
            lines.append(f"Summary: {i['summary']}")
        for s in i["sources"][:4]:
            lines.append(f"- {s['outlet']} (tier {s['tier']}, {s['source_type']}): {s['title']} — {s['url']}")
        for f in i["figures"][:3]:
            lines.append(f"- figure: “{f['span']}” — {f['outlet']}")
        return "\n".join(lines) + "\n"

    fixed = "\n".join(head + trends + groups + active + cal)
    budget = max_bytes - len(fixed.encode()) - 400
    sections, omitted_total = [], 0
    per_com = {com: [i for i in p["feed"] if i["commodities"][0] == com] for com in cfg_c}
    ranked = {com: sorted(v, key=lambda i: (-i["relevance"], i["first_published_at"])) for com, v in per_com.items()}
    chosen = {com: [] for com in cfg_c}
    # round-robin by relevance so every commodity gets coverage within the byte budget
    progress = True
    while progress:
        progress = False
        for com in cfg_c:
            if len(chosen[com]) < len(ranked[com]):
                md = story_md(ranked[com][len(chosen[com])])
                if len(md.encode()) <= budget:
                    chosen[com].append(md)
                    budget -= len(md.encode())
                    progress = True
    for com, cc in cfg_c.items():
        omitted = len(ranked[com]) - len(chosen[com])
        omitted_total += omitted
        sections.append(f"## {cc['label']} stories ({len(ranked[com])})\n")
        sections.extend(chosen[com] or ["No qualifying stories.\n"])
        if omitted:
            sections.append(f"_{omitted} lower-relevance stories omitted to keep the digest under {max_bytes // 1000} KB._\n")
    return fixed + "\n" + "\n".join(sections)
