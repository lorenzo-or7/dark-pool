"""Teste de fumaça das chaves da Alpaca (plano Basic, feed IEX). Só leitura, nenhuma ordem.

Uso, a partir da raiz do projeto:
    backend\\.venv\\Scripts\\python.exe scripts\\check_alpaca.py
    backend\\.venv\\Scripts\\python.exe scripts\\check_alpaca.py --symbol AAPL --date 2026-10-19

Lê ALPACA_API_KEY_ID e ALPACA_API_SECRET_KEY de backend/.env (ou das variáveis de ambiente),
pede as barras de 5 minutos de um pregão e diz quantas vieram. Nunca imprime as chaves.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
URL = "https://data.alpaca.markets/v2/stocks/bars"
NY = ZoneInfo("America/New_York")


def read_env() -> dict[str, str]:
    vals: dict[str, str] = {}
    for p in (ROOT / ".env", ROOT / "backend" / ".env"):
        if p.exists():
            for line in p.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    vals[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"):
        if os.environ.get(k):
            vals[k] = os.environ[k]
    return vals


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbol", default="TSLA")
    ap.add_argument("--date", default="2026-10-19", help="um dia de pregão (AAAA-MM-DD)")
    a = ap.parse_args()

    env = read_env()
    key, secret = env.get("ALPACA_API_KEY_ID", ""), env.get("ALPACA_API_SECRET_KEY", "")
    if not key or not secret:
        print("Faltam ALPACA_API_KEY_ID e/ou ALPACA_API_SECRET_KEY em backend/.env.")
        return 2
    print(f"Chave encontrada: {key[:2]}...{key[-2:]} (o secret não é exibido)")

    day = dt.date.fromisoformat(a.date)
    start = dt.datetime.combine(day, dt.time(9, 30), NY).astimezone(dt.UTC)
    end = dt.datetime.combine(day, dt.time(16, 0), NY).astimezone(dt.UTC)
    q = urllib.parse.urlencode({"symbols": a.symbol.upper(), "timeframe": "5Min", "feed": "iex",
                                "adjustment": "all", "limit": 1000,
                                "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "end": end.strftime("%Y-%m-%dT%H:%M:%SZ")})
    req = urllib.request.Request(f"{URL}?{q}", headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
                                                        "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            doc = json.load(r)
    except urllib.error.HTTPError as e:
        hint = {401: "chave ou secret incorretos", 403: "chave sem permissão para dados de mercado",
                429: "limite de requisições atingido; tente em um minuto"}.get(e.code, "")
        print(f"Falhou: HTTP {e.code} {hint}".strip())
        return 1
    except urllib.error.URLError as e:
        print(f"Falhou: não foi possível acessar a Alpaca ({e.reason}).")
        return 1

    bars = (doc.get("bars") or {}).get(a.symbol.upper()) or []
    print(f"OK: {len(bars)} barras de 5 min de {a.symbol.upper()} em {a.date} (feed IEX). Um pregão completo tem 78.")
    if bars:
        t0 = dt.datetime.fromisoformat(bars[0]["t"].replace("Z", "+00:00")).astimezone(NY)
        t1 = dt.datetime.fromisoformat(bars[-1]["t"].replace("Z", "+00:00")).astimezone(NY)
        print(f"Primeira barra {t0:%H:%M}, última {t1:%H:%M} (horário de Nova York).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
