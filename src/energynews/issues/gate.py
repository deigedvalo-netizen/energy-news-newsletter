"""Issue gate (FR-15, FR-17, FR-19): validate the ledger first, recompute trends, then newsletters and analyses.
python -m energynews.issues.gate --issues issues --site site
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
import html
import json
import os
import re
import frontmatter
import markdown
from ..config import ROOT, load_settings
from ..scoring.ledger import story_index, validate_ledger
from ..scoring.trends import compute_trends
from ..tag.organizations import OrganizationIndex
from .validate import RULES, TREND_TAG, validate_issue

PUBLISHABLE = ("PUBLISHED", "PUBLISHED_WITH_WARNINGS")


HEADING_NUMBER = re.compile(r"^(#{3,4}\s+)\d+[.)]\s+", re.M)


def render_md(md_body: str) -> str:
    safe = html.escape(HEADING_NUMBER.sub(r"\1", TREND_TAG.sub("", md_body)), quote=False)
    return markdown.markdown(safe, extensions=["sane_lists"], output_format="html")


render_issue_html = render_md


def split_sections(md_body: str) -> dict[str, str]:
    keys = RULES["analysis"]["section_keys"]
    out, cur, buf = {}, None, []
    for line in md_body.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if cur:
                out[cur] = render_md("\n".join(buf).strip())
            cur, buf = keys.get(m.group(1).strip()), []
            continue
        if cur:
            buf.append(line)
    if cur:
        out[cur] = render_md("\n".join(buf).strip())
    return out


def gate_ledger(issues_dir: Path, site_dir: Path, orgs: OrganizationIndex) -> dict:
    src = issues_dir / "trends.json"
    out = site_dir / "trends"
    out.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        return {"status": "NO_LEDGER"}
    prev_p = out / "ledger.json"
    prev = json.loads(prev_p.read_text()) if prev_p.exists() else None
    try:
        new = json.loads(src.read_text())
    except ValueError as ex:
        res = {"status": "REJECTED", "reasons": [{"code": "BAD_LEDGER", "detail": str(ex)}]}
    else:
        v = validate_ledger(new, prev, story_index(site_dir / "snapshots"), orgs)
        res = {"status": v.status, "reasons": v.reasons}
        if v.status == "ACCEPTED":
            prev_p.write_text(json.dumps(v.ledger, indent=1, ensure_ascii=False))
    res["validated_at"] = datetime.now(timezone.utc).isoformat()
    (out / "ledger-status.json").write_text(json.dumps(res, indent=1))
    return res


def _gate_files(src_dir: Path, out_dir: Path, site_dir: Path, kind: str, views: list[dict], budget: int) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    man_p = out_dir / "manifest.json"
    manifest = json.loads(man_p.read_text()) if man_p.exists() else {"issues": []}
    known = {i["date"]: i for i in manifest["issues"]}
    results = []
    for p in sorted(src_dir.glob("*.md")) if src_dir.exists() else []:
        d = p.stem
        if d in known and known[d]["status"] in PUBLISHABLE:
            continue  # never overwrite a published file (AC-14.2)
        v = validate_issue(p, site_dir / "snapshots", views, kind, budget)
        entry = {"date": d, "kind": kind, "status": v.status, "feed_sha256": str(v.meta.get("feed_sha256", "")),
                 "data_as_of": str(v.meta.get("data_as_of", "")), "validated_at": datetime.now(timezone.utc).isoformat(),
                 "reasons": v.reasons, "warnings": v.warnings}
        if v.status in PUBLISHABLE:
            post = frontmatter.load(p)
            (out_dir / f"{d}.html").write_text(render_md(post.content))
            if kind == "analysis":
                title = next((l[2:].strip() for l in post.content.splitlines() if l.startswith("# ")), "What this means for energy traders")
                (out_dir / f"{d}.json").write_text(json.dumps({"date": d, "title": title, "data_as_of": entry["data_as_of"], "status": v.status,
                                                                "sections": split_sections(post.content)}, indent=1))
        known[d] = entry
        results.append(entry)
    if kind == "issue":
        idx = src_dir / "index.json"
        if idx.exists():
            for e in json.loads(idx.read_text()).get("entries", []):
                if e.get("status") == "SKIPPED_STALE" and e.get("date") not in known:
                    known[e["date"]] = {**e, "reasons": [{"code": "SKIPPED_STALE", "detail": e.get("reason", "")}]}
    manifest["issues"] = sorted(known.values(), key=lambda i: i["date"], reverse=True)
    man_p.write_text(json.dumps(manifest, indent=1))
    return results


def run_gate(issues_dir: Path, site_dir: Path, settings_path: Path | None = None, orgs_path: Path | None = None, now: datetime | None = None) -> dict:
    settings = load_settings(settings_path)
    orgs = OrganizationIndex.load(orgs_path or ROOT / "config" / "organizations.yaml")
    now = now or datetime.now(timezone.utc)
    ledger_res = gate_ledger(issues_dir, site_dir, orgs)
    lp = site_dir / "trends" / "ledger.json"
    t, w = settings["trends"], settings["weights"]
    views = compute_trends(json.loads(lp.read_text()) if lp.exists() else None, now, t["confirm_companies"], t["status_window_days"],
                           t["trajectory_window_days"], {int(k): v for k, v in w["tier_weights"].items()}, w["half_life_hours"])
    (site_dir / "trends" / "trends.json").write_text(json.dumps({"computed_at": now.isoformat(), "trends": views}, indent=1))
    budget = settings["author"]["reading_budget"]
    issues = _gate_files(issues_dir, site_dir / "issues", site_dir, "issue", views, budget)
    analyses = _gate_files(issues_dir / "analysis", site_dir / "analysis", site_dir, "analysis", views, budget)
    return {"ledger": ledger_res, "issues": issues, "analyses": analyses}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--issues", default="issues")
    ap.add_argument("--site", default="site")
    ap.add_argument("--settings", default=None)
    ap.add_argument("--organizations", default=None)
    a = ap.parse_args(argv)
    res = run_gate(Path(a.issues), Path(a.site), Path(a.settings) if a.settings else None, Path(a.organizations) if a.organizations else None)
    text = json.dumps(res, indent=1)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write(f"## Issue gate\n\n```json\n{text}\n```\n")
    if res["ledger"].get("status") == "REJECTED" or any(r["status"] == "REJECTED" for r in res["issues"] + res["analyses"]):
        print("::warning::ledger or an issue was REJECTED; see reasons above")


if __name__ == "__main__":
    main()
