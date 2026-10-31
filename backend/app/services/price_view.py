"""What a visitor sees of prices derived from a data provider: dollars, or R and percent.

The display policy (services/policy.py) says the public lab shows signals, metrics and simulation
results, not prices. With DP_SHOW_TRIGGER_PRICES off (the default of the public mode), every
plan, Time Machine run, backtest trade and job derived from provider data is shown in R and in
percent of the entry: 0R at the entry, -1R at the stop, +xR at the target; Monte Carlo bands,
paths and the close histogram in R as well. Nothing changes in the database: the server keeps the
full numbers (to reproduce a run), and the API converts them on the way out.

The package's reference file (TSLA 2026-10-19, part of the MIT-licensed skill) is not provider
data: runs on it keep their dollar values everywhere.
"""

from __future__ import annotations

import re
from typing import Any

from ..config import get_settings

NOTE = ("Preços do provedor ocultos neste laboratório público: valores em R (0R na entrada, −1R no stop) e em % "
        "da entrada.")
PRICE_TEXT = re.compile(r"\$?\b\d{1,6}\.\d{2}\b(?!\s*%)")
PARAM_PRICE_FIELDS = ("entry", "stop", "target")
TRADE_PRICE_FIELDS = ("entry", "stop", "target", "exit_price")


def hiding() -> bool:
    return not get_settings().show_trigger_prices


def _r(x: Any, entry: float, risk: float) -> float | None:
    if not isinstance(x, (int, float)) or risk <= 0:
        return None
    return round((float(x) - entry) / risk, 3)


def _pct(x: Any, entry: float) -> float | None:
    if not isinstance(x, (int, float)) or entry <= 0:
        return None
    return round(100.0 * (float(x) - entry) / entry, 3)


def _scrub_text(items: list) -> list:
    return [("Aviso do motor omitido: cita preços." if isinstance(s, str) and PRICE_TEXT.search(s) else s)
            for s in items]


def plan_view(plan: dict | None) -> dict | None:
    """A plan (entry, stop, target in dollars) -> the same plan in R and percent."""
    if not isinstance(plan, dict) or not isinstance(plan.get("entry"), (int, float)):
        return plan
    entry = float(plan["entry"])
    stop = plan.get("stop")
    risk = entry - float(stop) if isinstance(stop, (int, float)) else 0.0
    keep = ("symbol", "side", "date", "setup", "entry_time", "entry_bar", "stop_rule", "stop_label", "target_label",
            "target_r", "reward_risk", "opening_range", "interval", "atr_bars", "atr_k", "flat_by")
    out = {k: plan[k] for k in keep if k in plan}
    out.update(entry_r=0.0, stop_r=-1.0 if risk > 0 else None,
               target_r=plan.get("target_r") if plan.get("target_r") is not None else _r(plan.get("target"), entry, risk),
               stop_pct=_pct(stop, entry), target_pct=_pct(plan.get("target"), entry),
               risk_pct=round(100.0 * risk / entry, 3) if entry > 0 else None, prices_hidden=True)
    if isinstance(plan.get("atr"), (int, float)) and entry > 0:
        out["atr_pct"] = round(100.0 * float(plan["atr"]) / entry, 3)
    if isinstance(out.get("opening_range"), dict):
        out["opening_range"] = {k: v for k, v in out["opening_range"].items() if k not in ("high", "low")}
    return out


def range_view(orr: dict | None, entry: float | None) -> dict | None:
    """Opening range high/low -> percent of the entry (or nothing when there is no entry)."""
    if not isinstance(orr, dict):
        return orr
    out = {k: v for k, v in orr.items() if k not in ("high", "low", "avg_volume")}
    if entry:
        out.update(high_pct=_pct(orr.get("high"), entry), low_pct=_pct(orr.get("low"), entry))
    out["prices_hidden"] = True
    return out


def trigger_view(trig: dict | None) -> dict | None:
    if not isinstance(trig, dict):
        return trig
    return {k: v for k, v in trig.items() if k not in ("price", "close", "volume")} | {"prices_hidden": True}


def mc_view(mc: dict | None, entry: float, risk: float) -> dict | None:
    """Monte Carlo prices (closes, bands, sample paths, histogram) -> R."""
    if not isinstance(mc, dict):
        return mc
    out = dict(mc)
    for k in ("median_close", "p5_close", "p95_close"):
        if k in out:
            out[k.replace("_close", "_close_r")] = _r(out.pop(k), entry, risk)
    if isinstance(out.get("bands"), list):
        out["bands"] = [[_r(x, entry, risk) for x in row] for row in out["bands"]]
    if isinstance(out.get("sample_paths"), list):
        out["sample_paths"] = [[_r(x, entry, risk) for x in path] for path in out["sample_paths"]]
    if isinstance(out.get("hist"), dict):
        h = out["hist"]
        out["hist"] = {**h, "lo": _r(h.get("lo"), entry, risk), "hi": _r(h.get("hi"), entry, risk)}
    out["unit"] = "R"
    return out


def trade_view(t: dict) -> dict:
    return {**{k: (None if k in TRADE_PRICE_FIELDS else v) for k, v in t.items()}, "prices_hidden": True}


def params_view(params: Any) -> Any:
    if not isinstance(params, dict):
        return params
    out = {k: v for k, v in params.items() if k not in PARAM_PRICE_FIELDS}
    if any(k in params for k in PARAM_PRICE_FIELDS):
        out["prices_hidden"] = True
    return out


def experiment_view(exp: dict, fixture: bool) -> dict:
    """GET /experiments/{id} (and its export). Unchanged when prices may be shown or the run used
    the package's reference file."""
    if fixture or not hiding():
        return exp
    out = dict(exp)
    out["params"] = params_view(exp.get("params"))
    res = exp.get("results")
    if isinstance(res, dict):
        res = dict(res)
        plan = res.get("plan")
        if isinstance(plan, dict) and isinstance(plan.get("entry"), (int, float)):
            entry = float(plan["entry"])
            risk = entry - float(plan.get("stop") or entry)
            res["mc"] = mc_view(res.get("mc"), entry, risk)
            res["plan"] = plan_view(plan)
        for k in ("warnings", "verdict_notes"):
            if isinstance(res.get(k), list):
                res[k] = _scrub_text(res[k])
        res["prices_hidden"] = True
        res["display_note"] = NOTE
        out["results"] = res
    sim = exp.get("simulation")
    if isinstance(sim, dict):
        sim = dict(sim)
        plan = sim.get("plan")
        if isinstance(plan, dict) and isinstance(plan.get("entry"), (int, float)):
            entry = float(plan["entry"])
            risk = entry - float(plan.get("stop") or entry)
            if isinstance(sim.get("results"), dict):
                sim["results"] = {**sim["results"], "mc": mc_view(sim["results"].get("mc"), entry, risk)}
            sim["plan"] = plan_view(plan)
        out["simulation"] = sim
    out["trades"] = [trade_view(t) for t in exp.get("trades") or []]
    return out


def job_view(job: dict, fixture: bool) -> dict:
    if fixture or not hiding():
        return job
    return {**job, "params": params_view(job.get("params"))}
