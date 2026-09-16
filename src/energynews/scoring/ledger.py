"""Trend ledger validation (FR-19, ADR-015).

The scheduled task edits issues/trends.json. The validated, annotated copy is published at site/trends/ledger.json and is
the only ledger the TrendEngine reads. Mentions are append-only; each new mention must link a story that appears in a
retained digest snapshot; its company is verified against that story's digest text and organization tags.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import json
import re
from ..fetch.urls import canonicalize_url
from ..models import Commodity
from ..tag.organizations import OrganizationIndex, fold

TREND_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,59}$")
COMMODITIES = {c.value for c in Commodity}


@dataclass
class LedgerValidation:
    status: str  # ACCEPTED | REJECTED | UNCHANGED
    reasons: list[dict] = field(default_factory=list)
    ledger: dict | None = None  # annotated ledger to publish when ACCEPTED


def story_index(snapshots_dir: Path) -> dict[str, dict]:
    """url -> story facts from every retained digest snapshot (newest snapshot wins)."""
    idx: dict[str, dict] = {}
    files = sorted(Path(snapshots_dir).glob("feed-*.json"), key=lambda p: p.stat().st_mtime) if Path(snapshots_dir).exists() else []
    for f in files:
        try:
            payload = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        for item in payload.get("feed", []):
            for s in item.get("sources", []):
                idx[canonicalize_url(s["url"])] = {
                    "title": s.get("title", ""), "excerpt": s.get("excerpt", ""), "outlet": s.get("outlet", ""),
                    "tier": s.get("tier", 3), "published_at": s.get("published_at"), "organizations": s.get("organizations", []),
                    "source_type": s.get("source_type"),
                    "cluster_id": item.get("cluster_id"), "commodities": item.get("commodities", [])}
    return idx


def _mention_key(m: dict) -> tuple:
    return (str(m.get("date")), fold(str(m.get("company", ""))).strip(), canonicalize_url(str(m.get("story_url", ""))), str(m.get("action", "")).strip())


def _schema_errors(ledger) -> list[str]:
    errs = []
    if not isinstance(ledger, dict) or not isinstance(ledger.get("trends"), list):
        return ["ledger must be an object with a 'trends' list"]
    ids = Counter()
    for i, t in enumerate(ledger["trends"]):
        where = f"trends[{i}]"
        if not isinstance(t, dict):
            errs.append(f"{where} must be an object"); continue
        tid = t.get("trend_id", "")
        ids[tid] += 1
        if not TREND_ID.match(str(tid)):
            errs.append(f"{where}.trend_id must be a lowercase slug")
        for k, limit in (("name", 90), ("thesis", 240)):
            if not isinstance(t.get(k), str) or not t[k].strip() or len(t[k]) > limit:
                errs.append(f"{where}.{k} required, max {limit} chars")
        comms = t.get("commodities")
        if not isinstance(comms, list) or not comms or any(c not in COMMODITIES for c in comms):
            errs.append(f"{where}.commodities must be a non-empty subset of {sorted(COMMODITIES)}")
        try:
            date.fromisoformat(str(t.get("first_seen")))
        except ValueError:
            errs.append(f"{where}.first_seen must be YYYY-MM-DD")
        if not isinstance(t.get("mentions"), list):
            errs.append(f"{where}.mentions must be a list"); continue
        for j, m in enumerate(t["mentions"]):
            w = f"{where}.mentions[{j}]"
            if not isinstance(m, dict):
                errs.append(f"{w} must be an object"); continue
            try:
                date.fromisoformat(str(m.get("date")))
            except ValueError:
                errs.append(f"{w}.date must be YYYY-MM-DD")
            if not isinstance(m.get("company"), str) or not m["company"].strip() or len(m["company"]) > 80:
                errs.append(f"{w}.company required, max 80 chars")
            if not str(m.get("story_url", "")).startswith(("http://", "https://")):
                errs.append(f"{w}.story_url must be an http(s) URL")
            action = m.get("action")
            if not isinstance(action, str) or not action.strip() or len(action.split()) > 20:
                errs.append(f"{w}.action required, 20 words or fewer")
    errs += [f"duplicate trend_id '{k}'" for k, n in ids.items() if n > 1]
    return errs


def validate_ledger(new: dict, previous: dict | None, index: dict[str, dict], orgs: OrganizationIndex) -> LedgerValidation:
    errs = _schema_errors(new)
    if errs:
        return LedgerValidation("REJECTED", [{"code": "BAD_LEDGER", "detail": e} for e in errs[:30]])
    reasons = []
    prev_trends = {t["trend_id"]: t for t in (previous or {}).get("trends", [])}
    new_trends = {t["trend_id"]: t for t in new["trends"]}
    for tid, pt in prev_trends.items():
        if tid not in new_trends:
            reasons.append({"code": "LEDGER_NOT_APPEND_ONLY", "detail": f"trend '{tid}' was removed"})
            continue
        have = Counter(_mention_key(m) for m in new_trends[tid]["mentions"])
        need = Counter(_mention_key(m) for m in pt["mentions"])
        missing = need - have
        if missing:
            reasons.append({"code": "LEDGER_NOT_APPEND_ONLY", "detail": f"trend '{tid}': {sum(missing.values())} existing mention(s) removed or changed"})
    if reasons:
        return LedgerValidation("REJECTED", reasons)
    published = {"trends": []}
    added = 0
    for t in new["trends"]:
        prev_ann = Counter()
        prev_by_key: dict[tuple, list[dict]] = {}
        for m in prev_trends.get(t["trend_id"], {}).get("mentions", []):
            prev_by_key.setdefault(_mention_key(m), []).append(m)
        out_mentions = []
        for m in t["mentions"]:
            k = _mention_key(m)
            if prev_by_key.get(k):
                out_mentions.append(prev_by_key[k].pop(0))  # keep original annotation
                continue
            url = canonicalize_url(m["story_url"])
            story = index.get(url)
            if story is None:
                reasons.append({"code": "UNSOURCED_MENTION", "detail": f"{t['trend_id']}: {m['story_url']}"})
                continue
            added += 1
            text = f"{story['title']} {story['excerpt']}"
            named = orgs.mentioned_in(m["company"], text, story.get("organizations", []))
            org = orgs.lookup(m["company"])
            is_company = org is None or org.org_type == "COMPANY"
            ann = {**m, "story_url": url, "company_key": org.org_id if org else fold(m["company"]).strip(),
                   "company_name": org.name if org else m["company"].strip(), "verified": bool(named and is_company),
                   "story_title": story["title"], "outlet": story["outlet"], "tier": story["tier"], "story_published_at": story["published_at"],
                   "source_type": story.get("source_type")}
            if not named:
                ann["reason"] = "UNVERIFIED_COMPANY"
            elif not is_company:
                ann["reason"] = "NOT_A_COMPANY"
            out_mentions.append(ann)
        published["trends"].append({k: t[k] for k in ("trend_id", "name", "thesis", "commodities", "first_seen")} | {"mentions": out_mentions})
    if reasons:
        return LedgerValidation("REJECTED", reasons)
    return LedgerValidation("ACCEPTED" if added or previous is None or published != previous else "UNCHANGED", [], published)
