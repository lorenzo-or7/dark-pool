"""Today's ORB signal of one symbol, from real-time IEX bars of the Alpaca market-data API.

The free plan serves IEX in real time (the SIP only with 15 minutes of delay, useless for an entry),
so the agent always asks for feed=iex up to the last closed 5-minute bar. The bars go through the
same converter and the same engines (trader-entry + trader-exit) as POST /api/plan/orb; nothing
in the plan's arithmetic is new here.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from ..services import alpaca, orb_plan
from ..services import market_calendar as mcal
from .settings import AgentSettings

FEED = "iex"


@dataclass
class Signal:
    symbol: str
    status: str                 # waiting | triggered | expired | no_data | refused
    reason: str | None
    plan: dict | None           # entry, stop, target, entry_time (HH:MM ET, the trigger bar's close)
    data_end: dt.datetime | None
    bars: int = 0


def data_end_for(day: dt.date, now_utc: dt.datetime) -> dt.datetime:
    """The end of the last closed 5-minute bar, never past the session close."""
    _, close = alpaca._open_close(day)
    return min(close, alpaca._floor5(now_utc))


def today_signal(symbol: str, day: dt.date, now_utc: dt.datetime, s: AgentSettings) -> Signal:
    open_utc, _ = alpaca._open_close(day)
    end = data_end_for(day, now_utc)
    if end <= open_utc:
        return Signal(symbol, "waiting", "O pregão ainda não abriu.", None, None)
    window = alpaca.Window(day, (day,), open_utc, end, 0)
    try:
        bars = alpaca.fetch_bars(symbol, alpaca.TIMEFRAME_5M, open_utc, end - dt.timedelta(seconds=1), FEED)
    except alpaca.AlpacaError as e:
        return Signal(symbol, "no_data", f"{e.code}: {e.message}", None, end)
    if not bars:
        return Signal(symbol, "no_data", "Sem candles IEX hoje.", None, end, 0)
    text = alpaca.to_chart_document(symbol, bars, window, FEED)
    try:
        res = orb_plan.compute(text, symbol, day, or_minutes=s.dp_agent_or_minutes, stop_rule=s.dp_agent_stop_rule,
                               stop_pct=s.dp_agent_stop_pct, atr_k=s.dp_agent_atr_k, target_r=s.dp_agent_target_r)
    except orb_plan.PlanRefusal as e:
        return Signal(symbol, "refused", str(e), None, end, len(bars))
    if not res.get("triggered"):
        return Signal(symbol, res.get("status") or "waiting", res.get("reason"), None, end, len(bars))
    if not res.get("plan"):
        return Signal(symbol, "refused", res.get("refusal") or "Sem plano.", None, end, len(bars))
    return Signal(symbol, "triggered", res.get("reason"), res["plan"], end, len(bars))


def trigger_time_utc(day: dt.date, entry_time: str) -> dt.datetime:
    h, m = (int(x) for x in entry_time.split(":"))
    return dt.datetime.combine(day, dt.time(h, m), mcal.NY).astimezone(dt.UTC)
