"""SiteRenderer + SnapshotStore + IssueArchiver + publish helpers (FR-9..FR-12, FR-14/15 snapshots, NFR-6/7)."""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import json
import shutil
from jinja2 import Environment, FileSystemLoader, select_autoescape

HERE = Path(__file__).parent


def canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=1).encode()


def render_site(payload: dict, out_dir: Path, custom_domain: str = "") -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    body = canonical_json(payload)
    sha = hashlib.sha256(body).hexdigest()
    env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=select_autoescape())
    (out_dir / "index.html").write_text(env.get_template("index.html").render(version=sha[:10], site=payload["site"]))
    (out_dir / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    cname = out_dir / "CNAME"
    if custom_domain:
        cname.write_text(custom_domain.strip() + "\n")
    elif cname.exists():
        cname.unlink()
    (out_dir / "assets").mkdir(exist_ok=True)
    for f in (HERE / "assets").iterdir():
        shutil.copy2(f, out_dir / "assets" / f.name)
    (out_dir / "feed.json").write_bytes(body)
    (out_dir / ".nojekyll").write_text("")
    return sha


def write_snapshot(out_dir: Path, sha: str, data_as_of: str, markdown: str) -> dict:
    snap = out_dir / "snapshots"
    snap.mkdir(exist_ok=True)
    shutil.copy2(out_dir / "feed.json", snap / f"feed-{sha}.json")
    (snap / f"digest-{sha}.md").write_text(markdown.replace("schema digest.v2", f"feed_sha256 {sha} · schema digest.v2", 1))
    ref = {"feed_sha256": sha, "data_as_of": data_as_of, "path": f"snapshots/feed-{sha}.json", "digest_path": f"snapshots/digest-{sha}.md"}
    (snap / "latest.json").write_text(json.dumps(ref, indent=1))
    return ref


def prune_snapshots(out_dir: Path, now: datetime, retention_days: int, keep: set[str]):
    snap = out_dir / "snapshots"
    if not snap.exists():
        return
    cutoff = now - timedelta(days=retention_days)
    for f in snap.glob("feed-*.json"):
        sha = f.stem.removeprefix("feed-")
        if sha in keep:
            continue
        try:
            as_of = datetime.fromisoformat(json.loads(f.read_text())["data_as_of"])
        except Exception:
            continue
        if as_of < cutoff:
            f.unlink()
            md = snap / f"digest-{sha}.md"
            if md.exists():
                md.unlink()


def archive_issue(out_dir: Path, now: datetime, tz: str, weekday: int, hour: int) -> str | None:
    """Freeze the weekly archive once per ISO week, at/after the configured local time (FR-12)."""
    local = now.astimezone(ZoneInfo(tz))
    monday = local.date() - timedelta(days=local.weekday())
    freeze_at = datetime.combine(monday + timedelta(days=weekday), datetime.min.time(), ZoneInfo(tz)).replace(hour=hour)
    if not (freeze_at <= local < freeze_at + timedelta(days=1)):
        return None  # only the first runs after the freeze time may archive, so a mid-week first deploy doesn't freeze a partial week
    y, w, _ = local.isocalendar()
    week = f"{y}-W{w:02d}"
    target = out_dir / "archive" / week
    if (target / "feed.json").exists():
        return None  # immutable
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out_dir / "feed.json", target / "feed.json")
    idx_p = out_dir / "archive" / "index.json"
    idx = json.loads(idx_p.read_text()) if idx_p.exists() else {"weeks": []}
    idx["weeks"] = sorted(set(idx["weeks"]) | {week}, reverse=True)
    idx_p.write_text(json.dumps(idx, indent=1))
    return week


def oversized_files(root: Path, max_bytes: int) -> list[str]:
    return [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and ".git" not in p.parts and p.stat().st_size > max_bytes]
