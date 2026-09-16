"""RunOrchestrator (FR-13): daily scan. python -m energynews.run --db data/energynews.db --site site
No LLM calls (ADR-014). Prices are not touched while settings prices.enabled is false (FR-8, NFR-9).
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import json
import os
import uuid
import httpx
from .cluster.clusterer import cluster_articles
from .config import ROOT, load_settings
from .extract.extractor import extract_article
from .fetch.fetcher import USER_AGENT, Robots, fetch_source
from .fetch.urls import canonicalize_url
from .models import Flag
from .publish.digest import build_markdown, build_payload
from .publish.render import archive_issue, oversized_files, prune_snapshots, render_site, write_snapshot
from .scoring.trends import compute_trends
from .scoring.weights import cluster_weight
from .sources.registry import eligible_sources, load_registry, reference_sources, skipped_sources
from .store.db import ArticleStore
from .tag.figures import conflicting_figures, extract_figures
from .tag.organizations import OrganizationIndex
from .tag.summarize import first_sentence
from .tag.tagger import tag_article


def load_published_ledger(site_dir: Path) -> dict | None:
    p = site_dir / "trends" / "ledger.json"
    return json.loads(p.read_text()) if p.exists() else None


def write_trend_views(site_dir: Path, views: list[dict], now: datetime):
    (site_dir / "trends").mkdir(parents=True, exist_ok=True)
    (site_dir / "trends" / "trends.json").write_text(json.dumps({"computed_at": now.isoformat(), "trends": views}, indent=1))


def run_pipeline(*, db_path: Path, site_dir: Path, registry_path: Path, settings_path: Path | None = None,
                 orgs_path: Path | None = None, http: httpx.Client | None = None, now: datetime | None = None, fetch: bool = True) -> dict:
    settings = load_settings(settings_path)
    now = now or datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    http = http or httpx.Client(headers={"User-Agent": USER_AGENT})
    store = ArticleStore(db_path)
    reg = load_registry(registry_path)
    orgs = OrganizationIndex.load(orgs_path or ROOT / "config" / "organizations.yaml")
    sources = {s.source_id: s for s in reg}
    flags: list[Flag] = []
    report = {"run_id": run_id, "started_at": now.isoformat(), "sources": [], "sources_skipped": [], "new_articles": 0,
              "clusters": 0, "published": False, "prices_enabled": bool(settings["prices"]["enabled"])}
    robots = Robots(http)
    report["sources_skipped"] = [{"source_id": s.source_id, "tos_status": s.tos_status, "enabled": s.enabled} for s in skipped_sources(reg)]
    if fetch:
        for src in eligible_sources(reg):
            h = store.health(src.source_id)
            res = fetch_source(src, h, http, robots)
            h.last_status, h.reason = res.status, res.reason
            if res.status in ("FAILED", "ROBOTS_DISALLOWED"):
                h.consecutive_failures += 1
                if res.status == "ROBOTS_DISALLOWED":
                    flags.append(Flag("ROBOTS_DISALLOWED", src.source_id, res.reason or ""))
                if res.reason == "SELECTOR_NO_MATCH":
                    flags.append(Flag("SELECTOR_NO_MATCH", src.source_id, "link_pattern matched no items"))
                if h.consecutive_failures >= 3:
                    flags.append(Flag("STALE_SOURCE", src.source_id, f"failed {h.consecutive_failures} consecutive runs: {res.reason}"))
            else:
                h.consecutive_failures = 0
                h.etag, h.last_modified = res.etag or h.etag, res.last_modified or h.last_modified
            store.save_health(h, now)
            new = 0
            for item in res.items:
                if store.has_url(canonicalize_url(item.url)):
                    continue
                a, text = extract_article(item, src, http, now, settings["storage"]["excerpt_chars"], robots)
                if a.status == "UNDATED":
                    flags.append(Flag("UNDATED", a.article_id, f"{src.source_id}: {a.title[:80]}"))
                else:
                    flags.extend(tag_article(a, text, orgs))
                    if a.status == "OK":
                        extract_figures(a, text if src.tos_status == "ALLOWED" else a.title + ". " + a.excerpt)
                if store.insert_article(a):
                    new += 1
            report["new_articles"] += new
            report["sources"].append({"source_id": src.source_id, "tier": src.tier, "status": res.status, "reason": res.reason,
                                      "items_seen": len(res.items), "new": new})
            store.commit()

    lookback = now - timedelta(days=settings["cluster"]["lookback_days"])
    arts = [a for a in store.articles_since(lookback) if a.published_at <= now]
    amap = {a.article_id: a for a in arts}
    clusters = cluster_articles(arts, Decimal(settings["cluster"]["similarity_threshold"]), settings["cluster"]["window_hours"])
    clusters = [c for c in clusters if c.first_published_at >= now - timedelta(days=settings["window_days"])]
    tw = {int(k): v for k, v in settings["weights"]["tier_weights"].items()}
    hl = settings["weights"]["half_life_hours"]
    weights = {c.cluster_id: cluster_weight(c, amap, sources, now, tw, hl) for c in clusters}
    conflicts = set()
    for c in clusters:
        members = sorted((amap[i] for i in c.article_ids), key=lambda a: (sources[a.source_id].tier, a.published_at, a.article_id))
        c.title, c.best_tier = members[0].title, sources[members[0].source_id].tier
        c.summary = next((first_sentence(m.excerpt) for m in members if m.excerpt), "")
        seen = {}
        for m in members:
            for o in m.organizations:
                seen.setdefault(o["org_id"], o)
        c.organizations = sorted(seen.values(), key=lambda o: o["name"])
        cf, has = conflicting_figures(c.cluster_id, members)
        flags.extend(cf)
        if has:
            conflicts.add(c.cluster_id)
    report["clusters"] = len(clusters)

    ledger = load_published_ledger(site_dir)
    t = settings["trends"]
    views = compute_trends(ledger, now, t["confirm_companies"], t["status_window_days"], t["trajectory_window_days"], tw, hl)
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    payload = build_payload(now=now, settings=settings, sources=sources, articles=amap, clusters=clusters, weights=weights,
                            trend_views=views, conflicts=conflicts, flags=[asdict(f) for f in flags],
                            run={k: report[k] for k in ("run_id", "new_articles", "clusters")}, references=reference_sources(reg))
    md = build_markdown(payload, settings, settings["digest"]["max_bytes"])
    report["digest_bytes"] = len(md.encode())

    sha = render_site(payload, site_dir, settings["site"].get("custom_domain", ""))
    ref = write_snapshot(site_dir, sha, payload["data_as_of"], md)
    write_trend_views(site_dir, views, now)
    prune_snapshots(site_dir, now, settings["storage"]["snapshot_retention_days"], keep={sha})
    report["archived_week"] = archive_issue(site_dir, now, settings["timezone"], settings["archive"]["weekday"], settings["archive"]["hour"])
    report["feed_sha256"] = ref["feed_sha256"]
    (site_dir / "runs").mkdir(exist_ok=True)
    (site_dir / "runs" / "latest.json").write_text(json.dumps(report, indent=1, default=str))

    store.prune(now, settings["storage"]["article_retention_days"])
    store.add_flags(run_id, flags, now)
    store.save_run(run_id, report)
    store.vacuum()
    store.close()
    too_big = oversized_files(site_dir, settings["storage"]["max_file_bytes"])
    if Path(db_path).exists() and Path(db_path).stat().st_size > settings["storage"]["max_file_bytes"]:
        too_big.append(str(db_path))
    if too_big:
        raise SystemExit(f"STORAGE_LIMIT: files over limit {too_big}; aborting publish (NFR-6)")
    report["published"] = True
    return report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/energynews.db")
    ap.add_argument("--site", default="site")
    ap.add_argument("--registry", default=str(ROOT / "config" / "sources.yaml"))
    ap.add_argument("--settings", default=None)
    ap.add_argument("--organizations", default=None)
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args(argv)
    rep = run_pipeline(db_path=Path(a.db), site_dir=Path(a.site), registry_path=Path(a.registry),
                       settings_path=Path(a.settings) if a.settings else None, orgs_path=Path(a.organizations) if a.organizations else None,
                       fetch=not a.no_fetch)
    text = json.dumps(rep, indent=1, default=str)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
            rows = "\n".join(f"| {s['source_id']} | {s['tier']} | {s['status']} | {s['reason'] or ''} | {s['items_seen']} | {s['new']} |" for s in rep["sources"])
            fh.write(f"## Daily scan {rep['run_id']}\n\n| source | tier | status | reason | items | new |\n|---|---|---|---|---|---|\n{rows}\n\n"
                     f"New articles: {rep['new_articles']} · clusters: {rep['clusters']} · digest: {rep['digest_bytes']} bytes\n")


if __name__ == "__main__":
    main()
