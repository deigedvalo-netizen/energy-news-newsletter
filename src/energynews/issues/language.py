"""Number normalisation and advisory/forecast language checks (FR-15, FR-17)."""
import re

NUMBER = re.compile(r"[+\-−]?\d[\d,]*(?:\.\d+)?")
# Descriptive reporting ("Microsoft agreed to buy credits", "buyers") is allowed. Advice and forecasts are not.
ADVISORY = re.compile(
    r"\b("
    r"(?:should|must|consider|time to|good time to|opportunity to|recommend(?:ed|s)?|we suggest|you may want to)\s+(?:buy(?:ing)?|sell(?:ing)?|short(?:ing)?|go(?:ing)? long|go(?:ing)? short|hedg(?:e|ing)|accumulat(?:e|ing))|"
    r"go(?:ing)? (?:long|short)|(?:buy|sell) signal|price targets?|trading opportunit\w+|trade idea\w*|"
    r"(?:bullish|bearish) (?:bet|position|trade|call)|position(?:ing)? for|"
    r"expect(?:s|ed)? prices? to|prices? (?:will|should) (?:rise|fall|climb|drop|head|move|trend)|"
    r"(?:is|are) (?:likely|poised|set|expected|bound) to (?:rise|fall|climb|drop|rally|decline|increase|decrease|surge|plunge|rebound)|"
    r"will (?:rise|fall|climb|drop|surge|plunge|rally|rebound)|"
    r"could (?:push|send|lift|drive|pressure|boost|sink) (?:prices|crude|oil|gas|carbon|allowances)"
    r")\b", re.I)


def norm_number(tok: str) -> str:
    t = tok.replace(",", "").replace("−", "-").lstrip("+-")
    if "." in t:
        t = t.rstrip("0").rstrip(".") or "0"
    return t


def numbers_in(text: str) -> set[str]:
    return {norm_number(m.group(0)) for m in NUMBER.finditer(text)}


def has_advisory(text: str) -> bool:
    return ADVISORY.search(text) is not None
