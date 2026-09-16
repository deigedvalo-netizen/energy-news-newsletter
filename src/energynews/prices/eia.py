"""PriceSource adapter: EIA Open Data API v2 daily spot series. Observed points only."""
from __future__ import annotations
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import os
import httpx


def get_prices(benchmark: str, bcfg: dict, start: date, http: httpx.Client, api_key: str | None = None) -> tuple[list[tuple[date, Decimal]], str | None]:
    key = api_key or os.environ.get("EIA_API_KEY")
    if not key:
        return [], "EIA_API_KEY not set"
    url = f"https://api.eia.gov/v2/{bcfg['route']}/data/"
    params = {"api_key": key, "frequency": "daily", "data[0]": "value", "facets[series][]": bcfg["series"],
              "start": start.isoformat(), "sort[0][column]": "period", "sort[0][direction]": "desc", "length": 5000}
    try:
        r = http.get(url, params=params, timeout=30)
        if r.status_code >= 400:
            return [], f"EIA HTTP {r.status_code}"
        rows = r.json().get("response", {}).get("data", [])
    except (httpx.HTTPError, ValueError) as ex:
        return [], f"EIA error {type(ex).__name__}"
    out = []
    for row in rows:
        try:
            v = row.get("value")
            if v is None:
                continue
            p = Decimal(str(v))
            if p > 0:
                out.append((date.fromisoformat(row["period"][:10]), p))
        except (InvalidOperation, KeyError, ValueError):
            continue
    return sorted(out), None if out else "EIA returned no rows"
