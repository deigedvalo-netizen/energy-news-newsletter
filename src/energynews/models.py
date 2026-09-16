"""Shared domain types (architecture_spec data_model)."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from enum import Enum


class Commodity(str, Enum):
    CRUDE_OIL = "CRUDE_OIL"
    NATURAL_GAS = "NATURAL_GAS"
    REFINED_PRODUCTS = "REFINED_PRODUCTS"
    CARBON_CREDITS = "CARBON_CREDITS"


class Topic(str, Enum):
    SUPPLY_POLICY = "SUPPLY_POLICY"
    INVENTORIES = "INVENTORIES"
    PRODUCTION = "PRODUCTION"
    GEOPOLITICS_DISRUPTION = "GEOPOLITICS_DISRUPTION"
    WEATHER = "WEATHER"
    DEMAND_MACRO = "DEMAND_MACRO"
    REGULATION = "REGULATION"
    INFRASTRUCTURE_OUTAGE = "INFRASTRUCTURE_OUTAGE"
    SHIPPING_REFINING = "SHIPPING_REFINING"
    OTHER = "OTHER"


TOPIC_LABELS = {
    "SUPPLY_POLICY": "Supply policy", "INVENTORIES": "Inventories", "PRODUCTION": "Production",
    "GEOPOLITICS_DISRUPTION": "Geopolitics & disruption", "WEATHER": "Weather", "DEMAND_MACRO": "Demand & macro",
    "REGULATION": "Regulation", "INFRASTRUCTURE_OUTAGE": "Infrastructure & outages",
    "SHIPPING_REFINING": "Shipping & refining", "OTHER": "Other",
}


class FlagKind(str, Enum):
    STALE_SOURCE = "STALE_SOURCE"
    ROBOTS_DISALLOWED = "ROBOTS_DISALLOWED"
    UNDATED = "UNDATED"
    UNCLASSIFIED = "UNCLASSIFIED"
    NOT_RELEVANT = "NOT_RELEVANT"
    CONFLICTING_FIGURES = "CONFLICTING_FIGURES"
    PRICE_MISSING = "PRICE_MISSING"
    CONFOUNDED = "CONFOUNDED"
    UNGROUNDED_SUMMARY = "UNGROUNDED_SUMMARY"
    SELECTOR_NO_MATCH = "SELECTOR_NO_MATCH"
    STORAGE_LIMIT = "STORAGE_LIMIT"
    FIGURE_DROPPED = "FIGURE_DROPPED"


@dataclass(frozen=True)
class Source:
    source_id: str
    name: str
    url: str
    tier: int
    commodities: frozenset[Commodity]
    access_method: str  # RSS | HTML_LIST
    tos_status: str  # ALLOWED | HEADLINE_ONLY | REFERENCE_ONLY | BLOCKED | UNVERIFIED
    enabled: bool
    source_type: str = "PRESS"  # OFFICIAL | PRESS | TRADE | NEWSROOM | AGGREGATOR
    terms_note: str = ""
    link_pattern: str | None = None  # HTML_LIST: regex matched against item hrefs
    base_url: str | None = None


@dataclass
class RawItem:
    source_id: str
    url: str
    title: str
    summary: str
    published: str | None  # raw string or ISO from feed parser
    published_parsed: datetime | None = None


@dataclass
class ExtractedFigure:
    article_id: str
    span: str
    context: str
    unit: str
    keyword: str


@dataclass
class Article:
    article_id: str
    source_id: str
    canonical_url: str
    title: str
    published_at: datetime | None
    excerpt: str
    content_hash: str
    commodities: frozenset[Commodity] = frozenset()
    topic: str | None = None
    status: str = "OK"
    fetched_at: datetime | None = None
    figures: list[ExtractedFigure] = field(default_factory=list)
    organizations: list[dict] = field(default_factory=list)  # [{org_id, name, org_type}]


@dataclass
class Cluster:
    cluster_id: str
    article_ids: list[str]
    commodities: frozenset[Commodity]
    topic: str
    first_published_at: datetime
    distinct_source_count: int
    title: str = ""
    summary: str = ""
    best_tier: int = 3
    organizations: list[dict] = field(default_factory=list)


@dataclass
class PriceEffect:
    cluster_id: str
    benchmark: str
    event_day: date
    status: str  # OK | PRICE_MISSING | PENDING
    day_move: Decimal | None = None
    two_day_move: Decimal | str | None = None  # Decimal | "PENDING" | None
    sigma20: Decimal | None = None
    z: Decimal | None = None
    p_t: Decimal | None = None
    p_prev: Decimal | None = None
    prev_day: date | None = None
    confounded_with: list[str] = field(default_factory=list)


@dataclass
class Flag:
    kind: str
    subject_id: str
    reason: str
