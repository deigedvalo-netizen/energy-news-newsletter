from datetime import datetime, timezone
import pytest
from energynews.models import Article, Commodity, Source
from energynews.config import ROOT
from energynews.tag.organizations import OrganizationIndex


def mk_source(sid, tier, tos="ALLOWED", stype="PRESS"):
    return Source(sid, sid.upper(), f"https://{sid}.example/rss", tier, frozenset(Commodity), "RSS", tos, True, stype)


def mk_article(aid, sid, title, published, commodities=(Commodity.CRUDE_OIL,), topic="INVENTORIES", excerpt=""):
    return Article(aid, sid, f"https://{sid}.example/{aid}", title, published, excerpt or title, "h" + aid,
                   frozenset(commodities), topic, "OK", published)


@pytest.fixture
def utc():
    return lambda *a: datetime(*a, tzinfo=timezone.utc)


@pytest.fixture(scope="session")
def orgs():
    return OrganizationIndex.load(ROOT / "config" / "organizations.yaml")
