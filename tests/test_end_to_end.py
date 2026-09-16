"""Offline end-to-end v2: two daily scans -> digest -> simulated scheduled task (ledger + newsletter + analysis) -> gate."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import httpx
import pytest
from energynews.issues.gate import run_gate
from energynews.issues.scope import check_issue_scope
from energynews.issues.validate import validate_issue
from energynews.run import run_pipeline

NOW = datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc)      # Wed 10:00 CT
EARLIER = NOW - timedelta(days=8)

REGISTRY = """
sources:
  - {id: eia, name: EIA Today in Energy, url: "https://www.eia.gov/rss/todayinenergy.xml", tier: 1, source_type: OFFICIAL, commodities: [CRUDE_OIL, NATURAL_GAS, REFINED_PRODUCTS], access_method: RSS, tos_status: ALLOWED}
  - {id: guardian, name: The Guardian — Energy, url: "https://www.theguardian.com/environment/energy/rss", tier: 1, source_type: PRESS, commodities: [CRUDE_OIL, NATURAL_GAS, REFINED_PRODUCTS, CARBON_CREDITS], access_method: RSS, tos_status: HEADLINE_ONLY}
  - {id: icap, name: ICAP News, url: "https://icapcarbonaction.com/en/news", tier: 1, source_type: OFFICIAL, commodities: [CARBON_CREDITS], access_method: HTML_LIST, link_pattern: "icapcarbonaction\\\\.com/en/news/[a-z0-9-]+$", tos_status: HEADLINE_ONLY}
  - {id: lngprime, name: LNG Prime, url: "https://lngprime.com/feed/", tier: 2, source_type: TRADE, commodities: [NATURAL_GAS], access_method: RSS, tos_status: HEADLINE_ONLY}
  - {id: carbonherald, name: Carbon Herald, url: "https://carbonherald.com/feed/", tier: 2, source_type: TRADE, commodities: [CARBON_CREDITS], access_method: RSS, tos_status: HEADLINE_ONLY}
  - {id: prn, name: PR Newswire — Energy, url: "https://www.prnewswire.com/rss/energy-latest-news/energy-latest-news-list.rss", tier: 2, source_type: NEWSROOM, commodities: [CRUDE_OIL, NATURAL_GAS, REFINED_PRODUCTS, CARBON_CREDITS], access_method: RSS, tos_status: HEADLINE_ONLY}
  - {id: broken, name: Broken, url: "https://broken.example/rss", tier: 2, source_type: TRADE, commodities: [CRUDE_OIL], access_method: RSS, tos_status: HEADLINE_ONLY}
  - {id: cdr, name: CDR.fyi, url: "https://www.cdr.fyi/", tier: 1, source_type: TRADE, commodities: [CARBON_CREDITS], tos_status: REFERENCE_ONLY}
"""


def fmt(dt):
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def rss(items):
    body = "".join(f"<item><title>{t}</title><link>{l}</link><description>{d}</description><pubDate>{fmt(p)}</pubDate></item>" for t, l, d, p in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{body}</channel></rss>'


FEEDS = {
    "www.eia.gov": [("U.S. crude oil inventories fell 4.1 million barrels last week", "https://www.eia.gov/todayinenergy/detail.php?id=1",
                     "Commercial crude oil inventories fell 4.1 million barrels in the week ending September 11.", NOW - timedelta(hours=20))],
    "www.theguardian.com": [
        ("QatarEnergy signs 15-year LNG supply deal with Indian buyer", "https://www.theguardian.com/business/qatar-lng-india", "QatarEnergy agreed a long-term LNG supply deal.", EARLIER - timedelta(hours=2)),
        ("Microsoft signs record carbon removal purchase with Climeworks", "https://www.theguardian.com/environment/microsoft-climeworks", "Microsoft agreed to buy durable carbon removal credits from Climeworks.", NOW - timedelta(days=2)),
    ],
    "lngprime.com": [("Venture Global signs 20-year LNG supply deal with Japanese buyer", "https://lngprime.com/venture-global-japan/", "Venture Global will supply LNG under a long-term deal.", NOW - timedelta(days=2, hours=4))],
    "www.prnewswire.com": [("Cheniere agrees long-term LNG sale to Asian utility", "https://www.prnewswire.com/news/cheniere-asia-lng", "Cheniere Energy signed a long-term LNG sale and purchase agreement.", NOW - timedelta(days=1, hours=3))],
    "carbonherald.com": [("Stripe and Shopify expand durable carbon removal purchases", "https://carbonherald.com/stripe-shopify-cdr/", "Stripe and Shopify announced new carbon removal purchases.", NOW - timedelta(days=3))],
}
ICAP_HTML = f"""<html><body><ul>
<li><a href="/en/news/eu-ets-auction-changes">European Commission proposes changes to EU ETS auction calendar</a><span>{(NOW - timedelta(days=1)).strftime('%b %d, %Y')}</span></li>
</ul></body></html>"""


def make_handler(seen_hosts):
    def handler(req: httpx.Request):
        seen_hosts.add(req.url.host)
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.host == "broken.example":
            return httpx.Response(500)
        if req.url.host == "icapcarbonaction.com":
            return httpx.Response(200, text=ICAP_HTML)
        if req.url.host in FEEDS and (req.url.path.endswith((".xml", ".rss", "/rss", "/feed/"))):
            return httpx.Response(200, text=rss(FEEDS[req.url.host]))
        if req.url.host == "www.eia.gov":
            return httpx.Response(200, text="<html><body><article><p>Commercial crude oil inventories fell 4.1 million barrels in the week ending September 11. U.S. crude oil production held at 13.4 million barrels per day.</p></article></body></html>")
        return httpx.Response(404)
    return handler


@pytest.fixture
def world(tmp_path):
    reg = tmp_path / "sources.yaml"; reg.write_text(REGISTRY)
    site, db, issues = tmp_path / "site", tmp_path / "db.sqlite", tmp_path / "issues"
    issues.mkdir()
    hosts = set()
    http = httpx.Client(transport=httpx.MockTransport(make_handler(hosts)))
    run = lambda now: run_pipeline(db_path=db, site_dir=site, registry_path=reg, http=http, now=now)
    return {"site": site, "issues": issues, "run": run, "hosts": hosts, "tmp": tmp_path}


def latest(site):
    ref = json.loads((site / "snapshots/latest.json").read_text())
    return ref, json.loads((site / ref["path"]).read_text()), (site / ref["digest_path"]).read_text()


def url_of(payload, needle):
    return next(s["url"] for i in payload["feed"] for s in i["sources"] if needle in s["title"])


def write_ledger(issues, trends):
    (issues / "trends.json").write_text(json.dumps({"trends": trends}, indent=1))


def newsletter(ref, payload, hot, day="2026-09-16", extra="", opened=None):
    item = next(i for i in payload["feed"] if "inventories" in i["title"])
    topics = "\n\n".join(f"### {t['name']} — {t['trajectory']} · {', '.join(t['companies'])} (trend: {t['trend_id']})\n\n{t['thesis']} [story]({t['timeline'][0]['story_url']})"
                         for n, t in enumerate(hot, 1)) or "No confirmed trends yet."
    opened = opened if opened is not None else [item["sources"][0]["url"]]
    return f"""---
date: {day}
feed_sha256: {ref['feed_sha256']}
data_as_of: {ref['data_as_of']}
prompt_version: newsletter-v2
articles_opened: {json.dumps(opened)}
---

# Energy News Daily — Wednesday, September 16, 2026

_Private preview · unverified, informational only · not investment advice_

## Hottest topics

{topics}

## Crude Oil

- **{item['title']}** — {item['summary']} [{item['sources'][0]['outlet']}]({item['sources'][0]['url']})
{extra}

## Natural Gas

No qualifying news in the last 24 hours.

## Refined Products

No qualifying news in the last 24 hours.

## Carbon Credits

No qualifying news in the last 24 hours.

## Sources

- [{item['sources'][0]['outlet']}]({item['sources'][0]['url']})

## Disclaimer

Private preview for a small readership. Generated automatically from public news sources. Unverified, informational only. Not investment advice.
"""


def test_end_to_end_v2(world):
    site, issues = world["site"], world["issues"]
    # ---- day 1 (8 days earlier): QatarEnergy LNG story; task starts the ledger
    rep1 = world["run"](EARLIER)
    assert rep1["published"]
    ref1, p1, md1 = latest(site)
    qatar = url_of(p1, "QatarEnergy")
    write_ledger(issues, [{"trend_id": "lng-asia-offtake", "name": "Long-term LNG supply deals with Asian buyers",
                           "thesis": "LNG sellers are locking in long-term demand from Asian buyers.", "commodities": ["NATURAL_GAS"], "first_seen": "2026-09-08",
                           "mentions": [{"date": "2026-09-08", "company": "QatarEnergy", "story_url": qatar, "action": "Signed 15-year LNG supply deal with Indian buyer"}]}])
    g1 = run_gate(issues, site, now=EARLIER + timedelta(hours=3))
    assert g1["ledger"]["status"] == "ACCEPTED"

    # ---- day 2 (today)
    rep = world["run"](NOW)
    assert rep["published"] and not rep["prices_enabled"]
    by = {s["source_id"]: s for s in rep["sources"]}
    assert by["broken"]["status"] == "FAILED" and by["icap"]["status"] == "OK"                       # AC-2.2, AC-2.5
    assert any(s["source_id"] == "cdr" and s["tos_status"] == "REFERENCE_ONLY" for s in rep["sources_skipped"])
    assert "www.cdr.fyi" not in world["hosts"] and "api.eia.gov" not in world["hosts"]              # AC-18.1, AC-N9.1
    ref, payload, md = latest(site)
    assert len(md.encode()) <= 60000 and "## Candidate trend groups" in md and "lng-asia-offtake" in md   # FR-16
    titles = [i["title"] for i in payload["feed"]]
    assert any("EU ETS auction" in t for t in titles)                                                    # HTML_LIST story made it
    assert not any("QatarEnergy" in t for t in titles)                                                   # outside 7-day window
    carbon = [i for i in payload["feed"] if "CARBON_CREDITS" in i["commodities"]]
    assert carbon and payload["reference_links"]["CARBON_CREDITS"][0]["url"] == "https://www.cdr.fyi/"
    ms = next(i for i in payload["feed"] if "Microsoft" in i["title"])
    assert {o["name"] for o in ms["organizations"]} >= {"Microsoft", "Climeworks"}
    assert (site / "robots.txt").read_text().strip().endswith("Disallow: /")
    assert 'content="noindex, nofollow"' in (site / "index.html").read_text()                           # AC-20.2
    for i in payload["feed"]:
        assert "price_effects" not in i                                                                  # AC-8.1

    # ---- scheduled task: append mentions, create a carbon removal trend
    ledger = json.loads((issues / "trends.json").read_text())
    ledger["trends"][0]["mentions"] += [
        {"date": "2026-09-14", "company": "Venture Global", "story_url": url_of(payload, "Venture Global"), "action": "Signed 20-year LNG supply deal with Japanese buyer"},
        {"date": "2026-09-15", "company": "Cheniere", "story_url": url_of(payload, "Cheniere"), "action": "Agreed long-term LNG sale to Asian utility"},
    ]
    ledger["trends"].append({"trend_id": "corporate-cdr-purchases", "name": "Corporate purchases of durable carbon removal",
                             "thesis": "Large companies are signing multi-year durable carbon removal purchases.", "commodities": ["CARBON_CREDITS"], "first_seen": "2026-09-13",
                             "mentions": [{"date": "2026-09-14", "company": "Microsoft", "story_url": url_of(payload, "Microsoft"), "action": "Signed record removal purchase with Climeworks"},
                                          {"date": "2026-09-13", "company": "Shopify", "story_url": url_of(payload, "Stripe"), "action": "Expanded durable carbon removal purchases"},
                                          {"date": "2026-09-13", "company": "Aramco", "story_url": url_of(payload, "Stripe"), "action": "Not actually in this story"}]})
    write_ledger(issues, ledger["trends"])
    g = run_gate(issues, site, now=NOW + timedelta(hours=1))
    assert g["ledger"]["status"] == "ACCEPTED", g["ledger"]
    views = {v["trend_id"]: v for v in json.loads((site / "trends/trends.json").read_text())["trends"]}
    lng, cdr = views["lng-asia-offtake"], views["corporate-cdr-purchases"]
    assert (lng["status"], lng["trajectory"], lng["companies_current"], lng["companies_previous"]) == ("CONFIRMED", "RISING", 2, 1)
    assert (cdr["status"], cdr["trajectory"]) == ("CONFIRMED", "NEW")
    assert any(m["company"] == "Saudi Aramco" and not m["verified"] and m["reason"] == "UNVERIFIED_COMPANY" for m in cdr["timeline"])                 # AC-19.4

    # ---- newsletter + analysis
    hot = [views["lng-asia-offtake"], views["corporate-cdr-purchases"]]
    (issues / "2026-09-16.md").write_text(newsletter(ref, payload, hot, extra="- Stocks may have fallen 9.9 million barrels elsewhere."))
    (issues / "analysis").mkdir()
    (issues / "analysis" / "2026-09-16.md").write_text(analysis(ref, payload, lng))
    g2 = run_gate(issues, site, now=NOW + timedelta(hours=1))
    [iss], [ana] = g2["issues"], g2["analyses"]
    assert iss["status"] == "PUBLISHED_WITH_WARNINGS" and iss["warnings"][0]["detail"] == "9.9", iss      # AC-15.2
    assert ana["status"] == "PUBLISHED", json.dumps(ana["reasons"])
    assert "(trend:" not in (site / "issues/2026-09-16.html").read_text()
    sections = json.loads((site / "analysis/2026-09-16.json").read_text())["sections"]
    assert {"overall", "CARBON_CREDITS", "trends", "watch"} <= set(sections)
    assert run_gate(issues, site, now=NOW + timedelta(hours=2))["issues"] == []                           # AC-14.2

    # ---- rejections
    cases = [
        ("UNSOURCED_URL", dict(extra="- [bad](https://evil.example/a)")),
        ("ADVISORY_LANGUAGE", dict(extra="- Traders should buy crude here.")),
        ("READING_BUDGET_EXCEEDED", dict(opened=[url_of(payload, "inventories")] * 16)),
    ]
    for code, kw in cases:
        d = world["tmp"] / f"rej-{code}"; d.mkdir()
        (d / "2026-09-16.md").write_text(newsletter(ref, payload, hot, **kw))
        v = validate_issue(d / "2026-09-16.md", site / "snapshots", list(views.values()), "issue")
        assert v.status == "REJECTED" and any(r["code"] == code for r in v.reasons), (code, v.reasons)
    emerging = dict(views["lng-asia-offtake"], status="EMERGING")
    d = world["tmp"] / "rej-trend"; d.mkdir()
    (d / "2026-09-16.md").write_text(newsletter(ref, payload, [views["lng-asia-offtake"]]))
    v = validate_issue(d / "2026-09-16.md", site / "snapshots", [emerging], "issue")
    assert any(r["code"] == "TREND_NOT_CONFIRMED" for r in v.reasons)                                    # AC-15.4

    # ---- append-only enforcement at the gate
    broken = json.loads((issues / "trends.json").read_text())
    broken["trends"][0]["mentions"] = broken["trends"][0]["mentions"][1:]
    write_ledger(issues, broken["trends"])
    assert run_gate(issues, site, now=NOW + timedelta(hours=3))["ledger"]["reasons"][0]["code"] == "LEDGER_NOT_APPEND_ONLY"
    assert len(json.loads((site / "trends/ledger.json").read_text())["trends"][0]["mentions"]) == 3      # previous ledger stays live


def analysis(ref, payload, lng):
    return f"""---
date: 2026-09-16
feed_sha256: {ref['feed_sha256']}
data_as_of: {ref['data_as_of']}
prompt_version: analysis-v2
articles_opened: []
---

# What this means for energy traders — Wednesday, September 16, 2026

## The big picture

LNG sellers keep locking in Asian demand, and corporate carbon removal buying is broadening.

## Crude Oil

An inventory draw was the main official data point this week; draws are generally read as a sign of tighter near-term supply.

## Natural Gas

More sellers are signing long-term Asian deals ([story]({lng['timeline'][0]['story_url']})).

## Refined Products

No qualifying news in the last 7 days.

## Carbon Credits

Technology companies continue to anchor durable removal demand.

## Trend trajectories

- {lng['name']} — {lng['trajectory']}: more companies moved this week than last.

## What to watch

- {payload['calendar'][0]['name']}, {payload['calendar'][0]['at_local']}

## Data notes

- Some trend evidence comes from company press releases.

## Disclaimer

Private preview for a small readership. Generated automatically from public news sources. Unverified, informational only. Not investment advice.
"""


def test_ac_n8_scope_guard():
    assert check_issue_scope(["issues/2026-09-16.md", "issues/trends.json", "issues/analysis/2026-09-16.md"], "issue: 2026-09-16")
    assert not check_issue_scope(["config/sources.yaml"], "issue: 2026-09-16")


def test_ac_20_1_cname(tmp_path):
    from energynews.publish.render import render_site
    render_site({"site": {"title": "T", "banner": "B"}, "x": 1}, tmp_path, "news.example.com")
    assert (tmp_path / "CNAME").read_text().strip() == "news.example.com"
    render_site({"site": {"title": "T", "banner": "B"}, "x": 1}, tmp_path, "")
    assert not (tmp_path / "CNAME").exists()


def test_ac_12_1_weekly_archive_immutable(tmp_path):
    from energynews.publish.render import archive_issue
    (tmp_path / "feed.json").write_text('{"v": 1}')
    mon = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)
    assert archive_issue(tmp_path, mon, "America/Chicago", 0, 7) == "2026-W38"
    (tmp_path / "feed.json").write_text('{"v": 2}')
    assert archive_issue(tmp_path, mon + timedelta(hours=3), "America/Chicago", 0, 7) is None
    assert json.loads((tmp_path / "archive/2026-W38/feed.json").read_text()) == {"v": 1}


def test_topic_headings_render_without_numbers():
    from energynews.issues.gate import render_md
    out = render_md("### 1. LNG deals — RISING (trend: lng-asia)\n\ntext\n\n### 2) Carbon removal — NEW")
    assert "1." not in out and "2)" not in out and "(trend:" not in out and "<h3>LNG deals — RISING</h3>" in out


def test_prepare_newsletter_prompt(tmp_path):
    from energynews.issues.prepare import prepare
    from energynews.config import ROOT
    site, issues = tmp_path / "site", tmp_path / "issues"
    (site / "snapshots").mkdir(parents=True); issues.mkdir()
    ref = {"feed_sha256": "a" * 64, "data_as_of": "2026-09-16T10:10:00+00:00", "path": "snapshots/feed-x.json", "digest_path": "snapshots/digest-x.md"}
    (site / "snapshots/latest.json").write_text(json.dumps(ref))
    out = tmp_path / "prompt.md"
    now = datetime(2026, 9, 16, 12, 30, tzinfo=timezone.utc)
    r = prepare(site, issues, ROOT / "tasks/newsletter-action-prompt.md", out, now)
    assert r["status"] == "READY" and r["today"] == "2026-09-16"
    text = out.read_text()
    assert "{{" not in text and "issues/2026-09-16.md" in text and "site/snapshots/digest-x.md" in text and "Wednesday, September 16, 2026" in text
    assert not text.startswith("---\nname:")
    (issues / "2026-09-16.md").write_text("x")
    assert prepare(site, issues, ROOT / "tasks/newsletter-action-prompt.md", out, now)["status"] == "ALREADY_PUBLISHED"
    (issues / "2026-09-16.md").unlink()
    stale = prepare(site, issues, ROOT / "tasks/newsletter-action-prompt.md", out, now + timedelta(hours=40))
    assert stale["status"] == "SKIPPED_STALE" and json.loads((issues / "index.json").read_text())["entries"][0]["status"] == "SKIPPED_STALE"
