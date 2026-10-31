"""Teste de fumaça das chaves da Alpaca (plano Basic, feeds SIP e IEX). Só leitura, nenhuma ordem.

Uso, a partir da raiz do projeto:
    backend\\.venv\\Scripts\\python.exe scripts\\check_alpaca.py
    backend\\.venv\\Scripts\\python.exe scripts\\check_alpaca.py --symbol AAPL --date 2026-10-19
    backend\\.venv\\Scripts\\python.exe scripts\\check_alpaca.py --feed sip

Lê ALPACA_API_KEY_ID e ALPACA_API_SECRET_KEY de backend/.env (ou das variáveis de ambiente),
pede as barras de 5 minutos do pregão regular de um dia e diz quantas vieram e se o campo t é o
início da barra (a barra das 9:30 deve vir com t = 13:30Z no horário de verão de Nova York).
Por padrão testa os dois feeds: SIP (consolidado; o plano gratuito serve dados com mais de 15 minutos,
que é o padrão do laboratório, DP_ALPACA_FEED=sip) e IEX (uma bolsa só). Nunca imprime as chaves,
nem parte delas.
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
    ap.add_argument("--feed", choices=("both", "sip", "iex"), default="both")
    a = ap.parse_args()

    env = read_env()
    key, secret = env.get("ALPACA_API_KEY_ID", ""), env.get("ALPACA_API_SECRET_KEY", "")
    if not key or not secret:
        print("Faltam ALPACA_API_KEY_ID e/ou ALPACA_API_SECRET_KEY em backend/.env.")
        return 2
    print("Chaves encontradas (não são exibidas).")

    day = dt.date.fromisoformat(a.date)
    feeds = ["sip", "iex"] if a.feed == "both" else [a.feed]
    worst = 0
    for f in feeds:
        worst = max(worst, check(a.symbol.upper(), day, f, key, secret))
    return worst


def check(sym: str, day: dt.date, feed: str, key: str, secret: str) -> int:
    start = dt.datetime.combine(day, dt.time(9, 30), NY).astimezone(dt.UTC)
    # `end` é inclusivo: 15:59:59 deixa de fora a barra das 16:00 (after-hours).
    end = dt.datetime.combine(day, dt.time(15, 59, 59), NY).astimezone(dt.UTC)
    q = urllib.parse.urlencode({"symbols": sym, "timeframe": "5Min", "feed": feed,
                                "adjustment": "all", "limit": 1000,
                                "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "end": end.strftime("%Y-%m-%dT%H:%M:%SZ")})
    req = urllib.request.Request(f"{URL}?{q}", headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
                                                        "Accept": "application/json"})
    tag = f"[{feed.upper()}]"
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            doc = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = str(json.loads(e.read().decode("utf-8", "replace")).get("message", ""))[:160]
        except Exception:  # noqa: BLE001
            msg = ""
        hint = {401: "chave ou secret incorretos", 403: "chave sem permissão para dados de mercado",
                429: "limite de requisições atingido; tente em um minuto"}.get(e.code, "")
        if "subscription" in msg.lower():
            hint = "o plano não cobre esse feed/período"
        print(f"{tag} Falhou: HTTP {e.code} {hint}".strip() + (f" ({msg})" if msg else ""))
        return 1
    except urllib.error.URLError as e:
        print(f"{tag} Falhou: não foi possível acessar a Alpaca ({e.reason}).")
        return 1

    bars = (doc.get("bars") or {}).get(sym) or []
    vol = sum(int(b.get("v") or 0) for b in bars)
    print(f"{tag} OK: {len(bars)} barras de 5 min de {sym} em {day} (volume somado {vol:,}). "
          "Um pregão completo tem 78.")
    if bars:
        t0 = dt.datetime.fromisoformat(bars[0]["t"].replace("Z", "+00:00")).astimezone(NY)
        t1 = dt.datetime.fromisoformat(bars[-1]["t"].replace("Z", "+00:00")).astimezone(NY)
        print(f"{tag} Primeira barra {t0:%H:%M} (t = {bars[0]['t']}), última {t1:%H:%M} (horário de Nova York).")
        if t0.strftime("%H:%M") == "09:30" and t1.strftime("%H:%M") <= "15:55":
            print(f"{tag} Confere: t é o início da barra (a barra 9:30-9:35 vem com t = 9:30).")
        else:
            print(f"{tag} ATENÇÃO: não deu para confirmar que t é o início da barra. Informe estas linhas.")
        off = [b["t"] for b in bars
               if dt.datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp() % 300]
        if off:
            print(f"{tag} ATENÇÃO: {len(off)} barra(s) fora da grade de 5 minutos.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
