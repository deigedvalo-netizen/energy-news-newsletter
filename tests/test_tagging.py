from datetime import timedelta
from decimal import Decimal
from energynews.cluster.clusterer import cluster_articles
from energynews.models import Commodity, ExtractedFigure
from energynews.scoring.relevance import relevance
from energynews.tag.figures import conflicting_figures, extract_figures
from energynews.tag.summarize import first_sentence
from energynews.tag.tagger import tag_article
from conftest import mk_article


def blank(utc):
    a = mk_article("1", "s", "", utc(2026, 9, 9), ())
    a.commodities, a.topic = frozenset(), None
    return a


def test_ac_4_1_lng_companies(utc, orgs):
    a = blank(utc)
    tag_article(a, "Venture Global and Cheniere expand US LNG export capacity", orgs)
    assert Commodity.NATURAL_GAS in a.commodities
    names = {o["name"]: o["org_type"] for o in a.organizations}
    assert names == {"Venture Global": "COMPANY", "Cheniere Energy": "COMPANY"}


def test_ac_4_2_not_relevant(utc, orgs):
    a = blank(utc)
    tag_article(a, "Company announces new head of human resources", orgs)
    assert a.status == "NOT_RELEVANT"


def test_ac_4_3_carbon_and_government(utc, orgs):
    a = blank(utc)
    tag_article(a, "EU carbon allowances slide after European Commission proposes changes to EU ETS auctions", orgs)
    assert a.commodities == frozenset({Commodity.CARBON_CREDITS})
    assert {"name": "European Commission", "org_type": "GOVERNMENT", "org_id": "european-commission"} in a.organizations


def test_org_aliases_avoid_false_positives(orgs):
    tagged = {o["name"] for o in orgs.tag("Deforestation in the Amazon rainforest threatens carbon credit integrity; seashells")}
    assert "Amazon" not in tagged and "Shell" not in tagged


def eia_set(utc):
    t = utc(2026, 9, 9, 15)
    titles = ["EIA: US crude oil inventories fell 4.1 million barrels last week", "US crude inventories fall 4.1 million barrels, EIA says",
              "Crude oil inventories drop 4.1 million barrels in EIA weekly report", "EIA weekly report shows crude inventories fell by 4.1 million barrels"]
    return [mk_article(str(i), f"src{i}", ti, t + timedelta(hours=i * 3)) for i, ti in enumerate(titles)]


def test_ac_5_1_to_5_4_clustering(utc):
    cs = cluster_articles(eia_set(utc))
    assert len(cs) == 1 and cs[0].distinct_source_count == 4
    same = eia_set(utc)[:3]
    for a in same:
        a.source_id = "same"
    assert cluster_articles(same)[0].distinct_source_count == 1
    a = mk_article("a", "s1", "OPEC+ meeting agrees to raise oil output", utc(2026, 9, 1), topic="SUPPLY_POLICY")
    b = mk_article("b", "s2", "OPEC+ meeting agrees to raise oil output", utc(2026, 9, 7), topic="SUPPLY_POLICY")
    assert len(cluster_articles([a, b])) == 2
    assert [c.article_ids for c in cluster_articles(eia_set(utc))] == [c.article_ids for c in cluster_articles(list(reversed(eia_set(utc))))]


def test_different_events_not_merged(utc):
    t = utc(2026, 9, 9, 15)
    arts = [mk_article("a", "s1", "EIA: US crude oil inventories fell 4.1 million barrels last week", t),
            mk_article("b", "s2", "Oil prices slide as China factory data weakens demand outlook", t, topic="DEMAND_MACRO"),
            mk_article("c", "s3", "Hurricane forces shutdown of Gulf of Mexico oil platforms", t, topic="WEATHER")]
    assert len(cluster_articles(arts)) == 3


def test_ac_6_1_figures_verbatim(utc):
    a = mk_article("1", "s", "t", utc(2026, 9, 9))
    text = "US crude production rose to 13.4 million barrels per day in June. Microsoft agreed to purchase 3.7 million tonnes of carbon removal."
    extract_figures(a, text)
    assert [f.span for f in a.figures] == ["13.4 million barrels per day", "3.7 million tonnes"]
    assert all(f.span in text for f in a.figures)


def test_ac_6_2_conflicting(utc):
    a = mk_article("1", "s1", "t", utc(2026, 9, 9)); b = mk_article("2", "s2", "t", utc(2026, 9, 9))
    a.figures = [ExtractedFigure("1", "3.9 million barrels", "c", "million barrels", "inventor")]
    b.figures = [ExtractedFigure("2", "4.1 million barrels", "c", "million barrels", "inventor")]
    assert conflicting_figures("c1", [a, b])[1]


def test_ac_11_1_extractive_summary():
    assert first_sentence("U.S. crude inventories fell 4.1 million barrels. Stocks at Cushing rose.") == "U.S. crude inventories fell 4.1 million barrels."


def test_ac_9_3_and_9_4_relevance():
    assert relevance(Decimal(3), 1) == 58
    assert relevance(Decimal("0.3"), 3) == 15 and relevance(Decimal("0.3"), 3) < 30


import pytest
from energynews.issues.language import has_advisory


@pytest.mark.parametrize("text,bad", [
    ("Traders should buy crude here.", True), ("Crude is likely to rise next week.", True), ("This could push prices higher.", True),
    ("Now is a good time to sell allowances.", True), ("Consider hedging winter gas.", True), ("Go long Henry Hub.", True),
    ("Microsoft agreed to buy durable carbon removal credits.", False), ("Corporate carbon removal buying is broadening.", False),
    ("Buyers signed long-term LNG deals.", False), ("Inventory draws are generally read as a sign of tighter supply.", False),
])
def test_advisory_language(text, bad):
    assert has_advisory(text) is bad
