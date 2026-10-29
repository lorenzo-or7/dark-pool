"""Statistics on a list of simulated trades (R multiples). Pure functions."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence

MIN_CONCLUSIVE = 30   # below this, metrics are shown as inconclusive
MIN_SHOWN = 10        # below this, rate metrics are withheld


def summarize(trades: Sequence[dict]) -> dict:
    """trades: dicts with r_multiple and entry_date (YYYY-MM-DD), oldest first or not."""
    ts = sorted(trades, key=lambda t: (t["entry_date"], t.get("entry_time") or ""))
    rs = [float(t["r_multiple"]) for t in ts]
    n = len(rs)
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gross_win, gross_loss = sum(wins), -sum(losses)
    equity, peak, max_dd, cum = [], 0.0, 0.0, 0.0
    for t, r in zip(ts, rs, strict=True):
        cum += r
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
        equity.append({"date": t["entry_date"], "cum_r": round(cum, 3)})
    by_month: dict[str, list[float]] = defaultdict(list)
    for t, r in zip(ts, rs, strict=True):
        by_month[t["entry_date"][:7]].append(r)
    months = [{"month": m, "trades": len(v), "sum_r": round(sum(v), 3), "avg_r": round(sum(v) / len(v), 3)}
              for m, v in sorted(by_month.items())]
    avg = sum(rs) / n if n else None
    sd = math.sqrt(sum((r - avg) ** 2 for r in rs) / (n - 1)) if n > 1 and avg is not None else None
    sample = "none" if n == 0 else "insufficient" if n < MIN_SHOWN else "small" if n < MIN_CONCLUSIVE else "ok"
    withhold = n < MIN_SHOWN
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "flat": n - len(wins) - len(losses),
        "win_rate": None if withhold else round(len(wins) / n, 4),
        "win_rate_ci95": None if withhold else wilson(len(wins), n),
        "avg_r": None if n == 0 else round(avg, 4),
        "expectancy_r": None if withhold else round(avg, 4),
        "std_r": None if sd is None else round(sd, 4),
        "std_error_r": None if sd is None else round(sd / math.sqrt(n), 4),
        "avg_win_r": round(gross_win / len(wins), 4) if wins else None,
        "avg_loss_r": round(-gross_loss / len(losses), 4) if losses else None,
        "payoff_ratio": round((gross_win / len(wins)) / (gross_loss / len(losses)), 4) if wins and losses else None,
        "profit_factor": None if withhold or gross_loss == 0 else round(gross_win / gross_loss, 4),
        "total_r": round(sum(rs), 3),
        "max_drawdown_r": round(max_dd, 3),
        "equity": equity,
        "distribution": histogram(rs),
        "by_month": months,
        "positive_months": sum(1 for m in months if m["sum_r"] > 0),
        "sample": sample,
        "sample_note": {
            "none": "Nenhuma operação simulada.",
            "insufficient": f"Apenas {n} operações: taxas não são exibidas (mínimo {MIN_SHOWN}).",
            "small": f"{n} operações: amostra pequena, resultados inconclusivos (referência: {MIN_CONCLUSIVE}+).",
            "ok": f"{n} operações.",
        }[sample],
    }


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    """95 % Wilson interval for a proportion: how uncertain a win rate is at this sample size."""
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def histogram(rs: Sequence[float], lo: float = -1.5, hi: float = 4.0, step: float = 0.5) -> list[dict]:
    edges = []
    x = lo
    while x < hi - 1e-9:
        edges.append(round(x, 2))
        x += step
    bins = [{"from": e, "to": round(e + step, 2), "count": 0} for e in edges]
    for r in rs:
        idx = min(max(int((r - lo) // step), 0), len(bins) - 1)
        bins[idx]["count"] += 1
    return bins
