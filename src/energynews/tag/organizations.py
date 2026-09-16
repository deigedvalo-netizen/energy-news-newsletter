"""Organization tagging (FR-4) and company verification helpers (FR-19)."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata
import yaml


def fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


@dataclass(frozen=True)
class Org:
    org_id: str
    name: str
    org_type: str
    patterns: tuple[re.Pattern, ...]

    def ref(self) -> dict:
        return {"org_id": self.org_id, "name": self.name, "org_type": self.org_type}


def _pattern(alias: str) -> re.Pattern:
    a = re.escape(fold(alias))
    return re.compile(rf"(?<![\w.]){a}(?![\w])")


class OrganizationIndex:
    def __init__(self, orgs: list[Org]):
        self.orgs = orgs
        self.by_key = {}
        for o in orgs:
            for key in (o.org_id, fold(o.name)):
                self.by_key[key] = o

    @classmethod
    def load(cls, path: Path) -> "OrganizationIndex":
        data = yaml.safe_load(Path(path).read_text()) or {}
        orgs = []
        for e in data.get("organizations", []):
            names = ([e["name"]] if e.get("match_name", True) else []) + list(e.get("aliases", []))
            orgs.append(Org(e["id"], e["name"], e.get("org_type", "COMPANY"), tuple(_pattern(n) for n in names if n)))
        return cls(orgs)

    def tag(self, text: str) -> list[dict]:
        t = fold(text or "")
        return [o.ref() for o in self.orgs if any(p.search(t) for p in o.patterns)]

    def lookup(self, company: str) -> Org | None:
        key = fold(company or "").strip()
        if key in self.by_key:
            return self.by_key[key]
        for o in self.orgs:
            if any(p.fullmatch(key) for p in o.patterns):
                return o
        return None

    def mentioned_in(self, company: str, text: str, org_refs: list[dict]) -> bool:
        """True if the company (or a known alias) is named in the text or among the story's tagged organizations."""
        o = self.lookup(company)
        if o is not None:
            if any(r.get("org_id") == o.org_id for r in org_refs):
                return True
            t = fold(text or "")
            return any(p.search(t) for p in o.patterns)
        return _pattern(company).search(fold(text or "")) is not None
