"""Display policy: what the API may send to visitors.

Free data plans checked on 2026-10-30 do not allow showing raw prices to anonymous visitors of
a public site. So, in the public lab, prices and bars are inputs to the server's own
calculations, and the API returns signals, metrics and simulation results instead.

The policy is enforced here, in the API. Hiding a field in the interface is not enough.
Defaults: everything visible in the local demo (only the developer's own machine can reach it),
restrictive in the public lab. Each switch can be set explicitly in the environment.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from ..config import get_settings

HIDDEN_MESSAGE = ("Preços e candles brutos não são exibidos neste laboratório público: os planos gratuitos "
                  "dos provedores não autorizam a exibição. Os cálculos do servidor continuam usando esses dados.")

# Price-level and volume fields of a scanner hit or a quote (derived metrics such as RSI,
# percent change and volatility stay).
QUOTE_HIDDEN_FIELDS = ("last", "volume", "avg_volume")
HIT_HIDDEN_FIELDS = ("price", "volume", "or_high", "or_low")


def summary() -> dict:
    s = get_settings()
    return {
        "shared": True,
        "show_raw_prices": s.show_raw_prices,
        "show_trigger_prices": s.show_trigger_prices,
        "pelosi_public": s.dp_pelosi_public,
        # What /api/congress actually answers: always in the local demo, in the public lab only
        # with DP_PELOSI_PUBLIC=true (same rule as services/congress.allowed()).
        "pelosi_shown": (not s.is_public) or s.dp_pelosi_public,
        "allow_unofficial_sources": s.allow_unofficial_sources,
        "mode": s.dp_auth_mode,
        "note": None if s.show_raw_prices else HIDDEN_MESSAGE,
    }


def require_raw_prices() -> None:
    if not get_settings().show_raw_prices:
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "display_policy", "message": HIDDEN_MESSAGE})


def redact_quote(q: dict) -> dict:
    if get_settings().show_raw_prices:
        return q
    return {**{k: (None if k in QUOTE_HIDDEN_FIELDS else v) for k, v in q.items()}, "spark": [], "prices_hidden": True}


def redact_scan_result(result: Any) -> Any:
    if get_settings().show_raw_prices or not isinstance(result, dict) or not isinstance(result.get("hits"), list):
        return result
    hits = [{k: (None if k in HIT_HIDDEN_FIELDS else v) for k, v in h.items()} if isinstance(h, dict) else h
            for h in result["hits"]]
    return {**result, "hits": hits, "prices_hidden": True}
