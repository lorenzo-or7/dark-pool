"""The ORB plan of one session: trader-entry finds the trigger bar, trader-exit sets the stop and
the target. Pure calls on a chart document; no network. Used by POST /api/plan/orb and by the
Time Machine when the plan is kept on the server (a rule instead of prices).
"""

from __future__ import annotations

import datetime as dt
import json

from ..engines.runner import load_module


class PlanRefusal(Exception):
    """The input cannot be read by the engines (bad document, unknown setup)."""


def eval_now(entry, text: str, day: dt.date) -> dt.datetime:  # noqa: ANN001
    """The instant the plan is evaluated at: just after the close, or earlier when the data stops
    earlier (a session still open). Otherwise a day whose bars end at 11:00 would read as
    'expired' at 16:05 instead of 'waiting'. Naive UTC, as the engines use."""
    close_utc = entry.eastern_to_utc(dt.datetime.combine(day, dt.time(16, 5)))
    try:
        data_time = (json.loads(text)["chart"]["result"][0].get("meta") or {}).get("regularMarketTime")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        data_time = None
    if isinstance(data_time, (int, float)):
        return min(close_utc, entry.utc_of(data_time))
    return close_utc


def compute(text: str, symbol: str, day: dt.date, or_minutes: int = 15, stop_rule: str = "or_mid",
            stop_pct: float = 1.0, atr_k: float = 1.5, target_r: float = 1.0) -> dict:
    """-> {triggered, status, reason, opening_range, trigger, plan | None, refusal, notes, evaluated_at}.
    Prices are in dollars here; what a visitor may see is decided by services/price_view.py."""
    entry, exitm = load_module("entry"), load_module("exit")
    now_utc = eval_now(entry, text, day)
    out = {"evaluated_at": entry.to_eastern(now_utc).strftime("%Y-%m-%d %H:%M ET"), "notes": []}
    try:
        chart = entry.parse_chart(text, symbol)
        res = entry.evaluate(chart, now_utc, setup="orb", or_minutes=or_minutes, interval="5m")
    except entry.EntryError as e:
        raise PlanRefusal(str(e)) from e
    pub = entry.public(res)
    orr, trig = pub.get("opening_range"), pub.get("trigger")
    if pub["status"] != "triggered" or not trig or not orr:
        return {**out, "triggered": False, "status": pub["status"], "reason": pub.get("reason"),
                "opening_range": orr, "trigger": None, "plan": None, "engine": "trader-entry"}
    base = {**out, "triggered": True, "status": "triggered", "reason": pub.get("reason"), "opening_range": orr,
            "trigger": trig, "engine": "trader-entry + trader-exit"}
    atr = atr_n = None
    if stop_rule == "atr":
        # trader-exit's own reader and ATR: closed, on-grid bars of the session up to the entry bar.
        bars = exitm.session_bars(chart, day, "5m", trig["bar_index"], now_utc)
        if len(bars) < 3:
            return {**base, "plan": None,
                    "refusal": f"O stop por ATR precisa de pelo menos 3 candles de 5 min fechados até a entrada; "
                               f"há {len(bars)}."}
        atr, atr_n = exitm.atr_of(bars)
    param = atr_k if stop_rule == "atr" else stop_pct
    try:
        plan = exitm.compute(exitm.D(str(trig["price"])), stop_rule, exitm.D(str(param)), "r",
                             exitm.D(str(target_r)), or_high=orr["high"], or_low=orr["low"], atr=atr, atr_bars=atr_n)
    except exitm.PlanError as e:
        return {**base, "plan": None, "refusal": str(e)}
    hh, mm = (int(x) for x in str(trig["time"])[:5].split(":"))
    out_plan = {"symbol": symbol, "date": day.isoformat(), "entry_time": f"{hh:02d}:{mm:02d}",
                "entry": float(plan["entry"]), "stop": float(plan["stop"]), "target": float(plan["target"]),
                "risk_per_share": float(plan["risk"]), "reward_risk": float(plan["reward_risk"]),
                "target_r": float(plan["target_r"]), "stop_rule": stop_rule, "stop_label": plan["stop_label"],
                "stop_detail": plan["stop_detail"], "target_label": plan["target_label"]}
    if atr is not None:
        out_plan.update(atr=round(atr, 4), atr_bars=atr_n, atr_k=atr_k)
    if stop_rule == "atr":
        base["notes"] = ["O histórico do Time Machine não conhece o stop por ATR: ele reexecuta as sessões passadas "
                         "com o mesmo stop em % da entrada."]
    return {**base, "plan": out_plan}
