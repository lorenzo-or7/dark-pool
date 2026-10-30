"""NYSE calendar: the server calendar (exchange_calendars), the official NYSE reference, the
table built into the vendored engines, and the routes that refuse a day the engines cannot use."""

from __future__ import annotations

import datetime as dt
import importlib.util

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from .conftest import DEMO

# Official NYSE holidays and 1:00 p.m. early closes for 2026 and 2027, from
# https://www.nyse.com/markets/hours-calendars (the page lists 2025 to 2027). The same dates are
# in the vendored engines, whose author read that page on 2026-10-13, and the provider report of
# 2026-10-30 re-checked the early closes. Update this table when the NYSE publishes 2028.
NYSE_OFFICIAL_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
    "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05",
    "2027-09-06", "2027-11-25", "2027-12-24",
}
NYSE_OFFICIAL_EARLY_CLOSES = {"2026-11-27", "2026-12-24", "2027-11-26"}
OFFICIAL_YEARS = (2026, 2027)

ENGINES = {
    "entry": "trader-entry/entry.py", "exit": "trader-exit/exit.py", "risk": "trader-risk/check.py",
    "alerts": "trader-alerts/alerts.py", "scanner": "trader-scanner/scan.py",
    "timemachine": "trader-timemachine/timemachine.py",
}


def _server_closed_weekdays(year: int) -> set[str]:
    from app.services import market_calendar as mcal
    cal = mcal._calendar()
    sessions = set(cal.sessions_in_range(f"{year}-01-01", f"{year}-12-31").strftime("%Y-%m-%d"))
    weekdays = set(pd.bdate_range(f"{year}-01-01", f"{year}-12-31").strftime("%Y-%m-%d"))
    return weekdays - sessions


def _server_early_closes(year: int) -> set[str]:
    from app.services import market_calendar as mcal
    return {d.strftime("%Y-%m-%d") for d in mcal._calendar().early_closes if d.year == year}


def _load_engine(name: str):  # noqa: ANN202
    from app.config import get_settings
    path = get_settings().dp_skill_dir / ENGINES[name]
    spec = importlib.util.spec_from_file_location(f"dp_cal_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_official_reference_is_current() -> None:
    """Fails once the year passes the last NYSE year in the reference, so it gets re-checked."""
    from app.services import market_calendar as mcal
    assert mcal.NYSE_PUBLISHED_THROUGH == max(OFFICIAL_YEARS)
    assert dt.date.today().year <= max(OFFICIAL_YEARS), (
        "A tabela oficial da NYSE usada neste teste terminou. Confira a página da NYSE e atualize-a.")


@pytest.mark.parametrize("year", OFFICIAL_YEARS)
def test_server_calendar_matches_the_nyse(year: int) -> None:
    assert _server_closed_weekdays(year) == {d for d in NYSE_OFFICIAL_HOLIDAYS if d.startswith(str(year))}
    assert _server_early_closes(year) == {d for d in NYSE_OFFICIAL_EARLY_CLOSES if d.startswith(str(year))}


@pytest.mark.parametrize("name", sorted(ENGINES))
def test_engine_tables_match_the_server_calendar(name: str) -> None:
    mod = _load_engine(name)
    early = set(getattr(mod, "NYSE_EARLY_CLOSE", {}))
    years = sorted({int(d[:4]) for d in early})
    assert years == list(OFFICIAL_YEARS), f"{name}: anos do calendário embutido mudaram: {years}"
    for y in years:
        assert {d for d in early if d.startswith(str(y))} == _server_early_closes(y)
        holidays = getattr(mod, "NYSE_HOLIDAYS", None)
        if holidays is not None:  # trader-timemachine keeps early closes only
            assert {d for d in holidays if d.startswith(str(y))} == _server_closed_weekdays(y)


def test_day_details() -> None:
    from app.services import market_calendar as mcal
    normal = mcal.day(dt.date(2026, 10, 19)).as_dict()
    assert normal == {"date": "2026-10-19", "is_session": True, "reason": None, "open": "09:30", "close": "16:00",
                      "early_close": False, "timezone": "America/New_York"}
    early = mcal.day(dt.date(2026, 11, 27))
    assert early.is_session and early.early_close and early.close_ny == dt.time(13, 0)
    hol = mcal.day(dt.date(2026, 11, 26))
    assert not hol.is_session and hol.reason
    assert mcal.day(dt.date(2026, 10, 24)).reason == "Fim de semana"


def test_status_on_a_known_minute() -> None:
    from app.services import market_calendar as mcal
    st = mcal.status(dt.datetime(2026, 10, 19, 14, 15, tzinfo=dt.UTC))  # 10:15 New York
    assert st["open"] is True and st["now_new_york"] == "2026-10-19 10:15"
    assert st["next_close"].startswith("2026-10-19T16:00")
    closed = mcal.status(dt.datetime(2026, 11, 26, 15, 0, tzinfo=dt.UTC))  # Thanksgiving
    assert closed["open"] is False and closed["next_open"].startswith("2026-11-27T09:30")


def test_engine_coverage_and_refusals() -> None:
    from app.services import market_calendar as mcal
    cov = mcal.coverage()
    assert cov["engine_years"] == {"from": 2026, "to": 2027}
    assert cov["license"] == "Apache-2.0"
    assert mcal.require_engine_session(dt.date(2026, 10, 19)).is_session
    with pytest.raises(mcal.CalendarError) as e:
        mcal.require_engine_session(dt.date(2026, 12, 25))
    assert e.value.code == "market_closed"
    with pytest.raises(mcal.CalendarError) as e:
        mcal.require_engine_session(dt.date(2028, 3, 1))
    assert e.value.code == "calendar_out_of_range"


# ---------------------------------------------------------------- API

def test_calendar_route(client: TestClient) -> None:
    r = client.get("/api/market/calendar?date=2026-11-27", headers=DEMO)
    assert r.status_code == 200
    body = r.json()
    assert body["day"]["early_close"] is True and body["day"]["close"] == "13:00"
    assert set(body["status"]) >= {"open", "next_open", "next_close", "today"}
    assert body["coverage"]["calendar"] == "XNYS"
    # No prices on this route.
    assert "bars" not in body and "quote" not in body
    far = client.get("/api/market/calendar?date=1990-01-02", headers=DEMO)
    assert far.status_code == 422 and far.json()["detail"]["code"] == "calendar_out_of_range"


def test_health_reports_calendar(client: TestClient) -> None:
    h = client.get("/api/health").json()
    assert h["calendar"]["engine_years"] == {"from": 2026, "to": 2027}
    assert h["calendar"]["status"] in ("ok", "warning")


TM = {"symbol": "TSLA", "entry": 364.18, "stop": 358.32, "target": 370.04, "entry_time": "10:15",
      "replays": 1000, "seed": 19}


@pytest.mark.parametrize(("date", "code"), [
    ("2026-09-07", "market_closed"),       # Labor Day
    ("2026-10-24", "market_closed"),       # Saturday
    ("2025-06-02", "calendar_out_of_range"),  # a session, but before the engines' calendar
])
def test_time_machine_refuses_days_the_engine_cannot_use(client: TestClient, date: str, code: str) -> None:
    r = client.post("/api/timemachine", json={**TM, "date": date}, headers=DEMO)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == code
    # Nothing was queued.
    assert not [j for j in client.get("/api/jobs", headers=DEMO).json() if j["type"] == "timemachine.run"]


def test_orb_plan_refuses_a_holiday(client: TestClient) -> None:
    snaps = client.get("/api/snapshots?symbol=TSLA&interval=5m", headers=DEMO).json()
    sid = [s for s in snaps if s["is_fixture"]][0]["id"]
    r = client.post("/api/plan/orb", json={"snapshot_id": sid, "date": "2026-09-07"}, headers=DEMO)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "market_closed"
    ok = client.post("/api/plan/orb", json={"snapshot_id": sid, "date": "2026-10-19"}, headers=DEMO)
    assert ok.status_code == 200
