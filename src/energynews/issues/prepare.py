"""Prepare the daily newsletter run inside GitHub Actions (FR-14 via Claude Code GitHub Action).

python -m energynews.issues.prepare --site site --issues issues --template tasks/newsletter-action-prompt.md --out /tmp/prompt.md
Prints one line KEY=VALUE pairs for $GITHUB_OUTPUT: status (READY | ALREADY_PUBLISHED | SKIPPED_STALE | NO_DIGEST) and today.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
from zoneinfo import ZoneInfo


def prepare(site: Path, issues: Path, template: Path, out: Path, now: datetime | None = None, tz: str = "America/Chicago",
            stale_hours: int = 30) -> dict:
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo(tz))
    today = local.date().isoformat()
    res = {"today": today}
    latest = site / "snapshots" / "latest.json"
    if (issues / f"{today}.md").exists():
        return res | {"status": "ALREADY_PUBLISHED"}
    if not latest.exists():
        return res | {"status": "NO_DIGEST"}
    ref = json.loads(latest.read_text())
    as_of = datetime.fromisoformat(ref["data_as_of"])
    if (now - as_of).total_seconds() > stale_hours * 3600:
        idx_p = issues / "index.json"
        idx = json.loads(idx_p.read_text()) if idx_p.exists() else {"entries": []}
        if not any(e.get("date") == today for e in idx["entries"]):
            idx["entries"].append({"date": today, "status": "SKIPPED_STALE", "feed_sha256": ref["feed_sha256"], "reason": f"data_as_of {ref['data_as_of']}"})
            issues.mkdir(parents=True, exist_ok=True)
            idx_p.write_text(json.dumps(idx, indent=1) + "\n")
        return res | {"status": "SKIPPED_STALE"}
    text = template.read_text()
    body = text[4:].split("\n---\n", 1)[1] if text.startswith("---\n") else text
    fills = {"{{TODAY}}": today, "{{TODAY_LONG}}": f"{local:%A}, {local:%B} {local.day}, {local.year}", "{{FEED_SHA}}": ref["feed_sha256"],
             "{{DATA_AS_OF}}": ref["data_as_of"], "{{DIGEST_PATH}}": "site/" + ref["digest_path"], "{{JSON_PATH}}": "site/" + ref["path"]}
    for k, v in fills.items():
        body = body.replace(k, v)
    out.write_text(body)
    return res | {"status": "READY", "feed_sha256": ref["feed_sha256"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="site")
    ap.add_argument("--issues", default="issues")
    ap.add_argument("--template", default="tasks/newsletter-action-prompt.md")
    ap.add_argument("--out", default="/tmp/newsletter-prompt.md")
    a = ap.parse_args(argv)
    res = prepare(Path(a.site), Path(a.issues), Path(a.template), Path(a.out))
    for k, v in res.items():
        print(f"{k}={v}")


if __name__ == "__main__":
    main()
