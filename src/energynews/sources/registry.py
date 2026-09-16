"""SourceRegistry (FR-1, ADR-006, ADR-018)."""
from __future__ import annotations
from pathlib import Path
import re
import yaml
from ..models import Commodity, Source

ACCESS = {"RSS", "HTML_LIST"}
TOS = {"ALLOWED", "HEADLINE_ONLY", "REFERENCE_ONLY", "BLOCKED", "UNVERIFIED"}
TYPES = {"OFFICIAL", "PRESS", "TRADE", "NEWSROOM", "AGGREGATOR"}
FETCHABLE = {"ALLOWED", "HEADLINE_ONLY"}


class RegistryValidationError(ValueError):
    def __init__(self, entry_id: str, reason: str):
        super().__init__(f"source '{entry_id}': {reason}")
        self.entry_id, self.reason = entry_id, reason


def load_registry(path: Path) -> list[Source]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    out, seen = [], set()
    for i, e in enumerate(data.get("sources", [])):
        sid = str(e.get("id") or f"#{i}")
        if sid in seen:
            raise RegistryValidationError(sid, "duplicate id")
        seen.add(sid)
        tier = e.get("tier")
        if not isinstance(tier, int) or tier not in (1, 2, 3):
            raise RegistryValidationError(sid, f"tier must be 1-3, got {tier!r}")
        stype = e.get("source_type", "PRESS")
        if stype not in TYPES:
            raise RegistryValidationError(sid, f"unknown source_type {stype!r}")
        access = e.get("access_method")
        tos = e.get("tos_status", "UNVERIFIED")
        if tos == "REFERENCE_ONLY":
            access = access or "RSS"
        if access not in ACCESS:
            raise RegistryValidationError(sid, f"unknown access_method {access!r}")
        if tos not in TOS:
            raise RegistryValidationError(sid, f"unknown tos_status {tos!r}")
        try:
            comms = frozenset(Commodity(c) for c in e.get("commodities") or [])
        except ValueError as ex:
            raise RegistryValidationError(sid, str(ex))
        if not comms:
            raise RegistryValidationError(sid, "commodities must be non-empty")
        for k in ("name", "url"):
            if not e.get(k):
                raise RegistryValidationError(sid, f"missing {k}")
        if access == "HTML_LIST" and tos in FETCHABLE:
            if not e.get("link_pattern"):
                raise RegistryValidationError(sid, "HTML_LIST sources need link_pattern")
            try:
                re.compile(e["link_pattern"])
            except re.error as ex:
                raise RegistryValidationError(sid, f"bad link_pattern: {ex}")
        enabled_default = stype != "AGGREGATOR" and tier != 3
        out.append(Source(sid, e["name"], e["url"], tier, comms, access, tos, bool(e.get("enabled", enabled_default)),
                          stype, e.get("terms_note", ""), e.get("link_pattern"), e.get("base_url")))
    return out


def eligible_sources(reg: list[Source]) -> list[Source]:
    return sorted((s for s in reg if s.enabled and s.tos_status in FETCHABLE), key=lambda s: (s.tier, s.source_id))


def skipped_sources(reg: list[Source]) -> list[Source]:
    return [s for s in reg if not (s.enabled and s.tos_status in FETCHABLE)]


def reference_sources(reg: list[Source]) -> list[Source]:
    return [s for s in reg if s.tos_status == "REFERENCE_ONLY"]
