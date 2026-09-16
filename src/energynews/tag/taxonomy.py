"""Closed taxonomies and deterministic keyword rules (FR-4)."""
import re
from ..models import Commodity

COMMODITY_RULES = {
    Commodity.CRUDE_OIL: r"\b(crude|brent|wti|opec\+?|oil (?:price|prices|output|production|market|markets|demand|supply|field|fields|major|majors|exports?|imports?|stocks?|inventor\w*|tanker|rig|rigs|well|wells|company|companies|producers?|sands)|barrels?|bpd|b/d|shale oil|petroleum|upstream|oilfield)\b",
    Commodity.NATURAL_GAS: r"\b(natural gas|lng|liquefied natural gas|henry hub|gas storage|gas prices?|gas production|gas exports?|bcf|mmbtu|ttf|gas pipeline|pipeline gas|feedgas)\b",
    Commodity.CARBON_CREDITS: r"\b(carbon credits?|carbon offsets?|carbon markets?|carbon prices?|carbon allowances?|emissions? allowances?|eu ets|uk ets|emissions trading(?: system| scheme)?|cap[- ]and[- ](?:trade|invest)|direct air capture|dac|biochar|durable (?:carbon )?removals?|cdr|euas?|rggi|corsia|article 6|voluntary carbon|vcm|carbon removals?|carbon dioxide removal|redd\+?|cbam|carbon border|verra|gold standard|icvcm|compliance market)\b",
    Commodity.REFINED_PRODUCTS: r"\b(gasoline|diesel|jet fuel|refiner(?:y|ies|s|ing)|distillates?|heating oil|rbob|ulsd|crack spreads?|propane|fuel prices?|pump prices?)\b",
}

TOPIC_RULES = [  # order = tie-break priority
    ("SUPPLY_POLICY", r"\b(auctions?|market stability reserve|linear reduction factor|cap|free allocation|opec\+?|quota|quotas|output cuts?|production cuts?|spare capacity|supply (?:cut|cuts|deal|policy)|unwind\w*|strategic petroleum reserve|spr)\b"),
    ("INVENTORIES", r"\b(inventor\w+|stockpiles?|stocks? (?:rose|fell|build|draw)|storage|draws?|builds?|injections?|withdrawals?)\b"),
    ("PRODUCTION", r"\b(production|output|rig counts?|drilling|drillers?|shale|upstream|wells?|permian)\b"),
    ("GEOPOLITICS_DISRUPTION", r"\b(sanctions?|attacks?|war|conflicts?|strait|houthis?|iran\w*|russia\w*|ukrain\w*|israel\w*|venezuela\w*|tensions?|drone)\b"),
    ("WEATHER", r"\b(hurricanes?|storms?|weather|heat ?waves?|cold snaps?|freeze|winter|temperatures?|tropical)\b"),
    ("DEMAND_MACRO", r"\b(offtakes?|buyers?|purchases?|retire\w*|demand|econom\w+|recession|china|fed|interest rates?|gdp|tariffs?|consumption|dollar|inflation)\b"),
    ("REGULATION", r"\b(integrity|registr(?:y|ies)|methodolog\w+|article 6|cbam|regulat\w+|epa|ferc|rules?|permits?|legislation|tax|taxes|mandates?|policy|policies|approval)\b"),
    ("INFRASTRUCTURE_OUTAGE", r"\b(outages?|shut ?downs?|shut-ins?|leaks?|explosions?|fires?|maintenance|force majeure|disrupt\w*)\b"),
    ("SHIPPING_REFINING", r"\b(tankers?|shipping|freight|vessels?|refining margins?|crack spreads?|refinery runs|utilization)\b"),
]

_CR = {c: re.compile(p, re.I) for c, p in COMMODITY_RULES.items()}
_TR = [(t, re.compile(p, re.I)) for t, p in TOPIC_RULES]


def keyword_classify(text: str) -> tuple[set[Commodity], str]:
    comms = {c for c, rx in _CR.items() if rx.search(text)}
    best, best_n = "OTHER", 0
    for t, rx in _TR:
        n = len(rx.findall(text))
        if n > best_n:
            best, best_n = t, n
    return comms, best
