"""Public lab display in R and percent (approved 2026-10-31): unit tests of services/price_view.py
and the Scanner's relative chart."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from .test_policy import public_default  # noqa: F401  (fixture)

PLAN = {"symbol": "TSLA", "date": "2026-10-19", "entry": 364.18, "stop": 358.32, "target": 370.04,
        "entry_time": "10:15", "risk_per_share": 5.86, "target_r": 1.0, "stop_rule": "or_mid",
        "stop_detail": "($362.18 + $354.47) / 2 = $358.325, rounded down", "opening_range": {"minutes": 15}}


def test_plan_view_has_no_dollar_values(settings_env) -> None:  # noqa: ANN001
    from app.services import price_view as pv
    v = pv.plan_view(PLAN)
    assert (v["entry_r"], v["stop_r"], v["target_r"]) == (0.0, -1.0, 1.0)
    assert v["stop_pct"] == round(100 * (358.32 - 364.18) / 364.18, 3) and v["risk_pct"] > 0
    text = json.dumps(v)
    for price in ("364.18", "358.32", "370.04", "362.18", "354.47", "5.86"):
        assert price not in text, price


def test_mc_view_converts_every_price_to_r(settings_env) -> None:  # noqa: ANN001
    from app.services import price_view as pv
    mc = {"median_close": 364.18, "p5_close": 358.32, "p95_close": 370.04, "bands": [[364.18] * 5, [358.32, 361.25, 364.18, 367.11, 370.04]],
          "sample_paths": [[364.18, 370.04]], "hist": {"lo": 352.46, "hi": 375.9, "bins": [1, 2]}, "p_target": 0.27}
    v = pv.mc_view(mc, 364.18, 5.86)
    assert (v["median_close_r"], v["p5_close_r"], v["p95_close_r"]) == (0.0, -1.0, 1.0)
    assert v["bands"] == [[0.0] * 5, [-1.0, -0.5, 0.0, 0.5, 1.0]] and v["sample_paths"] == [[0.0, 1.0]]
    assert v["hist"]["lo"] == -2.0 and v["hist"]["hi"] == 2.0 and v["hist"]["bins"] == [1, 2]
    assert v["p_target"] == 0.27 and v["unit"] == "R" and "median_close" not in v


def test_engine_texts_with_prices_are_omitted(settings_env) -> None:  # noqa: ANN001
    from app.services import price_view as pv
    out = pv._scrub_text(["the plan's entry 364.18 is outside that bar's range 360.10 to 363.00",
                          "12.5 % of the replays hit neither by 4:00 PM", "Average R is +0.028 all the same"])
    assert out[0].startswith("Aviso do motor omitido") and out[1].startswith("12.5 %") and out[2].startswith("Average")


def test_demo_keeps_dollars(settings_env) -> None:  # noqa: ANN001
    from app.services import price_view as pv
    exp = {"params": {"entry": 1.0}, "results": {"plan": PLAN}, "trades": [{"entry": 1.0, "r_multiple": 1}]}
    assert pv.experiment_view(exp, fixture=False) == exp


def test_relative_chart_has_no_price_level(public_default: TestClient,  # noqa: F811
                                           monkeypatch: pytest.MonkeyPatch, offline_yahoo: None) -> None:
    c = public_default
    monkeypatch.setenv("DP_ALLOW_UNOFFICIAL_SOURCES", "true")
    from app import config
    config.get_settings.cache_clear()
    assert c.get("/api/assets/TSLA/chart?range=1d").status_code == 403
    r = c.get("/api/assets/TSLA/relative?range=1d")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["prices_hidden"] is True and "bars" not in body
    s = body["series"]
    assert s["return_pct"][0] == 0.0 and len(s["return_pct"]) == len(body["time"]) == len(s["rsi14"])
    assert set(body["quote"]) == {"change_pct"}
    for price in ("364.18", "362.18", "354.47"):
        assert price not in r.text
