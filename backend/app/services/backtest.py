"""Historical backtests of a strategy configuration on frozen data.

Daily rules: the signal uses closes up to day t only; the entry is day t+1's
open; stop and target are checked bar by bar from the entry day (a bar that
touches both counts as the stop); otherwise the trade closes at the close of
the last bar allowed by max_hold_bars. One position at a time.

ORB (5-minute bars): the Time Machine's own `history_replay` on every full
session of the snapshot, so the rule matches trader-timemachine exactly.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Callable
from zoneinfo import ZoneInfo

from ..engines.runner import load_module
from . import indicators as ind
from .market_data import Chart

NY = ZoneInfo("America/New_York")

DAILY_RULES = ("breakout_20d", "bull_flag", "reclaim_ma20", "oversold", "oversold_bounce", "sma_cross", "macd_cross")
RULE_LABELS = {
    "orb": "Rompimento da faixa de abertura (ORB)",
    "breakout_20d": "Rompimento da máxima de fechamento de N dias",
    "bull_flag": "Bandeira de alta (bull flag)",
    "reclaim_ma20": "Retomada da média móvel",
    "oversold": "Sobrevenda (RSI abaixo do limite)",
    "oversold_bounce": "Repique de sobrevenda",
    "sma_cross": "Cruzamento de médias móveis",
    "macd_cross": "Cruzamento do MACD",
}


class BacktestError(Exception):
    pass


def _day(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, NY).date().isoformat()


def signals(rule: str, p: dict, closes: list[float]) -> list[bool]:
    n = len(closes)
    out = [False] * n
    if rule == "breakout_20d":
        lb = int(p.get("lookback", 20))
        for t in range(lb, n):
            out[t] = closes[t] > max(closes[t - lb:t])
    elif rule == "bull_flag":
        pole, flag, rng = float(p.get("pole_pct", 10)), int(p.get("flag_days", 5)), float(p.get("flag_range_pct", 5))
        for t in range(flag + 10, n):
            base, top = closes[t - flag - 10], closes[t - flag]
            window = closes[t - flag + 1:t + 1]
            if base > 0 and (top / base - 1) * 100 > pole and (max(window) / min(window) - 1) * 100 <= rng:
                out[t] = not out[t - 1]  # first day of the flag only
    elif rule == "reclaim_ma20":
        m = ind.sma(closes, int(p.get("period", 20)))
        for t in range(1, n):
            if m[t] is not None and m[t - 1] is not None:
                out[t] = closes[t - 1] < m[t - 1] and closes[t] > m[t]
    elif rule in ("oversold", "oversold_bounce"):
        r = ind.rsi(closes, int(p.get("rsi_period", 14)))
        thr = float(p.get("threshold", 30))
        for t in range(1, n):
            if r[t] is None or r[t - 1] is None:
                continue
            if rule == "oversold":
                out[t] = r[t] < thr <= r[t - 1]
            else:
                out[t] = r[t - 1] < thr and closes[t] > closes[t - 1]
    elif rule == "sma_cross":
        f, s = ind.sma(closes, int(p.get("fast", 20))), ind.sma(closes, int(p.get("slow", 50)))
        for t in range(1, n):
            if None not in (f[t], s[t], f[t - 1], s[t - 1]):
                out[t] = f[t - 1] <= s[t - 1] and f[t] > s[t]
    elif rule == "macd_cross":
        line, sig, _ = ind.macd(closes, int(p.get("fast", 12)), int(p.get("slow", 26)), int(p.get("signal", 9)))
        for t in range(1, n):
            if None not in (line[t], sig[t], line[t - 1], sig[t - 1]):
                out[t] = line[t - 1] <= sig[t - 1] and line[t] > sig[t]
    else:
        raise BacktestError(f"regra desconhecida: {rule}")
    return out


def backtest_daily(chart: Chart, cfg: dict, split_date: str | None = None,
                   cancelled: Callable[[], bool] | None = None) -> dict:
    bars = chart.bars
    if len(bars) < 60:
        raise BacktestError(f"Apenas {len(bars)} candles diários: são necessários pelo menos 60.")
    rule, params = cfg["rule"]["type"], cfg["rule"].get("params") or {}
    ex = cfg["exit"]
    closes = [b["close"] for b in bars]
    sig = signals(rule, params, closes)
    atr = ind.atr([b["high"] for b in bars], [b["low"] for b in bars], closes, 14)
    vol20 = ind.sma([float(b["volume"]) for b in bars], 20)
    min_vol = float((cfg.get("filters") or {}).get("min_avg_volume") or 0)
    min_price = float((cfg.get("filters") or {}).get("min_price") or 0)
    target_r, hold = float(ex["target_r"]), int(ex.get("max_hold_bars", 10))
    trades, t = [], 0
    while t < len(bars) - 1:
        if cancelled and cancelled():
            raise BacktestError("cancelado")
        ok = sig[t] and closes[t] >= min_price and (not min_vol or (vol20[t] or 0) >= min_vol)
        if not ok:
            t += 1
            continue
        e_i = t + 1
        entry = bars[e_i]["open"]
        if ex["stop_type"] == "atr":
            if atr[t] is None:
                t += 1
                continue
            stop = entry - float(ex["stop_value"]) * atr[t]
        else:
            stop = entry * (1 - float(ex["stop_value"]) / 100)
        stop = math.floor(stop * 100) / 100
        risk = entry - stop
        if risk <= 0:
            t += 1
            continue
        target = round(entry + target_r * risk, 2)
        outcome, exit_px, x_i = None, None, None
        last = min(e_i + hold - 1, len(bars) - 1)
        for j in range(e_i, last + 1):
            b = bars[j]
            if b["low"] <= stop:
                outcome, exit_px, x_i = "stop", stop, j
                break
            if b["high"] >= target:
                outcome, exit_px, x_i = "target", target, j
                break
        if outcome is None:
            if last == len(bars) - 1 and last - e_i + 1 < hold:
                break  # still open at the end of the data: not counted
            outcome, exit_px, x_i = "time", bars[last]["close"], last
        r = -1.0 if outcome == "stop" else target_r if outcome == "target" else (exit_px - entry) / risk
        d = _day(bars[e_i]["time"])
        trades.append({
            "entry_date": d, "entry_time": None, "entry": round(entry, 2), "stop": stop, "target": target,
            "exit_price": round(exit_px, 2), "exit_date": _day(bars[x_i]["time"]), "outcome": outcome,
            "r_multiple": round(r, 4),
            "dataset": "full" if not split_date else ("development" if d < split_date else "out_of_sample"),
        })
        t = x_i + 1
    return {
        "bars": len(bars), "first_date": _day(bars[0]["time"]), "last_date": _day(bars[-1]["time"]),
        "signals": sum(sig), "trades": trades, "split_date": split_date,
        "assumptions": [
            "Sinal calculado no fechamento do dia; entrada na abertura do dia seguinte.",
            "Stop verificado antes do alvo em cada candle; candle que toca os dois conta como stop.",
            "Sem custos, spread ou slippage. Gaps através do stop contam como -1R; na prática pode ser pior.",
            "Uma posição por vez. Operação ainda aberta no fim dos dados não é contada.",
        ],
    }


def backtest_orb(snapshot_text: str, symbol: str, cfg: dict, split_date: str | None = None) -> dict:
    tm = load_module("timemachine")
    ex = cfg["exit"]
    or_minutes = int((cfg["rule"].get("params") or {}).get("or_minutes", 15))
    stop_rule = {"or_mid": "or_mid", "or_low": "or_low", "pct": "pct"}.get(ex["stop_type"])
    if stop_rule is None:
        raise BacktestError("ORB aceita stop no meio da faixa, na mínima da faixa ou em %.")
    rule = {"or_minutes": or_minutes, "stop_rule": stop_rule, "stop_pct": float(ex.get("stop_value") or 0),
            "target_r": float(ex["target_r"])}
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    try:
        result = tm.chart_result(snapshot_text, symbol)
        _, bars, _ = tm.parse_bars(result, now)
        sessions, short = tm.full_sessions(tm.split_sessions(bars), "9999-12-31")
    except tm.TMError as e:
        raise BacktestError(str(e))
    if len(sessions) < 5:
        raise BacktestError(f"Apenas {len(sessions)} sessões completas no snapshot.")
    flat = (cfg.get("exit") or {}).get("flat_by") or "16:00"
    hh, mm = (int(x) for x in flat.split(":"))
    last = min((hh * 60 + mm - tm.OPEN_MIN) // 5 - 1, tm.SESSION_BARS - 1)
    h = tm.history_replay(sessions, rule, last)
    trades = [{
        "entry_date": x["date"], "entry_time": x["time"], "entry": x["entry"], "stop": x["stop"],
        "target": x["target"], "exit_price": None, "exit_date": x["date"],
        "outcome": x["outcome"], "r_multiple": x["R"],
        "dataset": "full" if not split_date else ("development" if x["date"] < split_date else "out_of_sample"),
    } for x in h["trades"]]
    return {
        "sessions": len(sessions), "short_sessions": short, "first_date": sessions[0][0],
        "last_date": sessions[-1][0], "signals": h["triggered"], "trades": trades, "split_date": split_date,
        "assumptions": [
            f"Faixa de abertura de {or_minutes} min; entrada no primeiro candle de 5 min que FECHA acima dela.",
            "Regra idêntica ao histórico do trader-timemachine (history_replay).",
            "Stop verificado antes do alvo; sem custos nem slippage.",
            f"Operações não encerradas são fechadas às {flat} (horário de Nova York).",
        ],
    }
