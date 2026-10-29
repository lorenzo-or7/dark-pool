# Testes do DARK POOL

Cada suíte fica junto do código que testa:

| Suíte | Onde | Como rodar (Windows, a partir da raiz) |
|---|---|---|
| API, autenticação, isolamento, jobs, Time Machine (regressão), backtests, métricas | `backend/tests` | `backend\.venv\Scripts\python.exe -m pytest backend` |
| Testes originais da Day Trader Skill (scanner, timemachine, entry, exit, budget, news, analyst) | `backend/vendor/day_trader_skill/tests` | `cd backend\vendor\day_trader_skill` e `py -3 tests\test_scanner.py` (um arquivo por módulo) |
| Unitários do frontend (Vitest) | `frontend/src/**/*.test.ts` | `npm --prefix frontend test` |
| Navegador (Playwright, desktop e mobile) | `frontend/e2e` | `npm --prefix frontend run test:e2e` (sobe backend e frontend se não estiverem rodando) |
| RLS da migration (Postgres embutido PGlite) | `supabase/tests` | `npm --prefix supabase/tests install` e depois `npm --prefix supabase/tests test` |

`test_risk.py` do pacote original depende do `trader-broker`, que não foi incorporado; ele é rodado contra a
instalação original da skill (veja o README principal).

A regressão do Time Machine usa o arquivo fixo `TSLA-60d5m.json.gz` do pacote e só vale com esse arquivo:
TSLA, 19/10/2026, entrada 364,18 às 10:15 ET, stop 358,32, alvo 370,04, seed 19, 10.000 replays →
alvo 29,4 %, stop 25,5 %, nenhum 45,1 %.
