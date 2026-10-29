# DARK POOL · Market Research Lab

**BEYOND THE MARKET.** Laboratório privado de pesquisa quantitativa: varredura de ações dos EUA, estratégias
versionadas, backtests sobre dados congelados, simulações Monte Carlo (Time Machine), análise estatística e um
diário de pesquisa compartilhado entre dois membros.

> Pesquisa e simulação apenas. Não há corretora conectada, depósito, carteira nem envio de ordens. Simulações não
> são previsões e resultados históricos não são promessa de rentabilidade.

## Estrutura

```text
Dark Pool/
├── backend/                 FastAPI (Python 3.13)
│   ├── app/
│   │   ├── main.py          app, CORS, cabeçalhos de segurança
│   │   ├── auth.py          JWT do Supabase (JWKS ou HS256) / sessão demo local + vínculo ao workspace
│   │   ├── db.py            tabelas (espelham as migrations) e transação com RLS por requisição
│   │   ├── schemas.py       validação de toda entrada do usuário
│   │   ├── engines/runner.py   execução segura dos scripts da Day Trader Skill
│   │   ├── services/        market_data (Yahoo + snapshots), jobs, tasks, backtest, indicadores, métricas, seed demo
│   │   └── routers/         system, market, lab, journal
│   ├── vendor/day_trader_skill/   módulos MIT da skill v2.0.0 (sem trader-broker) + testes originais
│   └── tests/               pytest
├── frontend/                React + TypeScript + Vite + Tailwind v4 (+ Radix/shadcn, Motion, Three.js,
│   │                        Lightweight Charts, Recharts, React Query, Supabase JS)
│   ├── src/brand/           wordmark e eclipse em vetor
│   ├── src/components/      landing, app, charts, ui, reactbits
│   ├── src/pages/           Landing, Login, ResetPassword e app/* (6 áreas + Configurações)
│   └── e2e/                 Playwright
├── supabase/
│   ├── config.toml          cadastro público desativado
│   ├── migrations/          schema, RLS, triggers, bucket de anexos
│   └── tests/               verificação de RLS em Postgres embutido (PGlite)
├── scripts/                 dev.ps1 (sobe tudo), invite_member.py (convites)
├── docs/COMPONENTES.md      mapa componente → arquivo → página → situação
├── tests/README.md          onde fica cada suíte de testes
└── .env.example
```

## Requisitos

- Windows, Node.js 20+ (testado com 24), Python 3.13 (`py -3`).
- Opcional: projeto Supabase (para login real e banco compartilhado).

## Instalação (Windows)

```bash
py -3 -m venv backend\.venv
```

```bash
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
```

```bash
npm --prefix frontend install
```

## Executar

Modo demonstração (sem Supabase; banco SQLite local em `backend/.data`, sessão só em localhost):

```bash
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

Ou em dois terminais:

```bash
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

```bash
npm --prefix frontend run dev
```

Abra http://localhost:5173. Documentação da API (só no modo demo): http://127.0.0.1:8000/api/docs.

## Modo real com Supabase

1. Crie um projeto no Supabase. Em **Authentication → Sign In / Providers**, desative "Allow new users to sign up"
   (o `supabase/config.toml` já faz isso para o ambiente local).
2. Em **Authentication → URL Configuration**, defina o Site URL (`http://localhost:5173`) e adicione
   `http://localhost:5173/reset-password` aos Redirect URLs.
3. Aplique a migration `supabase/migrations/20261029000100_darkpool_schema.sql` (SQL Editor, ou
   `npx supabase link` e `npx supabase db push`).
4. Configure o backend criando `.env` na raiz a partir do `.env.example`:
   `DP_AUTH_MODE=supabase`, `DATABASE_URL` (string de conexão Postgres, modo Session), `SUPABASE_URL`,
   `SUPABASE_ANON_KEY` e, só se o projeto usar a chave JWT legada, `SUPABASE_JWT_SECRET`.
5. Configure o frontend em `frontend/.env.local`: `VITE_SUPABASE_URL` e `VITE_SUPABASE_ANON_KEY`.
6. Convide os dois membros (rodado pelo proprietário, com `SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY` no ambiente,
   nunca no frontend):

```bash
py -3 scripts\invite_member.py --email SEU_EMAIL --create-workspace "DARK POOL" --role owner
```

```bash
py -3 scripts\invite_member.py --email EMAIL_DO_LIPE --workspace-id ID_IMPRESSO_ACIMA --role member
```

Cada pessoa recebe o e-mail do Supabase e define a própria senha.

**Como o acesso é controlado:** o backend valida o JWT (JWKS para chaves assimétricas, HS256 para a chave legada,
com emissor, audiência e expiração), confirma que o usuário pertence a um workspace e executa cada transação como o
papel `authenticated` com as claims do usuário. As políticas RLS da migration decidem o que cada um vê e altera;
membros só podem ser adicionados pela service role. O frontend nunca recebe a service role key.

**SEC EDGAR:** para notícias 8-K e resultados trimestrais (trader-news, trader-analyst), defina
`SEC_USER_AGENT="Seu Nome seu@email"` no backend. Sem isso, as notícias vêm só do Yahoo e a aba de resultados avisa.

## Site público (GitHub Pages)

`https://lorenzo-or7.github.io/dark-pool/` publica **só a landing page**, gerada pelo workflow
`.github/workflows/pages.yml` a cada push na `main` que altere `frontend/`. Esse build usa
`DP_BASE=/dark-pool/` e `VITE_PUBLIC_ONLY=true`: o código do login, do laboratório e das chamadas à API fica fora do
pacote. O desenvolvimento local continua em `/` com o laboratório completo.

Configuração única no GitHub: **Settings → Pages → Build and deployment → Source = GitHub Actions**.

## Testes

| Suíte | Comando |
|---|---|
| Backend (pytest) | `backend\.venv\Scripts\python.exe -m pytest backend` |
| Frontend (Vitest) | `npm --prefix frontend test` |
| Tipos | `npm --prefix frontend run typecheck` |
| Navegador (Playwright) | uma vez: `cd frontend` e `npx playwright install chromium`; depois `npm --prefix frontend run test:e2e` |
| RLS (PGlite) | `npm --prefix supabase/tests install` e `npm --prefix supabase/tests test` |
| Testes originais da skill | `cd backend\vendor\day_trader_skill` e `py -3 tests\test_timemachine.py` (e os demais) |

## Integração com a Day Trader Skill

Os módulos são chamados de duas formas, ambas em `backend/app/engines/runner.py`:

- **Subprocesso** para tarefas longas (scanner, time machine, news, analyst): lista de argumentos validados,
  interpretador isolado (`-I`), sem `shell=True`, pasta de trabalho própria, limite de tempo e cancelamento.
- **Chamada direta** de funções puras: `trader-entry` + `trader-exit` (plano ORB), `trader-budget` + `trader-risk`
  (dimensionamento simulado) e o `history_replay` do Time Machine (backtest ORB).

Integrados: scanner, timemachine, entry, exit, budget, risk, news, analyst.
Não integrados nesta versão: alerts e pelosi. **trader-broker não foi copiado nem é importável.**

O `trader-budget` monta internamente um dicionário no formato de ordem da Alpaca; o backend usa só o tamanho e o
veredito de risco e descarta o resto. Nada é enviado.

## Reprodutibilidade

Cada simulação grava parâmetros completos, seed, versão do algoritmo, fonte, período do pool, número de sessões e o
SHA-256 do snapshot de dados (arquivo comprimido em `backend/.data/snapshots`). "Repetir com os mesmos dados" refaz a
execução sobre o mesmo snapshot.

Regressão (somente com o arquivo de referência do pacote, `TSLA-60d5m.json.gz`): TSLA 19/10/2026, entrada 364,18 às
10:15 ET, stop 358,32, alvo 370,04, seed 19, 10.000 replays → alvo 29,4 %, stop 25,5 %, nenhum 45,1 %.

## Limitações conhecidas

- Os 28 componentes do 21st.dev não puderam ser baixados (o registro exige login). Foram reconstruídos a partir das
  descrições oficiais e estão marcados como provisórios em `docs/COMPONENTES.md`.
- O wordmark é uma reconstrução vetorial da prancha aprovada, até o arquivo vetorial do designer.
- Dados do Yahoo Finance: gratuitos, não oficiais e com atraso. 60 dias é o limite de candles de 5 minutos.
- O Time Machine e o backtest não modelam custos, spread, slippage nem dependência entre candles.
- As tarefas rodam em threads do próprio processo do backend. Se ele reiniciar, tarefas em andamento são marcadas
  como interrompidas.
- No modo Supabase com dois computadores, os snapshots ficam no disco de quem os baixou; a outra pessoa vê os
  resultados no banco, mas só repete a execução se tiver o mesmo arquivo de snapshot.
- O login real e o RLS no Supabase hospedado não foram testados de ponta a ponta neste ambiente (sem credenciais e
  sem Docker em execução). A migration e as políticas foram verificadas em Postgres embutido (PGlite).
