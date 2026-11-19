"""Agente de paper trading do DARK POOL (Bloco 11). Só conta PAPER da Alpaca (dinheiro simulado).

Uso, a partir da raiz do projeto:
    backend\\.venv\\Scripts\\python.exe scripts\\paper_agent.py check     # configuração e conta, sem ordens
    backend\\.venv\\Scripts\\python.exe scripts\\paper_agent.py once      # uma verificação
    backend\\.venv\\Scripts\\python.exe scripts\\paper_agent.py run       # verifica a cada DP_AGENT_POLL_S até Ctrl+C
    backend\\.venv\\Scripts\\python.exe scripts\\paper_agent.py flatten   # cancela ordens e zera posições agora
    backend\\.venv\\Scripts\\python.exe scripts\\paper_agent.py stop      # liga o kill switch (cria o arquivo STOP)
    backend\\.venv\\Scripts\\python.exe scripts\\paper_agent.py resume    # desliga o kill switch

Configuração em backend/.env (veja .env.example, seção "Agente de paper trading"):
DP_AGENT_MODE (off | dry_run | paper), DP_AGENT_SYMBOLS, ALPACA_PAPER_KEY_ID, ALPACA_PAPER_SECRET_KEY e
os limites de risco. As barras vêm da Alpaca Market Data (ALPACA_API_KEY_ID), feed IEX em tempo real.
O diário de cada dia fica em backend/.data/agent/journal-AAAA-MM-DD.jsonl. Nunca imprime as chaves.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.broker import BrokerError, PaperBroker  # noqa: E402
from app.agent.runner import Agent, AgentConfigError  # noqa: E402
from app.agent.settings import get_agent_settings  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.services import market_calendar as mcal  # noqa: E402


def _print(obj: object) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def _now(arg: str | None) -> dt.datetime | None:
    """--now "2026-10-19 10:16" (horário de Nova York), só para ensaio em dry_run."""
    if not arg:
        return None
    return dt.datetime.strptime(arg, "%Y-%m-%d %H:%M").replace(tzinfo=mcal.NY).astimezone(dt.UTC)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["check", "once", "run", "flatten", "stop", "resume"])
    ap.add_argument("--now", help='Relógio simulado, horário de Nova York ("AAAA-MM-DD HH:MM"); só em dry_run.')
    a = ap.parse_args()
    s = get_agent_settings()
    data_dir = get_settings().dp_data_dir
    stop_file = data_dir / "agent" / "STOP"

    if a.command == "stop":
        stop_file.parent.mkdir(parents=True, exist_ok=True)
        stop_file.write_text("kill switch\n", encoding="utf-8")
        print(f"Kill switch ligado ({stop_file}). Na próxima verificação o agente zera tudo e não entra mais.")
        return 0
    if a.command == "resume":
        stop_file.unlink(missing_ok=True)
        print("Kill switch desligado.")
        return 0

    if a.now and s.dp_agent_mode == "paper":
        print("--now só vale em DP_AGENT_MODE=dry_run (nunca envia ordens com relógio simulado).")
        return 2

    if a.command == "check":
        cfg = {"mode": s.dp_agent_mode, "symbols": s.symbols, "paper_keys": s.paper_keys_set,
               "market_data_keys": bool(get_settings().alpaca_api_key_id and get_settings().alpaca_api_secret_key),
               "strategy": {"setup": "orb", "or_minutes": s.dp_agent_or_minutes, "stop_rule": s.dp_agent_stop_rule,
                            "target_r": s.dp_agent_target_r},
               "limits": {"risk_per_trade_usd": s.dp_agent_risk_per_trade_usd,
                          "max_position_usd": s.dp_agent_max_position_usd,
                          "max_trades_per_day": s.dp_agent_max_trades_per_day,
                          "max_daily_loss_usd": s.dp_agent_max_daily_loss_usd},
               "kill_switch": stop_file.exists(), "market": mcal.status()}
        if s.paper_keys_set:
            try:
                acct = PaperBroker(s).account()
                cfg["paper_account"] = {k: acct.get(k) for k in ("status", "equity", "last_equity", "buying_power",
                                                                 "trading_blocked", "account_blocked", "multiplier")}
            except BrokerError as e:
                cfg["paper_account"] = {"error": e.code, "message": e.message}
        _print(cfg)
        return 0

    try:
        agent = Agent(s, data_dir)
    except (AgentConfigError, BrokerError) as e:
        print(f"Não iniciado: {getattr(e, 'message', e)}")
        return 2

    if a.command == "flatten":
        if s.dp_agent_mode != "paper":
            print("flatten só faz sentido em DP_AGENT_MODE=paper.")
            return 2
        try:
            _print(agent.broker.close_all())  # type: ignore[union-attr]
        except BrokerError as e:
            print(e.message)
            return 1
        return 0

    if a.command == "once":
        _print(agent.tick(_now(a.now)))
        return 0

    print(f"Agente em modo {s.dp_agent_mode}, símbolos {', '.join(s.symbols)}. Ctrl+C para sair.")
    try:
        while True:
            try:
                res = agent.tick()
            except Exception as e:  # noqa: BLE001  (one bad tick must not stop the loop)
                msg = f"{type(e).__name__}: {e}"
                res = {"action": "error", "reason": agent.broker.scrub(msg) if agent.broker else msg}
            if res.get("action") not in ("idle", "watch"):
                _print(res)
            time.sleep(s.dp_agent_poll_s)
    except KeyboardInterrupt:
        print("Encerrado. Posições abertas continuam com stop e alvo na Alpaca; use 'flatten' para zerar.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
