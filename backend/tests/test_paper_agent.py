"""Bloco 11: the paper-trading agent. No network: market data is the DERIVED TSLA fixture of
tests/alpaca_fixtures.py (2026-10-19, the skill's reference day) behind a fake Alpaca, and the
paper broker is a fake that records what would be sent. Nothing here proves how the real Alpaca
paper API behaves; that needs the user's paper keys.

Reference (tests/test_plan_orb.py): range 354.47-362.18, the 10:10 bar closes 364.18 -> entry at
10:15 ET; or-mid stop 358.32, 1R target 370.04.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx
import pytest

from . import alpaca_fixtures as fx
from .conftest import _reset

DATA_KEY = "PKDATASENTINEL0000000000"
DATA_SECRET = "DATASECRETSENTINELneverShow00000000000000"
PAPER_KEY = "PKPAPERSENTINEL000000000"
PAPER_SECRET = "PAPERSECRETSENTINELneverShow0000000000000"
DAY = dt.date(2026, 10, 19)
AT_1016 = fx.edt("2026-10-19", "10:16")


class FakeBroker:
    """Stand-in for PaperBroker: same methods, records the calls."""

    def __init__(self, equity: float = 100_000.0, last_equity: float = 100_000.0, status: str = "ACTIVE",
                 orders: list[dict] | None = None, refuse: str | None = None):
        self.acct = {"status": status, "equity": str(equity), "last_equity": str(last_equity),
                     "trading_blocked": False, "account_blocked": False}
        self.orders = orders or []
        self.refuse = refuse
        self.sent: list[dict] = []
        self.closed = 0

    def scrub(self, text: str) -> str:
        return text.replace(PAPER_KEY, "[oculto]").replace(PAPER_SECRET, "[oculto]")

    def account(self) -> dict:
        return self.acct

    def orders_since(self, after_iso: str) -> list[dict]:
        return list(self.orders)

    def bracket_buy(self, symbol, qty, limit_price, take_profit, stop_price, client_order_id):  # noqa: ANN001, ANN201
        from app.agent.broker import BrokerError
        if self.refuse:
            raise BrokerError("broker_refused", self.refuse)
        o = {"symbol": symbol, "qty": qty, "limit_price": limit_price, "take_profit": take_profit,
             "stop_price": stop_price, "client_order_id": client_order_id}
        self.sent.append(o)
        self.orders.append({"id": f"ord-{len(self.sent)}", "client_order_id": client_order_id, "status": "new"})
        return {"id": f"ord-{len(self.sent)}", "status": "new"}

    def close_all(self) -> list:
        self.closed += 1
        return [{"symbol": "TSLA", "status": 200}]


@pytest.fixture()
def env(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ALPACA_API_KEY_ID", DATA_KEY)
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", DATA_SECRET)
    monkeypatch.setenv("ALPACA_PAPER_KEY_ID", PAPER_KEY)
    monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", PAPER_SECRET)
    monkeypatch.setenv("DP_AGENT_SYMBOLS", "TSLA")
    monkeypatch.setenv("DP_AGENT_MODE", "dry_run")
    for k in ("DP_AGENT_RISK_PER_TRADE_USD", "DP_AGENT_MAX_POSITION_USD", "DP_AGENT_MAX_TRADES_PER_DAY",
              "DP_AGENT_MAX_DAILY_LOSS_USD", "DP_AGENT_MAX_SIGNAL_AGE_MIN", "DP_AGENT_MAX_ENTRY_SLIPPAGE_R",
              "DP_AGENT_STOP_RULE", "DP_AGENT_TARGET_R", "DP_AGENT_OR_MINUTES"):
        monkeypatch.delenv(k, raising=False)
    from app.services import alpaca
    fake = fx.FakeAlpaca(fx.derived_bars())
    monkeypatch.setattr(alpaca, "_http_get", fake)
    _reset()
    return settings_env


def _agent(monkeypatch: pytest.MonkeyPatch, mode: str = "dry_run", broker: FakeBroker | None = None, **env: str):
    monkeypatch.setenv("DP_AGENT_MODE", mode)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app.agent import settings as ags
    from app.agent.runner import Agent
    from app.config import get_settings
    ags.get_agent_settings.cache_clear()
    get_settings.cache_clear()
    return Agent(ags.get_agent_settings(), get_settings().dp_data_dir, broker=broker)


def _journal(agent, day: dt.date = DAY) -> list[dict]:  # noqa: ANN001
    p = agent.dir / f"journal-{day.isoformat()}.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


# ---------------------------------------------------------------- configuration

def test_off_by_default_and_needs_symbols(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent import settings as ags
    from app.agent.runner import Agent, AgentConfigError
    for k in ("DP_AGENT_MODE", "DP_AGENT_SYMBOLS"):
        monkeypatch.setenv(k, "")
    ags.get_agent_settings.cache_clear()
    s = ags.get_agent_settings()
    assert s.dp_agent_mode == "off"
    with pytest.raises(AgentConfigError):
        Agent(s, settings_env)
    monkeypatch.setenv("DP_AGENT_MODE", "dry_run")
    ags.get_agent_settings.cache_clear()
    with pytest.raises(AgentConfigError, match="DP_AGENT_SYMBOLS"):
        Agent(ags.get_agent_settings(), settings_env)
    monkeypatch.setenv("DP_AGENT_SYMBOLS", " spy, qqq;SPY ,")
    ags.get_agent_settings.cache_clear()
    assert ags.get_agent_settings().symbols == ["SPY", "QQQ"]


def test_paper_only_endpoint_and_no_setting_to_change_it() -> None:
    from app.agent import broker
    from app.agent.settings import AgentSettings
    assert broker.PAPER_URL == "https://paper-api.alpaca.markets"
    assert not any("url" in f or "base" in f for f in AgentSettings.model_fields)


def test_the_web_app_never_imports_the_agent() -> None:
    app_dir = Path(__file__).resolve().parents[1] / "app"
    for p in app_dir.rglob("*.py"):
        if "agent" in p.relative_to(app_dir).parts:
            continue
        assert "app.agent" not in p.read_text(encoding="utf-8") and "from .agent" not in p.read_text(encoding="utf-8"), p


# ---------------------------------------------------------------- sizing

def test_sizing_uses_the_limit_price_and_both_caps(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent.runner import size_order
    from app.agent.settings import AgentSettings
    s = AgentSettings(dp_agent_risk_per_trade_usd=50, dp_agent_max_position_usd=2000,
                      dp_agent_max_entry_slippage_r=0.1)
    z = size_order(364.18, 358.32, 370.04, s)
    # R = 5.86 -> limit 364.18 + 0.586 = 364.77; risk/share 6.45 -> 7 by risk, 5 by the US$ 2,000 cap
    assert z == {"qty": 5, "limit": 364.77, "risk_per_share": 6.45, "notional": 1823.85, "risk_usd": 32.25}
    s2 = AgentSettings(dp_agent_risk_per_trade_usd=50, dp_agent_max_position_usd=100_000)
    assert size_order(364.18, 358.32, 370.04, s2)["qty"] == 7
    assert "skip" in size_order(364.18, 358.32, 364.50, s)          # target inside the tolerance
    assert "skip" in size_order(0.95, 0.90, 1.10, s)                 # sub-dollar
    assert "skip" in size_order(364.18, 358.32, 370.04, AgentSettings(dp_agent_max_position_usd=100))


# ---------------------------------------------------------------- dry run on the reference day

def test_dry_run_logs_the_order_it_would_send(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import alpaca
    agent = _agent(monkeypatch)
    res = agent.tick(AT_1016)
    assert res["action"] == "orders" and res["sent"] == ["TSLA"]
    rows = _journal(agent)
    assert [r["event"] for r in rows] == ["would_send"]
    o = rows[0]["order"]
    assert o == {"symbol": "TSLA", "qty": 5, "limit_price": 364.77, "take_profit": 370.04, "stop_price": 358.32,
                 "client_order_id": "dp-orb-2026-10-19-TSLA"}
    assert rows[0]["plan"]["entry_time"] == "10:15"
    q = alpaca._http_get.calls[-1]
    # real-time IEX, the plan day only, up to the last closed bar (10:15)
    assert (q["feed"], q["start"], q["end"]) == ("iex", "2026-10-19T13:30:00Z", "2026-10-19T14:14:59Z")
    # the next tick neither repeats the order nor downloads again
    calls = len(alpaca._http_get.calls)
    assert agent.tick(AT_1016 + dt.timedelta(seconds=30))["sent"] == []
    assert len(alpaca._http_get.calls) == calls and len(_journal(agent)) == 1


def test_before_the_range_is_complete_it_waits(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _agent(monkeypatch)
    res = agent.tick(fx.edt("2026-10-19", "09:41"))
    assert res["action"] == "watch" and _journal(agent) == []


def test_a_stale_trigger_is_skipped(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _agent(monkeypatch)
    res = agent.tick(fx.edt("2026-10-19", "10:51"))   # the trigger closed at 10:15
    assert res["sent"] == [] and res["done"] == {"TSLA": "stale"}
    assert [r["event"] for r in _journal(agent)] == ["skip_stale"]


def test_weekend_and_before_open_do_nothing(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import alpaca
    agent = _agent(monkeypatch)
    assert agent.tick(fx.edt("2026-10-18", "11:00"))["action"] == "idle"
    assert agent.tick(fx.edt("2026-10-19", "09:00"))["action"] == "idle"
    assert alpaca._http_get.calls == []


# ---------------------------------------------------------------- paper mode

def test_paper_sends_one_bracket_order_and_survives_a_restart(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = FakeBroker()
    agent = _agent(monkeypatch, "paper", b)
    res = agent.tick(AT_1016)
    assert res["sent"] == ["TSLA"] and len(b.sent) == 1
    assert b.sent[0]["client_order_id"] == "dp-orb-2026-10-19-TSLA" and b.sent[0]["qty"] == 5
    # a new process with the state file gone still sees the order at the broker
    (agent.dir / "state-2026-10-19.json").unlink()
    again = _agent(monkeypatch, "paper", b)
    assert again.tick(AT_1016 + dt.timedelta(minutes=1))["sent"] == [] and len(b.sent) == 1


def test_bracket_body_follows_the_documented_shape(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent import broker as brk
    from app.agent.settings import get_agent_settings
    seen: list[tuple] = []

    def fake_request(method, url, params=None, json=None, headers=None, timeout=None):  # noqa: ANN001, ANN202, A002
        seen.append((method, url, params, json, headers))
        return httpx.Response(200, json={"id": "x", "status": "accepted"}, request=httpx.Request(method, url))

    monkeypatch.setattr(brk.httpx, "request", fake_request)
    get_agent_settings.cache_clear()
    b = brk.PaperBroker(get_agent_settings())
    b.bracket_buy("TSLA", 5, 364.908, 370.04, 358.32, "dp-orb-2026-10-19-TSLA")
    method, url, _, body, headers = seen[0]
    assert (method, url) == ("POST", "https://paper-api.alpaca.markets/v2/orders")
    assert body == {"symbol": "TSLA", "qty": "5", "side": "buy", "type": "limit", "limit_price": "364.91",
                    "time_in_force": "day", "order_class": "bracket", "take_profit": {"limit_price": "370.04"},
                    "stop_loss": {"stop_price": "358.32"}, "client_order_id": "dp-orb-2026-10-19-TSLA"}
    assert headers["APCA-API-KEY-ID"] == PAPER_KEY


def test_broker_errors_never_show_the_keys(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent import broker as brk
    from app.agent.settings import get_agent_settings

    def leaky(method, url, params=None, json=None, headers=None, timeout=None):  # noqa: ANN001, ANN202, A002
        return httpx.Response(403, json={"message": f"bad key {PAPER_KEY} / {PAPER_SECRET}"},
                              request=httpx.Request(method, url))

    monkeypatch.setattr(brk.httpx, "request", leaky)
    get_agent_settings.cache_clear()
    with pytest.raises(brk.BrokerError) as e:
        brk.PaperBroker(get_agent_settings()).account()
    assert PAPER_KEY not in e.value.message and PAPER_SECRET not in e.value.message and e.value.code == "broker_refused"


def test_daily_loss_limit_closes_everything_and_stops(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = FakeBroker(equity=99_800, last_equity=100_000)
    agent = _agent(monkeypatch, "paper", b, DP_AGENT_MAX_DAILY_LOSS_USD="150")
    res = agent.tick(AT_1016)
    assert res["action"] == "halt" and b.sent == [] and b.closed == 1
    assert agent.tick(AT_1016 + dt.timedelta(minutes=5))["action"] == "idle" and b.closed == 1


def test_blocked_account_halts(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = FakeBroker(status="ACCOUNT_CLOSED")
    agent = _agent(monkeypatch, "paper", b)
    assert agent.tick(AT_1016)["action"] == "halt" and b.sent == []


def test_max_trades_per_day(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = FakeBroker(orders=[{"id": "o1", "client_order_id": "dp-orb-2026-10-19-AAPL", "status": "filled"}])
    agent = _agent(monkeypatch, "paper", b, DP_AGENT_MAX_TRADES_PER_DAY="1")
    res = agent.tick(AT_1016)
    assert res["sent"] == [] and b.sent == [] and res["traded_today"] == ["AAPL"]
    assert [r["event"] for r in _journal(agent)] == ["max_trades_reached"]


def test_refused_order_is_logged_and_not_retried(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = FakeBroker(refuse="Buying power or shares is not sufficient.")
    agent = _agent(monkeypatch, "paper", b)
    assert agent.tick(AT_1016)["done"] == {"TSLA": "order_failed"}
    agent.tick(AT_1016 + dt.timedelta(minutes=5))
    assert [r["event"] for r in _journal(agent)] == ["order_failed"]


def test_flatten_before_the_close_once(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = FakeBroker()
    agent = _agent(monkeypatch, "paper", b)
    assert agent.tick(fx.edt("2026-10-19", "15:54"))["action"] != "flatten"
    assert agent.tick(fx.edt("2026-10-19", "15:55"))["action"] == "flatten" and b.closed == 1
    assert agent.tick(fx.edt("2026-10-19", "15:58"))["action"] == "idle" and b.closed == 1


def test_kill_switch_closes_everything(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = FakeBroker()
    agent = _agent(monkeypatch, "paper", b)
    agent.stop_file.write_text("stop", encoding="utf-8")
    assert agent.tick(AT_1016)["action"] == "flatten" and b.closed == 1 and b.sent == []
    assert agent.tick(AT_1016 + dt.timedelta(minutes=1))["action"] == "idle" and b.sent == []


def test_journal_never_holds_keys(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = FakeBroker()
    agent = _agent(monkeypatch, "paper", b)
    agent.tick(AT_1016)
    text = "".join(p.read_text(encoding="utf-8") for p in agent.dir.iterdir())
    for k in (DATA_KEY, DATA_SECRET, PAPER_KEY, PAPER_SECRET):
        assert k not in text
