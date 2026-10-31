"""Bloco 4: the ORB plan (trader-entry + trader-exit) with an ATR stop, and the plan of one day
without a snapshot (the day's bars downloaded now and frozen).

The Alpaca cases run on the DERIVED fixture of tests/alpaca_fixtures.py and a fake HTTP layer
(see test_alpaca.py); none of them proves how the real API behaves.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from . import alpaca_fixtures as fx
from .conftest import DEMO, _reset

SENTINEL_KEY = "PKORBPLANSENTINEL0000000"
SENTINEL_SECRET = "ORBPLANSECRETSENTINELneverShow0000000000"
NOW_1106 = fx.edt("2026-10-19", "11:06")  # data_end 10:50 ET: the bars of the skill's file


def _fixture_snapshot(c: TestClient) -> str:
    snaps = c.get("/api/snapshots?symbol=TSLA&interval=5m", headers=DEMO).json()
    return [s for s in snaps if s["is_fixture"]][0]["id"]


def _engine_reference(tmp_path: Path, k: str) -> dict:
    """trader-exit's own CLI on the same file and trigger: the numbers the route must match."""
    from app.engines.runner import run_script
    from app.services import market_data as md
    f = tmp_path / "tsla.json"
    with gzip.open(md.fixture_path(), "rt", encoding="utf-8") as fh:
        f.write_text(fh.read(), encoding="utf-8")
    res = run_script("exit", ["plan", "--symbol", "TSLA", "--entry", "364.18", "--or-high", "362.18",
                              "--or-low", "354.47", "--stop", f"atr:{k}", "--target", "1R", "--offline", str(f),
                              "--date", "2026-10-19", "--time", "10:15 AM", "--entry-bar", "8", "--json",
                              "--now", "2026-10-19 16:05"], tmp_path)
    assert res.returncode == 0, res.stderr
    doc = json.loads(res.stdout)
    return doc.get("plan", doc)


# ---------------------------------------------------------------- ATR stop

def test_atr_stop_matches_the_exit_engine(client: TestClient, tmp_path: Path) -> None:
    sid = _fixture_snapshot(client)
    r = client.post("/api/plan/orb", json={"snapshot_id": sid, "date": "2026-10-19", "stop_rule": "atr",
                                           "atr_k": 1.5, "target_r": 1}, headers=DEMO)
    assert r.status_code == 200, r.text
    body = r.json()
    ref = _engine_reference(tmp_path, "1.5")
    p = body["plan"]
    assert p["entry"] == ref["entry"] == 364.18
    assert p["stop"] == ref["stop"] and p["target"] == ref["target"]
    assert p["atr"] == ref["atr"] and p["atr_bars"] == ref["atr_bars"]
    assert p["stop_rule"] == "atr" and p["atr_k"] == 1.5 and "ATR" in p["stop_label"]
    assert body["data"]["new_snapshot"] is False and body["data"]["source"].startswith("fixture:")


def test_too_tight_atr_stop_is_trader_exits_refusal(client: TestClient) -> None:
    sid = _fixture_snapshot(client)
    r = client.post("/api/plan/orb", json={"snapshot_id": sid, "date": "2026-10-19", "stop_rule": "atr",
                                           "atr_k": 0.01, "target_r": 1}, headers=DEMO).json()
    # 0.01 x ATR is a few cents: under 0.05 % of the price, trader-exit refuses it with its reason.
    assert r["triggered"] is True and r["plan"] is None and "too tight" in r["refusal"]


def test_existing_stop_rules_are_unchanged(client: TestClient) -> None:
    sid = _fixture_snapshot(client)
    r = client.post("/api/plan/orb", json={"snapshot_id": sid, "date": "2026-10-19", "stop_rule": "or_mid",
                                           "target_r": 1}, headers=DEMO).json()
    assert r["plan"]["stop"] == 358.32 and r["plan"]["target"] == 370.04  # the skill's reel
    assert "atr" not in r["plan"]


def test_request_needs_a_snapshot_or_a_symbol(client: TestClient) -> None:
    r = client.post("/api/plan/orb", json={"date": "2026-10-19"}, headers=DEMO)
    assert r.status_code == 422
    sid = _fixture_snapshot(client)
    r = client.post("/api/plan/orb", json={"snapshot_id": sid, "symbol": "AAPL", "date": "2026-10-19"}, headers=DEMO)
    assert r.status_code == 400


def test_strategies_still_refuse_orb_with_atr(client: TestClient) -> None:
    """The ORB backtest and the Time Machine history replay have no ATR rule: unchanged."""
    from app.schemas import StrategyCreate
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        StrategyCreate.model_validate({"name": "x", "config": {
            "symbol": "TSLA", "rule": {"type": "orb", "or_minutes": 15},
            "exit": {"stop_type": "atr", "stop_value": 1.5, "target_r": 1}}})


# ---------------------------------------------------------------- one day, no snapshot (Alpaca)

@pytest.fixture()
def alpaca_lab(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, fx.FakeAlpaca]]:
    monkeypatch.setenv("ALPACA_API_KEY_ID", SENTINEL_KEY)
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", SENTINEL_SECRET)
    _reset()
    from app.main import create_app
    from app.services import alpaca
    from app.services import market_data as md
    f = fx.FakeAlpaca(fx.derived_bars())
    monkeypatch.setattr(alpaca, "_http_get", f)
    monkeypatch.setattr(alpaca, "_now", lambda: NOW_1106)

    def no_yahoo(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("Yahoo must not be called when the 5-minute provider is Alpaca")

    monkeypatch.setattr(md, "fetch_chart_raw", no_yahoo)
    with TestClient(create_app()) as c:
        yield c, f


def test_day_plan_downloads_only_that_session_and_freezes_it(alpaca_lab) -> None:  # noqa: ANN001
    c, f = alpaca_lab
    r = c.post("/api/plan/orb", json={"symbol": "TSLA", "date": "2026-10-19", "stop_rule": "or_mid",
                                      "target_r": 1}, headers=DEMO)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["triggered"] and body["plan"]["entry"] == 364.18 and body["plan"]["stop"] == 358.32
    # One call, only 2026-10-19 from the open until data_end (now - 16 min, 10:50 ET).
    assert len(f.calls) == 1
    assert f.calls[0]["start"] == "2026-10-19T13:30:00Z" and f.calls[0]["end"] == "2026-10-19T14:49:59Z"
    assert f.calls[0]["feed"] == "iex" and f.calls[0]["timeframe"] == "5Min"
    d = body["data"]
    assert d["new_snapshot"] is True and d["source"] == "alpaca:iex"
    assert d["provenance"]["provider"] == "alpaca" and d["provenance"]["feed"] == "iex"
    assert "16 minutos" in d["note"] and "monitoramento" in d["note"]
    assert d["data_quality"]["feed"] == "iex"
    assert d["evaluated_at_utc"] == "2026-10-19T14:50:00Z"
    snap = [s for s in c.get("/api/snapshots?symbol=TSLA", headers=DEMO).json() if s["id"] == d["snapshot_id"]][0]
    assert snap["source"] == "alpaca:iex" and snap["range"] == "1sess"
    # The same plan again from the frozen snapshot: no new download, same numbers.
    again = c.post("/api/plan/orb", json={"snapshot_id": d["snapshot_id"], "date": "2026-10-19",
                                          "stop_rule": "or_mid", "target_r": 1}, headers=DEMO).json()
    assert len(f.calls) == 1 and again["plan"] == body["plan"]


def test_day_plan_with_atr_on_alpaca_data(alpaca_lab, tmp_path: Path) -> None:  # noqa: ANN001
    c, _ = alpaca_lab
    body = c.post("/api/plan/orb", json={"symbol": "TSLA", "date": "2026-10-19", "stop_rule": "atr",
                                         "atr_k": 1.5, "target_r": 1}, headers=DEMO).json()
    ref = _engine_reference(tmp_path, "1.5")
    assert body["plan"]["stop"] == ref["stop"] and body["plan"]["atr_bars"] == ref["atr_bars"]


def test_session_in_progress_without_trigger_reads_waiting(alpaca_lab, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    c, _ = alpaca_lab
    from app.services import alpaca
    monkeypatch.setattr(alpaca, "_now", lambda: fx.edt("2026-10-19", "10:16"))  # data until 10:00 ET
    body = c.post("/api/plan/orb", json={"symbol": "TSLA", "date": "2026-10-19"}, headers=DEMO).json()
    assert body["triggered"] is False and body["status"] == "waiting"


def test_day_not_available_yet_is_a_clear_refusal(alpaca_lab, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    c, f = alpaca_lab
    from app.services import alpaca
    monkeypatch.setattr(alpaca, "_now", lambda: fx.edt("2026-10-19", "09:40"))
    r = c.post("/api/plan/orb", json={"symbol": "TSLA", "date": "2026-10-19"}, headers=DEMO)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_available_yet"
    assert f.calls == []


def test_alpaca_error_is_not_replaced_by_yahoo(alpaca_lab, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    c, _ = alpaca_lab
    from app.services import alpaca
    monkeypatch.setattr(alpaca, "_http_get", fx.FakeAlpaca([], status=401, body={"message": "forbidden"}))
    r = c.post("/api/plan/orb", json={"symbol": "TSLA", "date": "2026-10-19"}, headers=DEMO)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "provider_auth"
    assert SENTINEL_KEY not in r.text and SENTINEL_SECRET not in r.text


def test_day_plan_in_public_lab_without_alpaca_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Public lab, no Alpaca key: the 5-minute provider is Yahoo, which the policy turns off."""
    monkeypatch.setenv("DP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("DP_AUTH_MODE", "demo")
    _reset()
    from app.auth import DEMO_WORKSPACE_ID
    from app.services.seed import bootstrap_demo
    bootstrap_demo()
    monkeypatch.setenv("DP_AUTH_MODE", "public")
    monkeypatch.setenv("DP_PUBLIC_WORKSPACE_ID", str(DEMO_WORKSPACE_ID))
    _reset()
    from app.services.public_lab import setup_public_lab
    setup_public_lab(DEMO_WORKSPACE_ID)
    from app.main import create_app
    with TestClient(create_app(), client=("198.51.100.30", 1)) as c:
        r = c.post("/api/plan/orb", json={"symbol": "TSLA", "date": "2026-10-19"})
        assert r.status_code == 503 and r.json()["detail"]["code"] == "source_disabled"
    _reset()
