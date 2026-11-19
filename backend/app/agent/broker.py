"""The Alpaca paper Trading API, only the calls the agent needs.

Documentation used (checked 2026-11-18):
- https://docs.alpaca.markets/docs/paper-trading (paper base URL; paper keys differ from live keys)
- https://docs.alpaca.markets/us/reference/postorder.md (POST /v2/orders; qty and prices as strings;
  client_order_id up to 128 chars; 403 = not enough buying power, 422 = invalid input)
- https://docs.alpaca.markets/docs/orders-at-alpaca (bracket: take_profit.limit_price and
  stop_loss.stop_price both required; time_in_force day or gtc; no extended hours)
- https://docs.alpaca.markets/us/reference/getaccount-1.md (GET /v2/account; money as strings)
- https://docs.alpaca.markets/us/reference/getallorders-1.md (GET /v2/orders; status, after, limit)
- https://docs.alpaca.markets/us/reference/deleteallopenpositions-1.md (DELETE /v2/positions?cancel_orders=true -> 207)
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import httpx

from .settings import AgentSettings

# Paper only. There is deliberately no setting that changes this address.
PAPER_URL = "https://paper-api.alpaca.markets"


class BrokerError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def cents(x: float | Decimal) -> str:
    """A price as Alpaca wants it for stocks of $1 or more: a string with two decimals."""
    return str(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class PaperBroker:
    def __init__(self, settings: AgentSettings):
        if not settings.paper_keys_set:
            raise BrokerError("missing_key", "Configure ALPACA_PAPER_KEY_ID e ALPACA_PAPER_SECRET_KEY "
                                             "(chaves da conta paper da Alpaca).")
        self._key = settings.alpaca_paper_key_id
        self._secret = settings.alpaca_paper_secret_key

    def scrub(self, text: str) -> str:
        for secret in (self._key, self._secret):
            if secret and len(secret) >= 4:
                text = text.replace(secret, "[oculto]")
        return text

    def _send(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> httpx.Response:
        """The only network call. Tests replace it."""
        headers = {"APCA-API-KEY-ID": self._key, "APCA-API-SECRET-KEY": self._secret, "Accept": "application/json"}
        return httpx.request(method, PAPER_URL + path, params=params, json=body, headers=headers, timeout=20)

    def _call(self, method: str, path: str, params: dict | None = None, body: dict | None = None,
              ok: tuple[int, ...] = (200,)) -> object:
        try:
            r = self._send(method, path, params, body)
        except httpx.HTTPError as e:
            raise BrokerError("broker_unreachable", f"Não foi possível acessar a Alpaca paper ({type(e).__name__}).")
        if r.status_code in ok:
            try:
                return r.json() if r.content else None
            except ValueError:
                raise BrokerError("bad_payload", "A Alpaca paper devolveu um formato inesperado.")
        try:
            detail = str((r.json() or {}).get("message", ""))[:200]
        except (ValueError, AttributeError):
            detail = ""
        code = {401: "broker_auth", 403: "broker_refused", 422: "broker_invalid", 429: "rate_limited"}.get(
            r.status_code, "broker_error")
        raise BrokerError(code, self.scrub(f"Alpaca paper: HTTP {r.status_code} {detail}".strip()))

    def account(self) -> dict:
        return self._call("GET", "/v2/account")  # type: ignore[return-value]

    def orders_since(self, after_iso: str) -> list[dict]:
        out = self._call("GET", "/v2/orders", params={"status": "all", "after": after_iso, "limit": 500})
        return out if isinstance(out, list) else []

    def bracket_buy(self, symbol: str, qty: int, limit_price: float, take_profit: float, stop_price: float,
                    client_order_id: str) -> dict:
        body = {"symbol": symbol, "qty": str(int(qty)), "side": "buy", "type": "limit",
                "limit_price": cents(limit_price), "time_in_force": "day", "order_class": "bracket",
                "take_profit": {"limit_price": cents(take_profit)}, "stop_loss": {"stop_price": cents(stop_price)},
                "client_order_id": client_order_id[:128]}
        return self._call("POST", "/v2/orders", body=body)  # type: ignore[return-value]

    def close_all(self) -> list:
        out = self._call("DELETE", "/v2/positions", params={"cancel_orders": "true"}, ok=(200, 207))
        return out if isinstance(out, list) else []
