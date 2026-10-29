from __future__ import annotations

import math
import random

from app.services import indicators as ind
from app.services.backtest import backtest_daily, signals
from app.services.market_data import Chart
from app.services.metrics import summarize


def test_sma_ema_rsi_known_values() -> None:
    xs = [1, 2, 3, 4, 5]
    assert ind.sma(xs, 3) == [None, None, 2, 3, 4]
    assert ind.ema(xs, 3)[2] == 2 and ind.ema(xs, 3)[3] == 3
    assert ind.rsi([float(i) for i in range(30)], 14)[-1] == 100.0
    up_down = [10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11]
    assert math.isclose(ind.rsi(up_down, 14)[14], 50.0, abs_tol=1e-9)


def test_macd_is_aligned_and_starts_late() -> None:
    xs = [100 + math.sin(i / 3) for i in range(60)]
    line, sig, hist = ind.macd(xs)
    assert line[24] is None and line[25] is not None
    assert sig[25 + 7] is None and sig[25 + 8] is not None
    assert len(line) == len(sig) == len(hist) == 60


def _walk(n: int, seed: int) -> list[float]:
    rnd = random.Random(seed)
    xs, p = [], 100.0
    for _ in range(n):
        p *= 1 + rnd.gauss(0.0005, 0.02)
        xs.append(round(p, 2))
    return xs


def test_signals_never_look_ahead() -> None:
    """A signal on day t must not change when the data after t is removed."""
    closes = _walk(400, 3)
    params = {"lookback": 20, "pole_pct": 10, "flag_days": 5, "flag_range_pct": 5, "period": 20,
              "rsi_period": 14, "threshold": 30, "fast": 20, "slow": 50}
    for rule in ("breakout_20d", "bull_flag", "reclaim_ma20", "oversold", "oversold_bounce", "sma_cross"):
        full = signals(rule, params, closes)
        for cut in (120, 200, 333):
            assert signals(rule, params, closes[:cut]) == full[:cut], rule
    mp = {"fast": 12, "slow": 26, "signal": 9}
    full = signals("macd_cross", mp, closes)
    assert signals("macd_cross", mp, closes[:250]) == full[:250]


def test_daily_backtest_enters_next_open_and_stops_first() -> None:
    closes = _walk(300, 11)
    bars = [{"time": 1_700_000_000 + i * 86400, "open": c * 0.999, "high": c * 1.01, "low": c * 0.99, "close": c,
             "volume": 1_000_000} for i, c in enumerate(closes)]
    cfg = {"symbol": "TEST", "rule": {"type": "breakout_20d", "params": {"lookback": 20}},
           "exit": {"stop_type": "pct", "stop_value": 2, "target_r": 2, "max_hold_bars": 5},
           "filters": {"min_price": 0, "min_avg_volume": 0}}
    out = backtest_daily(Chart("TEST", {}, bars), cfg)
    sig = signals("breakout_20d", {"lookback": 20}, closes)
    by_day = {b["time"]: i for i, b in enumerate(bars)}
    for t in out["trades"]:
        assert t["outcome"] in ("stop", "target", "time")
        assert t["r_multiple"] == -1.0 if t["outcome"] == "stop" else True
        # the entry is the open of the day after a signal
        import datetime as dt
        from zoneinfo import ZoneInfo
        idx = [i for ts, i in by_day.items()
               if dt.datetime.fromtimestamp(ts, ZoneInfo("America/New_York")).date().isoformat() == t["entry_date"]][0]
        assert sig[idx - 1] and math.isclose(t["entry"], round(bars[idx]["open"], 2))


def test_metrics_known_sample() -> None:
    rs = [1, -1, 2, -1, -1, 1, 0.5, -1, 2, 1]
    trades = [{"r_multiple": r, "entry_date": f"2026-0{1 + i // 5}-1{i % 5}"} for i, r in enumerate(rs)]
    s = summarize(trades)
    assert s["trades"] == 10 and s["wins"] == 6 and s["losses"] == 4
    assert s["win_rate"] == 0.6
    assert s["profit_factor"] == round(7.5 / 4, 4)
    assert s["avg_r"] == 0.35 and s["total_r"] == 3.5
    assert s["max_drawdown_r"] == 2.0
    assert s["sample"] == "small"
    few = summarize(trades[:5])
    assert few["sample"] == "insufficient" and few["win_rate"] is None and few["profit_factor"] is None
