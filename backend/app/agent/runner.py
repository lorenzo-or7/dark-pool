"""One check of the paper-trading agent (`tick`), run every few seconds by scripts/paper_agent.py.

Each tick, on an NYSE session day:
1. Kill switch (file <DP_DATA_DIR>/agent/STOP) or the flatten time (close minus N minutes):
   cancel every open order and close every position, once a day. No new entries after that.
2. Account blocked, or the day's loss (equity - last_equity) at the limit: close everything and stop
   for the day.
3. For each watched symbol not yet traded today: today's ORB signal from real-time IEX bars. A fresh
   trigger (closed at most N minutes ago) becomes ONE bracket order: limit buy at the trigger price
   plus a small tolerance, stop and target from the lab's plan, size from the risk per trade and the
   largest position. Each symbol trades at most once a day; at most N trades a day.

Every decision goes to <DP_DATA_DIR>/agent/journal-YYYY-MM-DD.jsonl, and the day's state to
state-YYYY-MM-DD.json, so a restart neither forgets nor repeats an order (the broker's own order
list, by client_order_id, is read back too).
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
from collections.abc import Callable
from pathlib import Path

from ..services import alpaca
from ..services import market_calendar as mcal
from .broker import BrokerError, PaperBroker
from .settings import AgentSettings
from .signals import Signal, today_signal, trigger_time_utc

CID_PREFIX = "dp-orb-"


class AgentConfigError(Exception):
    pass


def client_order_id(day: dt.date, symbol: str) -> str:
    return f"{CID_PREFIX}{day.isoformat()}-{symbol}"


def size_order(entry: float, stop: float, target: float, s: AgentSettings) -> dict:
    """-> {qty, limit, risk_per_share, notional, risk_usd} or {skip: reason}. Worst case: the fill at the
    limit price, so the risk per share is measured from the limit, not from the trigger price."""
    if entry < 1:
        return {"skip": "Preço abaixo de US$ 1 (regras de centavos diferentes); fora do agente."}
    if stop >= entry - 0.01:
        return {"skip": "Stop colado no preço de entrada."}
    limit = round(entry + (entry - stop) * s.dp_agent_max_entry_slippage_r, 2)
    if target <= limit + 0.01:
        return {"skip": "Alvo abaixo do preço-limite de entrada com a tolerância."}
    rps = limit - stop
    qty = math.floor(min(s.dp_agent_risk_per_trade_usd / rps, s.dp_agent_max_position_usd / limit))
    if qty < 1:
        return {"skip": f"Risco por ação (US$ {rps:.2f}) ou preço maior que os limites configurados."}
    return {"qty": qty, "limit": limit, "risk_per_share": round(rps, 4), "notional": round(qty * limit, 2),
            "risk_usd": round(qty * rps, 2)}


class Agent:
    def __init__(self, settings: AgentSettings, data_dir: Path, broker: PaperBroker | None = None,
                 signal_fn: Callable[[str, dt.date, dt.datetime, AgentSettings], Signal] = today_signal):
        if settings.dp_agent_mode == "off":
            raise AgentConfigError("DP_AGENT_MODE=off: o agente está desligado.")
        if not settings.symbols:
            raise AgentConfigError("Defina DP_AGENT_SYMBOLS (por exemplo SPY,QQQ,AAPL).")
        self.s = settings
        self.dir = Path(data_dir) / "agent"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.paper = settings.dp_agent_mode == "paper"
        self.broker = broker if broker is not None else (PaperBroker(settings) if self.paper else None)
        self.signal_fn = signal_fn

    # ------------------------------------------------------------ files

    @property
    def stop_file(self) -> Path:
        return self.dir / "STOP"

    def _state_path(self, day: dt.date) -> Path:
        return self.dir / f"state-{day.isoformat()}.json"

    def load_state(self, day: dt.date) -> dict:
        try:
            st = json.loads(self._state_path(day).read_text(encoding="utf-8"))
            if isinstance(st, dict):
                st.setdefault("traded", {})
                st.setdefault("done", {})
                st.setdefault("checked", {})
                return st
        except (OSError, ValueError):
            pass
        return {"day": day.isoformat(), "mode": self.s.dp_agent_mode, "traded": {}, "done": {}, "checked": {},
                "flattened": False, "halted": None}

    def _save(self, day: dt.date, st: dict) -> None:
        p = self._state_path(day)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)

    def journal(self, day: dt.date, now: dt.datetime, event: str, **data: object) -> dict:
        row = {"ts": now.astimezone(mcal.NY).strftime("%Y-%m-%d %H:%M:%S ET"), "event": event,
               "mode": self.s.dp_agent_mode, **data}
        text = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
        if self.broker is not None:
            text = self.broker.scrub(text)
        with (self.dir / f"journal-{day.isoformat()}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(text + "\n")
        return row

    # ------------------------------------------------------------ actions

    def _flatten(self, day: dt.date, now: dt.datetime, st: dict, reason: str) -> dict:
        if not self.paper:
            st["flattened"] = True
            return self.journal(day, now, "flatten_skipped_dry_run", reason=reason)
        try:
            res = self.broker.close_all()  # type: ignore[union-attr]
        except BrokerError as e:
            return self.journal(day, now, "flatten_failed", reason=reason, code=e.code, error=e.message)
        st["flattened"] = True
        closed = [{"symbol": r.get("symbol"), "status": r.get("status")} for r in res if isinstance(r, dict)]
        return self.journal(day, now, "flatten", reason=reason, positions=closed)

    def tick(self, now_utc: dt.datetime | None = None) -> dict:
        now = (now_utc or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
        day = now.astimezone(mcal.NY).date()
        info = mcal.day(day)
        if not info.is_session:
            return {"action": "idle", "reason": info.reason or "Sem pregão."}
        open_utc, close_utc = alpaca._open_close(day)
        if now < open_utc:
            return {"action": "idle", "reason": "Antes da abertura."}
        st = self.load_state(day)
        try:
            return self._tick_session(day, now, open_utc, close_utc, st)
        finally:
            self._save(day, st)

    def _tick_session(self, day: dt.date, now: dt.datetime, open_utc: dt.datetime, close_utc: dt.datetime,
                      st: dict) -> dict:
        s = self.s
        flatten_at = close_utc - dt.timedelta(minutes=s.dp_agent_flatten_minutes_before_close)
        if self.stop_file.exists():
            if not st["flattened"]:
                return {"action": "flatten", **self._flatten(day, now, st, "kill_switch")}
            return {"action": "idle", "reason": "Kill switch ligado (arquivo STOP)."}
        if now >= flatten_at:
            if not st["flattened"]:
                if now >= close_utc:
                    self.journal(day, now, "late_flatten", note="Pregão já encerrado; a ordem fica para a abertura.")
                return {"action": "flatten", **self._flatten(day, now, st, "end_of_day")}
            return {"action": "idle", "reason": "Dia encerrado para o agente."}
        if st.get("halted"):
            return {"action": "idle", "reason": st["halted"]}

        if self.paper:
            try:
                acct = self.broker.account()  # type: ignore[union-attr]
            except BrokerError as e:
                self.journal(day, now, "broker_error", step="account", code=e.code, error=e.message)
                return {"action": "error", "reason": e.message}
            if acct.get("trading_blocked") or acct.get("account_blocked") or acct.get("status") != "ACTIVE":
                st["halted"] = "Conta paper bloqueada ou inativa."
                self.journal(day, now, "halt", reason=st["halted"], status=acct.get("status"))
                return {"action": "halt", "reason": st["halted"]}
            try:
                pnl = float(acct.get("equity")) - float(acct.get("last_equity"))
            except (TypeError, ValueError):
                pnl = 0.0
            if pnl <= -s.dp_agent_max_daily_loss_usd:
                st["halted"] = f"Perda do dia (US$ {pnl:.2f}) atingiu o limite de US$ {s.dp_agent_max_daily_loss_usd:.2f}."
                self.journal(day, now, "halt", reason=st["halted"], pnl=round(pnl, 2))
                self._flatten(day, now, st, "daily_loss_limit")
                return {"action": "halt", "reason": st["halted"]}
            try:
                orders = self.broker.orders_since(open_utc.strftime("%Y-%m-%dT%H:%M:%SZ"))  # type: ignore[union-attr]
            except BrokerError as e:
                self.journal(day, now, "broker_error", step="orders", code=e.code, error=e.message)
                return {"action": "error", "reason": e.message}
            prefix = f"{CID_PREFIX}{day.isoformat()}-"
            for o in orders:
                cid = str(o.get("client_order_id") or "")
                if cid.startswith(prefix):
                    st["traded"].setdefault(cid[len(prefix):], {"order_id": o.get("id"), "status": o.get("status"),
                                                                 "from": "broker"})

        sent: list[str] = []
        for sym in s.symbols:
            if sym in st["traded"] or sym in st["done"]:
                continue
            if len(st["traded"]) >= s.dp_agent_max_trades_per_day:
                if not st.get("max_trades_logged"):
                    st["max_trades_logged"] = True
                    self.journal(day, now, "max_trades_reached", limit=s.dp_agent_max_trades_per_day)
                break
            end_iso = alpaca._floor5(now).isoformat()
            if st["checked"].get(sym) == end_iso:
                continue  # no new closed bar since the last look
            sig = self.signal_fn(sym, day, now, s)
            st["checked"][sym] = end_iso
            if sig.status in ("expired", "refused"):
                st["done"][sym] = sig.status
                self.journal(day, now, "no_trade", symbol=sym, status=sig.status, reason=sig.reason)
                continue
            if sig.status != "triggered" or not sig.plan:
                continue
            p = sig.plan
            age = now - trigger_time_utc(day, p["entry_time"])
            if age > dt.timedelta(minutes=s.dp_agent_max_signal_age_min):
                st["done"][sym] = "stale"
                self.journal(day, now, "skip_stale", symbol=sym, trigger_time=p["entry_time"],
                             age_min=round(age.total_seconds() / 60, 1), max_age_min=s.dp_agent_max_signal_age_min)
                continue
            size = size_order(p["entry"], p["stop"], p["target"], s)
            if "skip" in size:
                st["done"][sym] = "skip"
                self.journal(day, now, "skip_size", symbol=sym, reason=size["skip"], plan=p)
                continue
            cid = client_order_id(day, sym)
            order = {"symbol": sym, "qty": size["qty"], "limit_price": size["limit"], "take_profit": p["target"],
                     "stop_price": p["stop"], "client_order_id": cid}
            if not self.paper:
                st["traded"][sym] = {"dry_run": True, **order}
                self.journal(day, now, "would_send", order=order, plan=p, sizing=size)
                sent.append(sym)
                continue
            try:
                res = self.broker.bracket_buy(sym, size["qty"], size["limit"], p["target"], p["stop"], cid)  # type: ignore[union-attr]
            except BrokerError as e:
                st["done"][sym] = "order_failed"
                self.journal(day, now, "order_failed", order=order, code=e.code, error=e.message)
                continue
            st["traded"][sym] = {"order_id": res.get("id"), "status": res.get("status"), **order}
            self.journal(day, now, "order_sent", order=order, order_id=res.get("id"), status=res.get("status"),
                         plan=p, sizing=size)
            sent.append(sym)
        return {"action": "orders" if sent else "watch", "sent": sent, "traded_today": sorted(st["traded"]),
                "done": st["done"]}
