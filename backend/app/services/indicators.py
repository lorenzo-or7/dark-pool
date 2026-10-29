"""Technical indicators on a list of floats. Each output is aligned with the
input; a value is None until there is enough history (no look-ahead)."""

from __future__ import annotations

from collections.abc import Sequence

Series = list[float | None]


def sma(xs: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(xs)
    s = 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(xs: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(xs)
    if len(xs) < n:
        return out
    k = 2 / (n + 1)
    prev = sum(xs[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(xs)):
        prev = xs[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(xs: Sequence[float], n: int = 14) -> Series:
    """Wilder's RSI, the same smoothing trader-scanner uses."""
    out: Series = [None] * len(xs)
    if len(xs) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = xs[i] - xs[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(xs)):
        d = xs[i] - xs[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def macd(xs: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[Series, Series, Series]:
    ef, es = ema(xs, fast), ema(xs, slow)
    line: Series = [None if a is None or b is None else a - b for a, b in zip(ef, es, strict=True)]
    start = next((i for i, v in enumerate(line) if v is not None), None)
    sig: Series = [None] * len(xs)
    if start is not None:
        tail = ema([v for v in line[start:] if v is not None], signal)
        for j, v in enumerate(tail):
            sig[start + j] = v
    hist: Series = [None if a is None or b is None else a - b for a, b in zip(line, sig, strict=True)]
    return line, sig, hist


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], n: int = 14) -> Series:
    out: Series = [None] * len(closes)
    trs = []
    for i in range(len(closes)):
        if i == 0:
            trs.append(highs[0] - lows[0])
        else:
            pc = closes[i - 1]
            trs.append(max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc)))
    if len(trs) < n:
        return out
    a = sum(trs[:n]) / n
    out[n - 1] = a
    for i in range(n, len(trs)):
        a = (a * (n - 1) + trs[i]) / n
        out[i] = a
    return out


def r4(x: float | None) -> float | None:
    return None if x is None else round(x, 4)
