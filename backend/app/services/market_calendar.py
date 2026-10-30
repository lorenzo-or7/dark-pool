"""NYSE trading calendar for the lab, computed locally (no network, no API key).

Source: the `exchange_calendars` library (Apache-2.0), calendar XNYS. It knows holidays and
1:00 p.m. early closes from rules plus ad hoc closures, so it does not expire at the end of a
hard-coded list.

The vendored Day Trader Skill engines keep their own NYSE table (2026 and 2027) and are never
edited. So this module also says how far the engines' table goes, and the routes that hand a
date to an engine refuse a day the engines cannot place on the calendar, instead of letting a
holiday or an unknown year turn into a vague engine error.
"""

from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass
from functools import lru_cache
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
CALENDAR_CODE = "XNYS"
SOURCE_LABEL = "Calendário NYSE (biblioteca exchange_calendars, calculado no servidor)"
OFFICIAL_URL = "https://www.nyse.com/markets/hours-calendars"
# Last year in the official NYSE holiday page, as read on 2026-10-30 (it lists 2025 to 2027).
# The calendar test fails once the current year passes it, so the reference gets re-checked.
NYSE_PUBLISHED_THROUGH = 2027
FIRST_YEAR = 2016  # oldest intraday history the lab plans to use
YEARS_AHEAD = 3

_lock = threading.Lock()
_cal = None
_cal_built_for: int | None = None


class CalendarError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _calendar():  # noqa: ANN202
    """The XNYS calendar, built lazily (pandas is heavy) and rebuilt once a year."""
    global _cal, _cal_built_for
    year = dt.date.today().year
    with _lock:
        if _cal is None or _cal_built_for != year:
            import exchange_calendars as xc
            _cal = xc.get_calendar(CALENDAR_CODE, start=f"{FIRST_YEAR}-01-01",
                                   end=f"{year + YEARS_AHEAD}-12-31")
            _cal_built_for = year
        return _cal


def library_version() -> str:
    try:
        from importlib.metadata import version
        return version("exchange_calendars")
    except Exception:  # noqa: BLE001
        return "unknown"


def calendar_range() -> tuple[dt.date, dt.date]:
    cal = _calendar()
    return cal.first_session.date(), cal.last_session.date()


@lru_cache
def engine_calendar() -> dict:
    """The NYSE table built into the vendored engines (trader-entry is the reference copy)."""
    from ..engines.runner import load_module
    mod = load_module("entry")
    holidays = dict(getattr(mod, "NYSE_HOLIDAYS", {}) or {})
    early = dict(getattr(mod, "NYSE_EARLY_CLOSE", {}) or {})
    years = sorted({int(d[:4]) for d in (*holidays, *early)})
    return {"holidays": holidays, "early_closes": early,
            "first_year": years[0] if years else None, "last_year": years[-1] if years else None}


def _holiday_names(year: int) -> dict[str, str]:
    cal = _calendar()
    names: dict[str, str] = {}
    try:
        s = cal.regular_holidays.holidays(f"{year}-01-01", f"{year}-12-31", return_name=True)
        names.update({ts.strftime("%Y-%m-%d"): str(name) for ts, name in s.items()})
    except Exception:  # noqa: BLE001 - names are a nicety; the session list is what counts
        pass
    for ts in getattr(cal, "adhoc_holidays", []) or []:
        d = ts.strftime("%Y-%m-%d")
        if d.startswith(str(year)):
            names.setdefault(d, "Fechamento extraordinário")
    return names


@dataclass
class Day:
    date: dt.date
    is_session: bool
    reason: str | None
    open_ny: dt.time | None
    close_ny: dt.time | None
    early_close: bool

    def as_dict(self) -> dict:
        return {"date": self.date.isoformat(), "is_session": self.is_session, "reason": self.reason,
                "open": self.open_ny.strftime("%H:%M") if self.open_ny else None,
                "close": self.close_ny.strftime("%H:%M") if self.close_ny else None,
                "early_close": self.early_close, "timezone": "America/New_York"}


def day(d: dt.date) -> Day:
    first, last = calendar_range()
    if not (first <= d <= last):
        raise CalendarError("calendar_out_of_range",
                            f"O calendário do servidor cobre de {first.isoformat()} a {last.isoformat()}.")
    cal = _calendar()
    key = d.isoformat()
    if d.weekday() >= 5:
        return Day(d, False, "Fim de semana", None, None, False)
    if not cal.is_session(key):
        name = _holiday_names(d.year).get(key) or "Feriado da NYSE"
        return Day(d, False, name, None, None, False)
    o = cal.session_open(key).tz_convert(NY).time()
    c = cal.session_close(key).tz_convert(NY).time()
    return Day(d, True, None, o, c, c < dt.time(16, 0))


def status(now_utc: dt.datetime | None = None) -> dict:
    """Is the NYSE open now, and the next open and close, in New York time."""
    now_utc = now_utc or dt.datetime.now(dt.UTC)
    cal = _calendar()
    import pandas as pd
    ts = pd.Timestamp(now_utc)
    is_open = bool(cal.is_open_on_minute(ts, ignore_breaks=True))
    nxt_open = cal.next_open(ts).tz_convert(NY)
    nxt_close = cal.next_close(ts).tz_convert(NY)
    today = day(now_utc.astimezone(NY).date())
    return {"now_new_york": now_utc.astimezone(NY).strftime("%Y-%m-%d %H:%M"), "open": is_open,
            "today": today.as_dict(), "next_open": nxt_open.isoformat(), "next_close": nxt_close.isoformat()}


def coverage() -> dict:
    eng = engine_calendar()
    first, last = calendar_range()
    today = dt.date.today()
    warnings = []
    if eng["last_year"] is not None and today > dt.date(eng["last_year"], 9, 30):
        warnings.append(f"O calendário embutido nos motores termina em {eng['last_year']}. "
                        "Atualize a day-trader-skill antes do fim do ano.")
    if today.year > NYSE_PUBLISHED_THROUGH:
        warnings.append("A referência oficial da NYSE usada nos testes está desatualizada.")
    return {"calendar": CALENDAR_CODE, "source": SOURCE_LABEL, "library": f"exchange_calendars {library_version()}",
            "license": "Apache-2.0", "official_reference": OFFICIAL_URL,
            "nyse_published_through": NYSE_PUBLISHED_THROUGH,
            "server_range": {"from": first.isoformat(), "to": last.isoformat()},
            "engine_years": {"from": eng["first_year"], "to": eng["last_year"]}, "warnings": warnings}


def require_engine_session(d: dt.date) -> Day:
    """A day an engine can be asked about: a NYSE session inside the engines' own calendar years.
    Raises CalendarError with a plain message otherwise."""
    eng = engine_calendar()
    if eng["first_year"] is not None and not (eng["first_year"] <= d.year <= eng["last_year"]):
        raise CalendarError(
            "calendar_out_of_range",
            f"Os motores da day-trader-skill só conhecem o calendário da NYSE de {eng['first_year']} a "
            f"{eng['last_year']}. Escolha uma data nesse intervalo.")
    info = day(d)
    if not info.is_session:
        raise CalendarError("market_closed", f"A NYSE não abriu em {d.isoformat()} ({info.reason}).")
    return info
