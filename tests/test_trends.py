from datetime import datetime, timedelta, timezone
import pytest
from energynews.scoring.ledger import validate_ledger
from energynews.scoring.trends import candidate_groups, compute_trends, hottest

NOW = datetime(2026, 9, 16, 15, tzinfo=timezone.utc)


def story(title, days_ago, tier=1, orgs=(), stype="PRESS"):
    return {"title": title, "excerpt": "", "outlet": "Outlet", "tier": tier, "source_type": stype,
            "published_at": (NOW - timedelta(days=days_ago)).isoformat(), "organizations": [{"org_id": o, "name": o, "org_type": "COMPANY"} for o in orgs]}


INDEX = {
    "https://a.example/1": story("Shell signs LNG supply deal with Japanese buyer", 1),
    "https://a.example/2": story("TotalEnergies agrees long-term LNG sale to Korean utility", 2),
    "https://a.example/3": story("Equinor books LNG offtake with Chinese importer", 3),
    "https://a.example/4": story("QatarEnergy inks LNG supply pact with Indian buyer", 10),
    "https://a.example/5": story("Market roundup: LNG deals continue", 1),
}


def mention(company, url, date="2026-09-15", action="Signed long-term LNG supply deal"):
    return {"date": date, "company": company, "story_url": url, "action": action}


def ledger(*mentions, first_seen="2026-09-01", tid="lng-asia-offtake"):
    return {"trends": [{"trend_id": tid, "name": "LNG supply deals with Asian buyers", "thesis": "Sellers lock in long-term Asian demand.",
                        "commodities": ["NATURAL_GAS"], "first_seen": first_seen, "mentions": list(mentions)}]}


def test_ac_19_1_unsourced_mention_rejected(orgs):
    v = validate_ledger(ledger(mention("Shell", "https://nowhere.example/x")), None, INDEX, orgs)
    assert v.status == "REJECTED" and v.reasons[0]["code"] == "UNSOURCED_MENTION"


def test_ac_19_2_append_only(orgs):
    prev = validate_ledger(ledger(mention("Shell", "https://a.example/1"), mention("TotalEnergies", "https://a.example/2")), None, INDEX, orgs).ledger
    v = validate_ledger(ledger(mention("Shell", "https://a.example/1")), prev, INDEX, orgs)
    assert v.status == "REJECTED" and v.reasons[0]["code"] == "LEDGER_NOT_APPEND_ONLY"
    grown = validate_ledger(ledger(mention("Shell", "https://a.example/1"), mention("TotalEnergies", "https://a.example/2"), mention("Equinor", "https://a.example/3")), prev, INDEX, orgs)
    assert grown.status == "ACCEPTED" and len(grown.ledger["trends"][0]["mentions"]) == 3


def test_ac_19_3_and_19_4_company_verification(orgs):
    v = validate_ledger(ledger(mention("Shell plc", "https://a.example/1"), mention("Aramco", "https://a.example/5")), None, INDEX, orgs)
    ms = v.ledger["trends"][0]["mentions"]
    assert v.status == "ACCEPTED" and ms[0]["verified"] and ms[0]["company_name"] == "Shell"
    assert not ms[1]["verified"] and ms[1]["reason"] == "UNVERIFIED_COMPANY"


def test_bad_ledger_schema(orgs):
    bad = ledger(mention("Shell", "https://a.example/1", action=" ".join(["word"] * 21)))
    assert validate_ledger(bad, None, INDEX, orgs).reasons[0]["code"] == "BAD_LEDGER"


def views_for(*mentions, first_seen="2026-09-01", orgs=None):
    v = validate_ledger(ledger(*mentions, first_seen=first_seen), None, INDEX, orgs)
    assert v.status == "ACCEPTED", v.reasons
    return compute_trends(v.ledger, NOW)


def test_ac_7_1_single_company_is_emerging(orgs):
    [t] = views_for(mention("Shell", "https://a.example/1"), orgs=orgs)
    assert t["status"] == "EMERGING" and hottest([t]) == []


def test_ac_7_2_rising(orgs):
    [t] = views_for(mention("QatarEnergy", "https://a.example/4", "2026-09-06"), mention("Shell", "https://a.example/1"),
                    mention("TotalEnergies", "https://a.example/2"), mention("Equinor", "https://a.example/3"), orgs=orgs)
    assert (t["companies_current"], t["companies_previous"], t["trajectory"], t["status"]) == (3, 1, "RISING", "CONFIRMED")
    assert hottest([t])[0]["trend_id"] == "lng-asia-offtake"


def test_ac_7_3_new(orgs):
    [t] = views_for(mention("Shell", "https://a.example/1"), mention("TotalEnergies", "https://a.example/2"), orgs=orgs)
    assert t["trajectory"] == "NEW"


def test_ac_7_4_fading(orgs):
    idx = {"https://b.example/1": story("Shell signs LNG deal", 9), "https://b.example/2": story("TotalEnergies signs LNG deal", 10)}
    v = validate_ledger(ledger(mention("Shell", "https://b.example/1"), mention("TotalEnergies", "https://b.example/2")), None, idx, orgs)
    [t] = compute_trends(v.ledger, NOW)
    assert (t["companies_current"], t["companies_previous"], t["trajectory"]) == (0, 2, "FADING")


def test_ac_7_5_hotness(orgs):
    idx = {"https://c.example/1": story("Shell signs LNG deal with TotalEnergies", 3, tier=1)}
    v = validate_ledger(ledger(mention("Shell", "https://c.example/1"), mention("TotalEnergies", "https://c.example/1")), None, idx, orgs)
    [t] = compute_trends(v.ledger, NOW)
    assert t["companies_current"] == 2 and t["hotness"] == "7.50"


def test_ac_7_6_deterministic(orgs):
    ms = [mention("Shell", "https://a.example/1"), mention("TotalEnergies", "https://a.example/2")]
    assert views_for(*ms, orgs=orgs) == views_for(*ms, orgs=orgs)


def test_candidate_groups():
    items = [{"cluster_id": "a", "title": "Shell LNG deal", "topic": "SUPPLY_POLICY", "commodities": ["NATURAL_GAS"], "sources": [{"url": "u1"}],
              "organizations": [{"org_id": "shell", "name": "Shell", "org_type": "COMPANY"}]},
             {"cluster_id": "b", "title": "BP LNG deal", "topic": "SUPPLY_POLICY", "commodities": ["NATURAL_GAS"], "sources": [{"url": "u2"}],
              "organizations": [{"org_id": "bp", "name": "BP", "org_type": "COMPANY"}, {"org_id": "eia", "name": "EIA", "org_type": "AGENCY"}]}]
    [g] = candidate_groups(items)
    assert g["companies"] == ["BP", "Shell"] and g["commodity"] == "NATURAL_GAS"
