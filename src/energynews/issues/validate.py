"""IssueValidator (FR-15, FR-17, ADR-017): reject/warn rules for newsletters and analyses.
python -m energynews.issues.validate issues/2026-09-16.md --site site --kind issue
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
import hashlib
import json
import re
import sys
import frontmatter
import yaml
from ..fetch.urls import canonicalize_url
from .language import ADVISORY, NUMBER, norm_number
from .tokens import URL, allowed_tokens

RULES = yaml.safe_load((Path(__file__).parent / "rules.yaml").read_text())
TREND_TAG = re.compile(r"[ \t]*\(trend:\s*([a-z0-9-]+)\)")
TRAJECTORIES = ("NEW", "RISING", "STEADY", "FADING", "DORMANT")


@dataclass
class IssueValidation:
    status: str  # PUBLISHED | PUBLISHED_WITH_WARNINGS | REJECTED
    reasons: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


def _date_numbers(d: date) -> set[str]:
    return {str(d.year), str(d.month), f"{d.month:02d}", str(d.day), f"{d.day:02d}"}


def sections(body: str) -> dict[str, str]:
    out, cur, buf = {}, None, []
    for line in body.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if cur is not None:
                out[cur] = "\n".join(buf)
            cur, buf = m.group(1).strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf)
    return out


def validate_issue(path: Path, snapshots_dir: Path, trend_views: list[dict] | None, kind: str = "issue", reading_budget: int = 15) -> IssueValidation:
    rej, warn = [], []
    try:
        post = frontmatter.load(path)
    except Exception as ex:  # noqa: BLE001
        return IssueValidation("REJECTED", [{"code": "BAD_FRONTMATTER", "detail": str(ex)}])
    meta, body = dict(post.metadata), post.content
    for k in ("date", "feed_sha256", "data_as_of", "prompt_version"):
        if not meta.get(k):
            rej.append({"code": "BAD_FRONTMATTER", "detail": f"missing {k}"})
    try:
        d = meta["date"] if isinstance(meta.get("date"), date) else date.fromisoformat(str(meta.get("date")))
    except (ValueError, TypeError):
        return IssueValidation("REJECTED", rej + [{"code": "BAD_FRONTMATTER", "detail": "date is not YYYY-MM-DD"}], meta=meta)
    if path.stem != d.isoformat():
        rej.append({"code": "BAD_FRONTMATTER", "detail": f"file name {path.name} does not match date {d}"})
    sha = str(meta.get("feed_sha256", ""))
    snap = snapshots_dir / f"feed-{sha}.json"
    if not re.fullmatch(r"[0-9a-f]{64}", sha) or not snap.exists():
        return IssueValidation("REJECTED", rej + [{"code": "UNKNOWN_SNAPSHOT", "detail": f"no retained snapshot {sha[:16]}"}], meta=meta)
    raw = snap.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        return IssueValidation("REJECTED", rej + [{"code": "UNKNOWN_SNAPSHOT", "detail": "snapshot hash mismatch"}], meta=meta)
    payload = json.loads(raw)
    tok = allowed_tokens(payload)
    canon_urls = {canonicalize_url(u) for u in tok.urls}

    opened = meta.get("articles_opened") or []
    if not isinstance(opened, list):
        rej.append({"code": "BAD_FRONTMATTER", "detail": "articles_opened must be a list"})
        opened = []
    if len(opened) > reading_budget:
        rej.append({"code": "READING_BUDGET_EXCEEDED", "detail": f"{len(opened)} articles opened, budget {reading_budget}"})
    for u in opened:
        if canonicalize_url(str(u)) not in canon_urls:
            rej.append({"code": "UNSOURCED_URL", "detail": f"articles_opened: {u}"})

    low = body.lower()
    for req in RULES["common"]["required_phrases"]:
        if req["pattern"] not in low:
            rej.append({"code": req["code"], "detail": f"missing phrase '{req['pattern']}'"})
    secs = sections(body)
    for sec in RULES[kind]["required_sections"]:
        if sec not in secs:
            rej.append({"code": "MISSING_SECTION", "detail": f"missing '## {sec}'"})

    for u in sorted({u.rstrip(".,") for u in URL.findall(body)}):
        if canonicalize_url(u) not in canon_urls:
            rej.append({"code": "UNSOURCED_URL", "detail": u})

    if kind == "issue" and "Hottest topics" in secs:
        views = {v["trend_id"]: v for v in (trend_views or [])}
        heads = [l for l in secs["Hottest topics"].splitlines() if l.startswith("### ")]
        if len(heads) > 5:
            rej.append({"code": "TOO_MANY_TOPICS", "detail": f"{len(heads)} hottest topics, max 5"})
        for h in heads:
            m = TREND_TAG.search(h)
            v = views.get(m.group(1)) if m else None
            if not m:
                rej.append({"code": "TREND_NOT_CONFIRMED", "detail": f"heading lacks (trend: id): {h[:80]}"})
            elif v is None or v["status"] != "CONFIRMED" or v["trajectory"] == "DORMANT":
                rej.append({"code": "TREND_NOT_CONFIRMED", "detail": f"{m.group(1)} is {v['status'] if v else 'not in the ledger'}"})
            else:
                said = next((t for t in TRAJECTORIES if re.search(rf"\b{t}\b", h)), None)
                if said and said != v["trajectory"]:
                    warn.append({"code": "TRAJECTORY_MISMATCH", "detail": f"{v['trend_id']}: heading says {said}, computed {v['trajectory']}"})

    scrubbed = TREND_TAG.sub(" ", URL.sub(" ", body))
    allowed = set(tok.numbers) | set(RULES["common"]["always_allowed_numbers"]) | _date_numbers(d)
    for v in trend_views or []:
        allowed |= {str(v["companies_current"]), str(v["companies_previous"]), str(v["mentions_current"]), str(v["mentions_previous"]), v["hotness"].rstrip("0").rstrip(".")}
    try:
        allowed |= _date_numbers(datetime.fromisoformat(str(meta.get("data_as_of"))).date())
    except ValueError:
        pass
    for b in sorted({m.group(0) for m in NUMBER.finditer(scrubbed) if norm_number(m.group(0)) not in allowed}):
        warn.append({"code": "UNVERIFIED_NUMBER", "detail": b})

    adv = scrubbed
    for p in tok.phrases:
        adv = adv.replace(p, " ")
    for m in ADVISORY.finditer(adv):
        rej.append({"code": "ADVISORY_LANGUAGE", "detail": m.group(0)})

    status = "REJECTED" if rej else ("PUBLISHED_WITH_WARNINGS" if warn else "PUBLISHED")
    return IssueValidation(status, rej, warn, meta)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--site", default="site")
    ap.add_argument("--kind", choices=["issue", "analysis"], default="issue")
    a = ap.parse_args(argv)
    tv = Path(a.site) / "trends" / "trends.json"
    views = json.loads(tv.read_text())["trends"] if tv.exists() else []
    v = validate_issue(Path(a.path), Path(a.site) / "snapshots", views, a.kind)
    print(json.dumps({"status": v.status, "reasons": v.reasons, "warnings": v.warnings}, indent=1))
    sys.exit(1 if v.status == "REJECTED" else 0)


if __name__ == "__main__":
    main()
