"""ArticleStore + FlagRegistry persistence (SQLite, NFR-6)."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal
from pathlib import Path
import json
import sqlite3
from ..models import Article, Commodity, ExtractedFigure, Flag
from ..fetch.fetcher import SourceHealth

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_health(source_id TEXT PRIMARY KEY, etag TEXT, last_modified TEXT,
  consecutive_failures INTEGER NOT NULL DEFAULT 0, last_status TEXT, reason TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS articles(article_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, canonical_url TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL, published_at TEXT, excerpt TEXT NOT NULL CHECK(length(excerpt) <= 300), content_hash TEXT NOT NULL,
  commodities TEXT NOT NULL DEFAULT '[]', topic TEXT, status TEXT NOT NULL, fetched_at TEXT NOT NULL,
  organizations TEXT NOT NULL DEFAULT '[]');
CREATE INDEX IF NOT EXISTS ix_articles_pub ON articles(published_at);
CREATE TABLE IF NOT EXISTS figures(article_id TEXT NOT NULL, span TEXT NOT NULL, context TEXT NOT NULL, unit TEXT NOT NULL,
  keyword TEXT NOT NULL, PRIMARY KEY(article_id, span, context));
CREATE TABLE IF NOT EXISTS prices(benchmark TEXT NOT NULL, date TEXT NOT NULL, settle TEXT NOT NULL, source TEXT NOT NULL,
  PRIMARY KEY(benchmark, date));
CREATE TABLE IF NOT EXISTS flags(run_id TEXT NOT NULL, kind TEXT NOT NULL, subject_id TEXT NOT NULL, reason TEXT NOT NULL, raised_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, report TEXT NOT NULL);
"""


def _iso(d: datetime | None) -> str | None:
    return d.astimezone(timezone.utc).isoformat() if d else None


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


class ArticleStore:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.executescript(SCHEMA)
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(articles)")}
        if "organizations" not in cols:
            self.db.execute("ALTER TABLE articles ADD COLUMN organizations TEXT NOT NULL DEFAULT '[]'")

    # --- sources
    def health(self, source_id: str) -> SourceHealth:
        r = self.db.execute("SELECT etag,last_modified,consecutive_failures,last_status,reason FROM source_health WHERE source_id=?", (source_id,)).fetchone()
        return SourceHealth(source_id, *r) if r else SourceHealth(source_id)

    def save_health(self, h: SourceHealth, now: datetime):
        self.db.execute("INSERT OR REPLACE INTO source_health VALUES(?,?,?,?,?,?,?)",
                        (h.source_id, h.etag, h.last_modified, h.consecutive_failures, h.last_status, h.reason, _iso(now)))

    # --- articles
    def has_url(self, canonical_url: str) -> bool:
        return self.db.execute("SELECT 1 FROM articles WHERE canonical_url=?", (canonical_url,)).fetchone() is not None

    def insert_article(self, a: Article) -> bool:
        if len(a.excerpt) > 300:
            raise ValueError("excerpt exceeds 300 chars (NFR-4)")
        cur = self.db.execute("INSERT OR IGNORE INTO articles(article_id,source_id,canonical_url,title,published_at,excerpt,content_hash,commodities,topic,status,fetched_at,organizations) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (a.article_id, a.source_id, a.canonical_url, a.title, _iso(a.published_at), a.excerpt, a.content_hash,
             json.dumps(sorted(c.value for c in a.commodities)), a.topic, a.status, _iso(a.fetched_at), json.dumps(a.organizations)))
        if cur.rowcount:
            for f in a.figures:
                self.db.execute("INSERT OR IGNORE INTO figures VALUES(?,?,?,?,?)", (a.article_id, f.span, f.context, f.unit, f.keyword))
        return bool(cur.rowcount)

    def articles_since(self, since: datetime) -> list[Article]:
        rows = self.db.execute("SELECT article_id,source_id,canonical_url,title,published_at,excerpt,content_hash,commodities,topic,status,fetched_at,organizations "
                               "FROM articles WHERE published_at >= ? ORDER BY published_at, article_id", (_iso(since),)).fetchall()
        out = []
        for r in rows:
            a = Article(r[0], r[1], r[2], r[3], _dt(r[4]), r[5], r[6], frozenset(Commodity(c) for c in json.loads(r[7])), r[8], r[9], _dt(r[10]))
            a.organizations = json.loads(r[11])
            a.figures = [ExtractedFigure(r[0], *f) for f in self.db.execute("SELECT span,context,unit,keyword FROM figures WHERE article_id=? ORDER BY rowid", (r[0],))]
            out.append(a)
        return out

    def prune(self, now: datetime, retention_days: int):
        cutoff = _iso(now - timedelta(days=retention_days))
        self.db.execute("DELETE FROM figures WHERE article_id IN (SELECT article_id FROM articles WHERE fetched_at < ?)", (cutoff,))
        self.db.execute("DELETE FROM articles WHERE fetched_at < ?", (cutoff,))
        self.db.execute("DELETE FROM flags WHERE raised_at < ?", (cutoff,))

    # --- prices
    def upsert_prices(self, benchmark: str, points: list[tuple[date, Decimal]], source: str):
        self.db.executemany("INSERT OR REPLACE INTO prices VALUES(?,?,?,?)", [(benchmark, d.isoformat(), str(p), source) for d, p in points])

    def prices(self, benchmark: str) -> dict[date, Decimal]:
        return {date.fromisoformat(d): Decimal(p) for d, p in self.db.execute("SELECT date,settle FROM prices WHERE benchmark=? ORDER BY date", (benchmark,))}

    # --- flags / cache / runs
    def add_flags(self, run_id: str, flags: list[Flag], now: datetime):
        self.db.executemany("INSERT INTO flags VALUES(?,?,?,?,?)", [(run_id, f.kind, f.subject_id, f.reason, _iso(now)) for f in flags])

    def save_run(self, run_id: str, report: dict):
        self.db.execute("INSERT OR REPLACE INTO runs VALUES(?,?)", (run_id, json.dumps(report, default=str)))

    def commit(self):
        self.db.commit()

    def vacuum(self):
        self.db.commit()
        self.db.execute("VACUUM")

    def close(self):
        self.db.commit()
        self.db.close()
