"""Demo mode bootstrap: a local workspace with a few labelled starting points.
It never creates results: experiments only exist after an engine runs."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from ..auth import DEMO_USER_ID, DEMO_WORKSPACE_ID
from ..db import (create_demo_schema, get_engine, journal_entries, new_id, now, profiles, strategies,
                  strategy_versions, watchlist_assets, watchlists, workspace_members, workspaces)
from . import market_data as md

DEMO_STRATEGIES = [
    ("ORB TSLA · 15 min · 1R (demonstração)",
     "Regra do exemplo do trader-timemachine: entrada no primeiro candle de 5 min que fecha acima da faixa de "
     "abertura de 15 min, stop no meio da faixa, alvo de 1R.",
     {"symbol": "TSLA", "rule": {"type": "orb", "params": {"or_minutes": 15}},
      "exit": {"stop_type": "or_mid", "stop_value": 0, "target_r": 1, "max_hold_bars": 1, "flat_by": "16:00"},
      "filters": {"min_price": 5, "min_avg_volume": 0},
      "risk": {"account_size": 10000, "max_loss_per_trade": 100, "max_position_pct": 50, "daily_loss_limit": 300,
               "max_trades_per_day": 3, "min_reward_risk": 1}}),
    ("Rompimento de 20 dias · AAPL (demonstração)",
     "Fechamento acima de todos os fechamentos das 20 sessões anteriores (regra breakout_20d do scanner). "
     "Entrada na abertura seguinte, stop de 3 %, alvo de 2R, saída em até 10 sessões.",
     {"symbol": "AAPL", "rule": {"type": "breakout_20d", "params": {"lookback": 20}},
      "exit": {"stop_type": "pct", "stop_value": 3, "target_r": 2, "max_hold_bars": 10, "flat_by": "15:55"},
      "filters": {"min_price": 5, "min_avg_volume": 0},
      "risk": {"account_size": 10000, "max_loss_per_trade": 100, "max_position_pct": 50, "daily_loss_limit": 300,
               "max_trades_per_day": 3, "min_reward_risk": 1}}),
]


def bootstrap_demo() -> None:
    create_demo_schema()
    eng = get_engine()
    with eng.begin() as conn:
        if conn.execute(select(workspaces.c.id).where(workspaces.c.id == DEMO_WORKSPACE_ID)).first():
            return
        t = now()
        conn.execute(profiles.insert().values(id=DEMO_USER_ID, email="demo@darkpool.local",
                                              display_name="Pesquisador (demo)", preferences={}, created_at=t,
                                              updated_at=t))
        conn.execute(workspaces.insert().values(id=DEMO_WORKSPACE_ID, name="Laboratório DARK POOL · demonstração",
                                                is_demo=True, settings={}, created_at=t, updated_at=t))
        conn.execute(workspace_members.insert().values(workspace_id=DEMO_WORKSPACE_ID, user_id=DEMO_USER_ID,
                                                       role="owner", created_at=t))
        wl = new_id()
        conn.execute(watchlists.insert().values(id=wl, workspace_id=DEMO_WORKSPACE_ID, name="Acompanhamento",
                                                created_by=DEMO_USER_ID, updated_by=DEMO_USER_ID, created_at=t,
                                                updated_at=t))
        for s in ("TSLA", "NVDA", "AAPL", "KO", "JPM"):
            conn.execute(watchlist_assets.insert().values(id=new_id(), workspace_id=DEMO_WORKSPACE_ID,
                                                          watchlist_id=wl, symbol=s, added_by=DEMO_USER_ID,
                                                          created_at=t))
        for name, desc, cfg in DEMO_STRATEGIES:
            sid = new_id()
            conn.execute(strategies.insert().values(
                id=sid, workspace_id=DEMO_WORKSPACE_ID, name=name, description=desc, symbol=cfg["symbol"],
                rule_type=cfg["rule"]["type"], current_version=1, is_demo=True, archived=False,
                created_by=DEMO_USER_ID, updated_by=DEMO_USER_ID, created_at=t, updated_at=t))
            conn.execute(strategy_versions.insert().values(
                id=new_id(), workspace_id=DEMO_WORKSPACE_ID, strategy_id=sid, version=1, config=cfg,
                note="Configuração de demonstração", created_by=DEMO_USER_ID, created_at=t))
        conn.execute(journal_entries.insert().values(
            id=new_id(), workspace_id=DEMO_WORKSPACE_ID, title="Como usar este laboratório (demonstração)",
            body=("Este workspace é local e serve para desenvolvimento. As estratégias marcadas como demonstração "
                  "são pontos de partida, sem resultados. Os resultados só aparecem depois que o Time Machine ou "
                  "um backtest roda de verdade, com a origem dos dados registrada."),
            kind="note", tags=["demo", "onboarding"], entry_date=date.today().isoformat(), is_demo=True,
            created_by=DEMO_USER_ID, updated_by=DEMO_USER_ID, created_at=t, updated_at=t))
        md.register_fixture(conn, DEMO_WORKSPACE_ID, DEMO_USER_ID)
