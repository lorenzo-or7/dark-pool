"""The plan day's 5-minute bars for trader-entry and trader-exit (Bloco 4).

Entry finds the opening-range breakout and Exit sets the stop (opening range, percent or
`atr:K` = K x the 14-bar ATR of the session up to the entry bar). Both read only the plan day's
own regular session, so this module downloads just that day, from the provider chosen for new
5-minute bars (DP_INTRADAY_PROVIDER, the same one the Time Machine uses). No silent switch: if
that provider is off or fails, the plan fails with its reason.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from . import alpaca
from . import market_calendar as mcal
from . import market_data as md
from . import providers


class DayBarsError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DayBars:
    text: str              # the chart document, exactly as it will be frozen (hash = SHA-256 of it)
    fetched_at: dt.datetime
    source: str            # snapshot source: alpaca:sip, alpaca:iex or yahoo
    range: str             # snapshot range label (String(8)): "1sess", "1d", "5d", "60d"
    quality: dict | None   # session coverage of an Alpaca document; None for Yahoo


def yahoo_range(day: dt.date, today: dt.date) -> str:
    """The shortest Yahoo 5-minute range that still holds `day` (the same idea as trader-exit's
    own loader; Yahoo keeps about 60 days of 5-minute bars)."""
    back = (today - day).days
    if back <= 0:
        return "1d"
    if back <= 6:
        return "5d"
    if back <= 58:
        return "60d"
    raise DayBarsError("out_of_range", "O Yahoo guarda cerca de 60 dias de candles de 5 minutos: escolha uma data "
                                       "mais recente ou configure a Alpaca.")


def fetch(symbol: str, day: dt.date, now_utc: dt.datetime | None = None) -> DayBars:
    pid = providers.bars_provider("5m")
    if pid == alpaca.PROVIDER_ID:
        try:
            text, fetched, quality = alpaca.fetch_day_chart(symbol, day, now_utc)
        except alpaca.AlpacaError as e:
            raise DayBarsError(e.code, e.message)
        return DayBars(text, fetched, alpaca.source(quality["feed"]), "1sess", quality)
    now = now_utc or dt.datetime.now(dt.UTC)
    rng = yahoo_range(day, now.astimezone(mcal.NY).date())
    try:
        text, fetched, _ = md.fetch_chart_raw(symbol, rng, "5m", use_cache=False)
    except md.DataError as e:
        raise DayBarsError(e.code, e.message)
    return DayBars(text, fetched, md.PROVIDER_ID, rng, None)
