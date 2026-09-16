"""Settings loading shared by all stages."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    raw: dict

    def __getitem__(self, k):
        return self.raw[k]

    @property
    def holidays(self) -> frozenset[date]:
        return frozenset(d if isinstance(d, date) else date.fromisoformat(str(d)) for d in self.raw.get("exchange_holidays", []))


def load_settings(path: Path | None = None) -> Settings:
    path = path or ROOT / "config" / "settings.yaml"
    return Settings(yaml.safe_load(Path(path).read_text()))
