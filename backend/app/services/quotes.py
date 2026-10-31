"""Quotes for trader-alerts (Bloco 5): many symbols per request, from the configured provider.

- Alpaca (DP_QUOTE_PROVIDER=auto with keys, or alpaca): GET /v2/stocks/snapshots, all symbols in
  one request (up to 100), feed DP_ALPACA_QUOTE_FEED = delayed_sip (consolidated, 15 min late) or
  iex (real time, one exchange).
- Yahoo (no keys, or yahoo): one chart request per symbol through the shared quota of
  market_data.fetch_chart_raw, read by trader-alerts' own parse_yahoo.
- Stooq, the engine's second source, is not used: its endpoint answered 404 when the skill was
  written and it is not a documented API. The engine is not edited.
No silent switch: if the chosen provider fails, the check fails with its reason.
"""

from __future__ import annotations

from ..engines.runner import load_module
from . import alpaca
from . import market_data as md
from . import providers


class QuoteError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def fetch(symbols: list[str]) -> tuple[dict[str, dict], list[dict], dict]:
    """-> ({SYM: quote in trader-alerts' shape}, [errors per symbol], meta about the source)."""
    pid = providers.quote_provider()
    if not symbols:
        return {}, [], {"provider": pid, "feed": None, "requests": 0}
    if pid == alpaca.PROVIDER_ID:
        try:
            quotes, errors = alpaca.fetch_snapshots(symbols)
        except alpaca.AlpacaError as e:
            raise QuoteError(e.code, e.message)
        feed = alpaca.quote_feed()
        return quotes, errors, {"provider": pid, "feed": feed, "delayed": feed == "delayed_sip",
                                "requests": -(-len(symbols) // alpaca.SNAPSHOT_CHUNK)}
    al = load_module("alerts")
    quotes, errors = {}, []
    for sym in symbols:
        try:
            text, _, _ = md.fetch_chart_raw(sym, "1d", "5m")
        except md.DataError as e:
            if e.code in ("source_disabled", "provider_paused", "quota_exhausted", "rate_limited"):
                raise QuoteError(e.code, e.message)
            errors.append({"symbol": sym, "code": e.code, "message": e.message})
            continue
        try:
            quotes[sym] = al.parse_yahoo(text, sym)
        except al.AlertError as e:
            errors.append({"symbol": sym, "code": "no_data", "message": str(e)})
    return quotes, errors, {"provider": pid, "feed": None, "delayed": True, "requests": len(symbols)}
