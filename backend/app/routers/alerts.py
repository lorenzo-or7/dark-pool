"""Price and clock alerts (trader-alerts), checked on demand (Bloco 5).

The visitor's rules and their "already rang" state live in the browser and come with each check:
the lab runs nothing periodically and sends nothing outside (no e-mail, push or webhook). The
server fetches the quotes (services/quotes.py), runs trader-alerts' own pure `evaluate` and
returns what rang plus the new state. With DP_SHOW_RAW_PRICES off (the public lab) prices are
removed from the messages and the quotes; the comparison itself still uses them on the server.
"""

from __future__ import annotations

import datetime as dt
import re

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser, current_user
from ..config import get_settings
from ..engines.runner import load_module
from ..schemas import AlertCheckRequest
from ..services import price_view as pv
from ..services import providers
from ..services import quotes as qsvc
from .common import bad_request

router = APIRouter(prefix="/api", tags=["alerts"])

PROVIDER_DOWN = {"source_disabled", "missing_key", "provider_paused", "quota_exhausted", "rate_limited",
                 "not_integrated", "needs_config"}
BROKER_HINT = re.compile(r"\s*If \S+ is still open, close it: trader-broker.*$")


def _now() -> dt.datetime:
    """Naive UTC, as the engines use (tests replace it)."""
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


@router.post("/alerts/check")
def check_alerts(body: AlertCheckRequest, user: CurrentUser = Depends(current_user)) -> dict:  # noqa: ARG001
    al = load_module("alerts")
    rules = [r.model_dump(exclude_none=True) for r in body.rules]
    for r in rules:
        try:
            al.validate(r)
        except al.AlertError as e:
            raise bad_request(str(e), "invalid_rule")
    now = _now()
    status = al.market_status(now)
    today = status["date"]
    symbols = sorted({str(r["symbol"]).upper() for r in rules
                      if r.get("symbol") and r["type"] not in al.NO_QUOTE and al.active(r, today)})
    try:
        quotes, errors, meta = qsvc.fetch(symbols)
    except qsvc.QuoteError as e:
        code = 503 if e.code in PROVIDER_DOWN else 502
        raise HTTPException(code, {"code": e.code, "message": e.message})
    rings, state = al.evaluate(rules, quotes, status, body.state.model_dump(), now)
    show = get_settings().show_raw_prices
    out_rings = []
    for ring in rings:
        msg = BROKER_HINT.sub("", ring["message"])   # the lab has no broker: drop the engine's trader-broker hint
        if not show:
            msg = pv.PRICE_TEXT.sub("[preço oculto]", msg)
        out_rings.append({**ring, "message": msg})
    out_quotes = {}
    for sym, q in quotes.items():
        prev = q.get("prev_close")
        chg = round(100.0 * (q["price"] / float(prev) - 1), 3) if prev else None
        out_quotes[sym] = ({"price": q["price"], "prev_close": prev, "time": q.get("time"), "change_pct": chg}
                           if show else {"time": q.get("time"), "change_pct": chg, "prices_hidden": True})
    return {
        "rings": out_rings, "state": state, "market": {k: status.get(k) for k in
                                                        ("now_new_york", "date", "open", "reason", "opens", "closes",
                                                         "early_close", "next_open", "calendar_known")},
        "quotes": out_quotes, "errors": errors,
        "source": {**meta, "provenance": providers.provenance_for_source(
            f"alpaca:{meta['feed']}" if meta["provider"] == "alpaca" else meta["provider"])},
        "prices_hidden": not show,
        "note": "Verificação sob demanda: o laboratório não verifica sozinho nem envia alertas para fora.",
    }
