"""News API adapters: GDELT, Guardian, NewsData (parsing, domain filtering, missing keys, key redaction)."""
from datetime import datetime, timezone
import httpx
from energynews.config import ROOT
from energynews.extract.extractor import extract_article, parse_published
from energynews.fetch.fetcher import Robots, SourceHealth, fetch_source
from energynews.models import Commodity, Source
from energynews.sources.registry import eligible_sources, load_registry
import energynews.fetch.apis as apis

NOW = datetime(2026, 9, 16, 12, tzinfo=timezone.utc)


def src(access, queries, domains=(), params=None, env=None):
    return Source("x", "X", "https://api.example", 1, frozenset(Commodity), access, "HEADLINE_ONLY", True, "PRESS",
                  options={"queries": list(queries), "domains": list(domains), "params": params or {}, "api_key_env": env})


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_gdelt_parses_filters_domains_and_paces(monkeypatch):
    calls, slept = [], []
    apis._last_gdelt[0] = 0.0

    def handler(req):
        calls.append(req.url.params["query"])
        return httpx.Response(200, json={"articles": [
            {"url": "https://www.reuters.com/markets/carbon/eu-ets-1", "title": "EU carbon price climbs", "seendate": "20260916T083000Z"},
            {"url": "https://spam.example/carbon", "title": "Buy carbon now", "seendate": "20260916T083000Z"},
            {"url": "/relative", "title": "Bad link", "seendate": "20260916T083000Z"},
        ]})
    s = src("API_GDELT", ['("carbon credits" OR cbam)'], domains=[f"d{i}.com" for i in range(9)] + ["reuters.com"])
    items, errors = apis.fetch_gdelt(s, client(handler), sleep=slept.append)
    assert len(calls) == 2  # 10 domains -> two OR groups of at most 8
    assert "(domain:d0.com OR" in calls[0] and calls[0].endswith("sourcelang:english")
    assert slept, "second GDELT request must wait"
    assert [i.url for i in items] == ["https://www.reuters.com/markets/carbon/eu-ets-1"]
    assert items[0].published_parsed == datetime(2026, 9, 16, 8, 30, tzinfo=timezone.utc)
    assert errors == []


def test_gdelt_plain_text_error_is_reported():
    apis._last_gdelt[0] = 0.0
    s = src("API_GDELT", ["cbam"])
    res = apis.fetch_api_source(s, client(lambda r: httpx.Response(200, text="Please limit requests to one every 5 seconds")), NOW, sleep=lambda x: None)
    assert res.status == "FAILED" and "limit requests" in res.reason


def test_guardian_items_and_missing_key_is_skipped(monkeypatch):
    s = src("API_GUARDIAN", ['"carbon market"'], env="GUARDIAN_API_KEY")
    monkeypatch.delenv("GUARDIAN_API_KEY", raising=False)
    assert fetch_source(s, SourceHealth("x"), client(lambda r: httpx.Response(500)), Robots(client(lambda r: httpx.Response(404)))).status == "SKIPPED"
    monkeypatch.setenv("GUARDIAN_API_KEY", "sekrit")
    seen = {}

    def handler(req):
        seen.update(req.url.params)
        return httpx.Response(200, json={"response": {"status": "ok", "results": [
            {"webUrl": "https://www.theguardian.com/environment/2026/sep/16/carbon", "webTitle": "Carbon market reform",
             "webPublicationDate": "2026-09-16T07:00:00Z", "fields": {"trailText": "<p>EU agrees changes</p>"}}]}})
    res = apis.fetch_api_source(s, client(handler), NOW)
    assert res.status == "OK" and seen["api-key"] == "sekrit" and seen["from-date"] == "2026-09-14"
    it = res.items[0]
    assert parse_published(it) == datetime(2026, 9, 16, 7, tzinfo=timezone.utc)
    a, _ = extract_article(it, s, None, NOW)
    assert a.status == "OK" and a.excerpt == "EU agrees changes"


def test_newsdata_paginates_and_redacts_key_on_errors(monkeypatch):
    monkeypatch.setenv("NEWSDATA_API_KEY", "k3y-123")
    s = src("API_NEWSDATA", ['"carbon credits"'], params={"prioritydomain": "top", "pages": 2}, env="NEWSDATA_API_KEY")
    pages = []

    def handler(req):
        pages.append(req.url.params.get("page"))
        assert "pages" not in req.url.params and req.url.params["prioritydomain"] == "top"
        if not req.url.params.get("page"):
            return httpx.Response(200, json={"status": "success", "nextPage": "p2", "results": [
                {"link": "https://www.ft.com/content/abc", "title": "Carbon credits rally", "description": "d", "pubDate": "2026-09-16 05:00:00"}]})
        return httpx.Response(200, json={"status": "success", "nextPage": None, "results": [
            {"link": "https://www.ft.com/content/abc", "title": "dup", "pubDate": "2026-09-16 05:00:00"}]})
    res = apis.fetch_api_source(s, client(handler), NOW)
    assert pages == [None, "p2"] and len(res.items) == 1
    assert res.items[0].published_parsed == datetime(2026, 9, 16, 5, tzinfo=timezone.utc)

    def boom(req):
        raise httpx.ConnectError(f"failed for {req.url}")
    bad = apis.fetch_api_source(s, client(boom), NOW)
    assert bad.status == "FAILED" and "k3y-123" not in bad.reason and "***" in bad.reason


def test_registry_api_entries_are_valid_and_eligible():
    reg = load_registry(ROOT / "config" / "sources.yaml")
    api = {s.source_id: s for s in eligible_sources(reg) if s.access_method.startswith("API_")}
    assert set(api) == {"guardian-api", "newsdata-carbon"}  # GDELT entries stay in the registry but are disabled
    gd = {s.source_id: s for s in reg if s.access_method == "API_GDELT"}
    assert set(gd) == {"gdelt-major-press", "gdelt-carbon-trade"} and not any(s.enabled for s in gd.values())
    assert api["guardian-api"].options["api_key_env"] == "GUARDIAN_API_KEY"
    assert gd["gdelt-major-press"].options["api_key_env"] is None
    assert all(len(q) <= 100 for q in api["newsdata-carbon"].options["queries"])  # NewsData free-plan query limit


def test_gdelt_backs_off_on_429_then_gives_up():
    apis._last_gdelt[0] = 0.0
    calls, slept = [], []

    def handler(req):
        calls.append(1)
        return httpx.Response(429)
    s = src("API_GDELT", ["cbam", "lng"])
    res = apis.fetch_api_source(s, client(handler), NOW, sleep=slept.append)
    assert res.status == "FAILED" and "429 after 3 tries" in res.reason
    assert len(calls) == 3 and 20 in slept and 45 in slept  # second query is not attempted


def test_gdelt_recovers_after_disconnect():
    apis._last_gdelt[0] = 0.0
    n = []

    def handler(req):
        n.append(1)
        if len(n) == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return httpx.Response(200, json={"articles": [{"url": "https://www.ft.com/content/x", "title": "CBAM row", "seendate": "20260916T083000Z"}]})
    res = apis.fetch_api_source(src("API_GDELT", ["cbam"]), client(handler), NOW, sleep=lambda x: None)
    assert res.status == "OK" and len(res.items) == 1
