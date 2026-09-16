from dataclasses import replace
from datetime import datetime, timezone
import httpx
import pytest
from energynews.extract.extractor import excerpt_of, parse_published
from energynews.fetch.fetcher import Robots, SourceHealth, fetch_source
from energynews.fetch.html_list import parse_date_text, parse_listing
from energynews.fetch.urls import canonicalize_url
from energynews.models import Commodity, RawItem, Source
from energynews.sources.registry import RegistryValidationError, eligible_sources, load_registry, reference_sources
from energynews.store.db import ArticleStore
from energynews.config import ROOT
from conftest import mk_article, mk_source

REG = """
sources:
  - {id: a, name: A, url: "https://a.example/rss", tier: 1, source_type: OFFICIAL, commodities: [CRUDE_OIL], access_method: RSS, tos_status: ALLOWED}
  - {id: b, name: B, url: "https://b.example/rss", tier: 2, source_type: TRADE, commodities: [CRUDE_OIL], access_method: RSS, tos_status: UNVERIFIED}
  - {id: c, name: C, url: "https://c.example/rss", tier: 1, source_type: PRESS, commodities: [CRUDE_OIL], access_method: RSS, tos_status: BLOCKED}
  - {id: d, name: D, url: "https://d.example/", tier: 1, source_type: TRADE, commodities: [CARBON_CREDITS], tos_status: REFERENCE_ONLY}
  - {id: e, name: E, url: "https://e.example/rss", tier: 3, source_type: AGGREGATOR, commodities: [CRUDE_OIL], access_method: RSS, tos_status: HEADLINE_ONLY}
"""


def test_ac_1_1_and_1_3_only_fetchable_enabled_sources(tmp_path):
    p = tmp_path / "s.yaml"; p.write_text(REG)
    reg = load_registry(p)
    assert [s.source_id for s in eligible_sources(reg)] == ["a"]
    assert [s.source_id for s in reference_sources(reg)] == ["d"]


@pytest.mark.parametrize("extra,msg", [
    ('{id: a, name: Z, url: "https://z", tier: 1, source_type: PRESS, commodities: [CRUDE_OIL], access_method: RSS}', "duplicate"),
    ('{id: z, name: Z, url: "https://z", tier: 4, source_type: PRESS, commodities: [CRUDE_OIL], access_method: RSS}', "tier"),
    ('{id: z, name: Z, url: "https://z", tier: 1, source_type: BLOG, commodities: [CRUDE_OIL], access_method: RSS}', "source_type"),
    ('{id: z, name: Z, url: "https://z", tier: 1, source_type: OFFICIAL, commodities: [CRUDE_OIL], access_method: HTML_LIST, tos_status: ALLOWED}', "link_pattern"),
])
def test_ac_1_2_registry_validation(tmp_path, extra, msg):
    p = tmp_path / "s.yaml"; p.write_text(REG + "  - " + extra + "\n")
    with pytest.raises(RegistryValidationError, match=msg):
        load_registry(p)


def test_shipped_registry_is_valid_and_cdr_fyi_is_reference_only():
    reg = load_registry(ROOT / "config" / "sources.yaml")
    cdr = next(s for s in reg if s.source_id == "cdr-fyi")
    assert cdr.tos_status == "REFERENCE_ONLY" and cdr not in eligible_sources(reg)
    tier1 = [s for s in eligible_sources(reg) if s.tier == 1]
    assert len(tier1) >= 12 and any(Commodity.CARBON_CREDITS in s.commodities for s in tier1)


def test_ac_2_1_canonical_url_dedupe():
    assert canonicalize_url("https://Ex.com/story/?utm_source=x&id=5") == canonicalize_url("https://ex.com/story?id=5")


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ac_2_2_failure_isolated():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.host == "bad.example":
            return httpx.Response(503)
        return httpx.Response(200, content=b"<rss><channel><item><title>Crude stocks fall sharply</title><link>https://ok.example/1</link><pubDate>Wed, 09 Sep 2026 14:35:00 GMT</pubDate></item></channel></rss>")
    http = _client(handler); robots = Robots(http)
    bad = fetch_source(replace(mk_source("bad", 1), url="https://bad.example/rss"), SourceHealth("bad"), http, robots)
    ok = fetch_source(replace(mk_source("ok", 1), url="https://ok.example/rss"), SourceHealth("ok"), http, robots)
    assert bad.status == "FAILED" and "503" in bad.reason
    assert ok.status == "OK" and len(ok.items) == 1


def test_ac_2_4_robots_disallowed():
    def handler(req):
        return httpx.Response(200, text="User-agent: *\nDisallow: /") if req.url.path == "/robots.txt" else httpx.Response(200, text="")
    http = _client(handler)
    assert fetch_source(replace(mk_source("r", 1), url="https://r.example/rss"), SourceHealth("r"), http, Robots(http)).status == "ROBOTS_DISALLOWED"


LISTING = """<html><body><ul class="news">
<li><h3><a href="/en/news/turkiye-ets-pilot-design">Türkiye's Carbon Market Board clarifies initial national ETS pilot design</a></h3><span>Sep 08, 2026</span></li>
<li><a href="/en/news/quebec-cap-and-trade-update">Québec updates its cap-and-trade regulation</a> <time datetime="2026-09-03">3 September 2026</time></li>
<li><a href="/en/about">About ICAP and its members</a></li>
<li><a href="/en/news/undated-item">A news item without any date shown</a></li>
</ul></body></html>"""


def test_ac_2_5_html_list_adapter():
    src = Source("icap", "ICAP", "https://icapcarbonaction.com/en/news", 1, frozenset({Commodity.CARBON_CREDITS}), "HTML_LIST", "HEADLINE_ONLY", True,
                 "OFFICIAL", "", r"icapcarbonaction\.com/en/news/[a-z0-9-]+$")
    items = parse_listing(LISTING, src, src.url)
    assert [i.url for i in items] == ["https://icapcarbonaction.com/en/news/turkiye-ets-pilot-design", "https://icapcarbonaction.com/en/news/quebec-cap-and-trade-update", "https://icapcarbonaction.com/en/news/undated-item"]
    assert items[0].published_parsed == datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
    assert items[1].published_parsed.date().isoformat() == "2026-09-03"
    assert items[2].published_parsed is None
    def handler(req):
        return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, text="<html><a href='/x'>nothing here at all</a></html>")
    http = _client(handler)
    assert fetch_source(src, SourceHealth("icap"), http, Robots(http)).reason == "SELECTOR_NO_MATCH"


@pytest.mark.parametrize("text,iso", [("Published 2026-09-15", "2026-09-15"), ("September 8, 2026", "2026-09-08"), ("08 September 2026", "2026-09-08"), ("no date", None)])
def test_listing_date_formats(text, iso):
    d = parse_date_text(text)
    assert (d.date().isoformat() if d else None) == iso


def test_ac_3_1_and_3_3_dates():
    assert parse_published(RawItem("s", "u", "t", "", None)) is None
    assert parse_published(RawItem("s", "u", "t", "", "Wed, 09 Sep 2026 10:35:00 -0400")) == datetime(2026, 9, 9, 14, 35, tzinfo=timezone.utc)


def test_ac_n4_1_excerpt_limit(utc):
    assert len(excerpt_of("word " * 400)) <= 300
    a = mk_article("x", "s", "t", utc(2026, 9, 9)); a.excerpt = "y" * 301
    with pytest.raises(ValueError):
        ArticleStore(":memory:").insert_article(a)
