"""TradingCalendar (FR-8)."""
from __future__ import annotations
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


class TradingCalendar:
    def __init__(self, holidays: frozenset[date]):
        self.holidays = holidays

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def next_trading_day(self, d: date) -> date:
        d += timedelta(days=1)
        while not self.is_trading_day(d):
            d += timedelta(days=1)
        return d

    def prev_trading_day(self, d: date) -> date:
        d -= timedelta(days=1)
        while not self.is_trading_day(d):
            d -= timedelta(days=1)
        return d


def event_day(published_at: datetime, settle_tz: str, settle_time: str, cal: TradingCalendar) -> date:
    local = published_at.astimezone(ZoneInfo(settle_tz))
    hh, mm = map(int, settle_time.split(":"))
    d = local.date()
    if cal.is_trading_day(d) and local.time() <= time(hh, mm):
        return d
    return cal.next_trading_day(d)
