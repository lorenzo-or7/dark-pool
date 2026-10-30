# DARK POOL · Market Research Lab

**BEYOND THE MARKET.** Laboratório compartilhado de pesquisa quantitativa: varredura de ações dos EUA, estratégias
versionadas, backtests sobre dados congelados, simulações Monte Carlo (Time Machine), análise estatística e um
diário de pesquisa. **Acesso público pelo link, sem login:** todos os visitantes usam o mesmo laboratório.

> Pesquisa e simulação apenas. Não há corretora conectada, depósito, carteira nem envio de ordens. Simulações não
> são previsões e resultados históricos não são promessa de rentabilidade.

## Estrutura

```text
Dark Pool/
├── backend/                 FastAPI (Python 3.13)
│   ├── app/
│   │   ├── main.py          app, CORS, cabeçalhos de segurança
│   │   ├── auth.py          modo public (identidade técnica do servidor) / JWT do Supabase / demo local
│   │   ├── limits.py        limites de requisições, payload e upload por IP
│   │   ├── db.py            tabelas (espelham as migrations) e transação com RLS por requisição
│   │   ├── schemas.py       validação de toda entrada do usuário
│   │   ├── engines/runner.py   execução segura dos scripts da Day Trader Skill
│   │   ├── services/        market_data (Yahoo + snapshots), storage (Supabase Storage privado), jobs, tasks,
│   │   │                    public_lab (preparo do workspace público), backtest, indicadores, métricas, seed demo
│   │   └── routers/         system, market, lab, journal
│   ├── vendor/day_trader_skill/   módulos MIT da skill v2.0.0 (sem trader-broker) + testes originais
│   └── tests/               pytest
├── frontend/                React + TypeScript + Vite + Tailwind v4 (+ Radix/shadcn, Motion, Three.js,
│   │                        Lightweight Charts, Recharts, React Query)
│   ├── src/lab/             LabProvider (contexto do laboratório) e JobTracker (tarefas globais)
│   ├── vercel.json          build e fallback de SPA na Vercel
│   ├── src/brand/           wordmark e eclipse em vetor
│   ├── src/components/      landing, app, charts, ui, reactbits
│   ├── src/pages/           Landing e app/* (6 áreas + Configurações); Login/ResetPassword só redirecionam
│   └── e2e/                 Playwright
├── supabase/
│   ├── config.toml          cadastro público desativado
│   ├── migrations/          schema, RLS, triggers, buckets; 20261030000100 = laboratório público
│   └── tests/               RLS em PGlite e supabase_stub.sql (Postgres local nos testes do backend)
├── scripts/                 dev.ps1, setup_public_lab.py (prepara o workspace público), e2e_backend.py,
│                            invite_member.py (modo antigo)
├── render.yaml              Blueprint do backend no Render
├── docs/HOSPEDAGEM.md       passo a passo Supabase → Render → Vercel
├── docs/COMPONENTES.md      mapa componente → arquivo → página → situação
├── tests/README.md          onde fica cada suíte de testes
└── .env.example
```

## Requisitos

- Windows, Node.js 20+ (testado com 24), Python 3.13 (`py -3`).
- Opcional: projeto Supabase (banco e armazenamento do laboratório hospedado).

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

Modo demonstração (sem Supabase; banco SQLite local em `backend/.data`, aceito só em localhost, sem login):

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

## Acesso público compartilhado (modo `public`)

Quem abre o link usa o laboratório direto, sem cadastro, senha ou conta. Todos veem e alteram o mesmo workspace:
estratégias, resultados, varreduras, simulações, watchlists e diário. Não há corretora nem ordens reais.

Como funciona, sem abrir mão do RLS:

- O backend roda com `DP_AUTH_MODE=public` e `DP_PUBLIC_WORKSPACE_ID=<id do workspace DARK POOL existente>`.
  Sem essa variável (ou com um id inválido ou não preparado) as rotas do laboratório respondem 503 com a explicação,
  e `/api/health` mostra `public_lab: unconfigured`. Nenhum workspace é escolhido automaticamente.
- Cada requisição roda como uma **identidade técnica** criada só para isso: um registro em `auth.users` sem senha,
  bloqueado para login, marcado `dp_technical`, e **membro** (nunca proprietário) apenas desse workspace. A identidade
  é decidida no servidor; cabeçalhos, ids, papéis ou claims enviados pelo navegador são ignorados.
- As transações continuam como o papel `authenticated` com essas claims, então as políticas RLS, o carimbo de autoria
  e a auditoria valem como antes. Uma migration incremental restringe a identidade técnica: ela não lê perfis nem a
  lista de membros (e-mails de quem criou o laboratório) e não altera perfis. Nada foi liberado para `anon`.
- `/api/me` e `/api/workspace` não devolvem e-mail, id de usuário, lista de membros nem configurações do workspace;
  o diário não mostra autores. Preferências visuais ficam no navegador (localStorage).
- Limites no servidor: requisições, alterações e execuções por IP por minuto, tamanho de corpo e de upload, número
  de tarefas simultâneas no laboratório (fila cheia → HTTP 429 `queue_full`) e deduplicação de execuções idênticas.

Preparar o workspace existente (idempotente; não apaga nem recria nada):

```bash
py -3 scripts\setup_public_lab.py --list-workspaces
```

```bash
py -3 scripts\setup_public_lab.py --workspace-id ID_DO_WORKSPACE_DARK_POOL
```

Passo a passo completo de hospedagem (Supabase, Render, Vercel): [`docs/HOSPEDAGEM.md`](docs/HOSPEDAGEM.md).

O modo `supabase` (login por membro, `scripts/invite_member.py`) continua no backend, mas a interface atual não tem
mais tela de login.

**SEC EDGAR:** para notícias 8-K e resultados trimestrais (trader-news, trader-analyst), defina
`SEC_USER_AGENT="Seu Nome seu@email"` no backend. Sem isso, as notícias vêm só do Yahoo e a aba de resultados avisa.

## Site público (GitHub Pages) e laboratório completo (Vercel)

São duas publicações separadas:

- `https://lorenzo-or7.github.io/dark-pool/` publica **só a landing page**, gerada pelo workflow
  `.github/workflows/pages.yml` a cada push na `main` que altere `frontend/`. Esse build usa `DP_BASE=/dark-pool/` e
  `VITE_PUBLIC_ONLY=true`: o código do laboratório e das chamadas à API fica fora do pacote. O Pages só serve
  arquivos estáticos e não executa Python. Com a variável de repositório `DP_LAB_URL`, os botões "Abrir laboratório"
  da landing apontam para o laboratório na Vercel.
- A **Vercel** publica o frontend completo (landing + laboratório) a partir de `frontend/` (`frontend/vercel.json`),
  sem `VITE_PUBLIC_ONLY`, falando com o backend do Render por `VITE_API_URL`.

Configuração única no GitHub: **Settings → Pages → Build and deployment → Source = GitHub Actions**.

## Testes

| Suíte | Comando |
|---|---|
| Backend (pytest) | `backend\.venv\Scripts\python.exe -m pytest backend` |
| Backend + RLS em Postgres local | defina `DP_TEST_PG_URL=postgresql://postgres@127.0.0.1:5432/postgres` (servidor descartável) e rode o pytest |
| Frontend (Vitest) | `npm --prefix frontend test` |
| Tipos | `npm --prefix frontend run typecheck` |
| Navegador (Playwright) | uma vez: `cd frontend` e `npx playwright install chromium`; depois `npm --prefix frontend run test:e2e` (sobe o backend em modo public numa cópia descartável do laboratório demo) |
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
SHA-256 do snapshot de dados. O arquivo comprimido fica no bucket privado `snapshots` do Supabase Storage
(`<workspace_id>/<sha256>.json.gz`), com cópia em cache em `backend/.data/snapshots`; depois de um reinício o backend
baixa de novo e confere o hash antes de usar. "Repetir com os mesmos dados" refaz a execução sobre o mesmo snapshot.

Regressão (somente com o arquivo de referência do pacote, `TSLA-60d5m.json.gz`): TSLA 19/10/2026, entrada 364,18 às
10:15 ET, stop 358,32, alvo 370,04, seed 19, 10.000 replays → alvo 29,4 %, stop 25,5 %, nenhum 45,1 %.

## Limitações conhecidas

- Os 28 componentes do 21st.dev não puderam ser baixados (o registro exige login). Foram reconstruídos a partir das
  descrições oficiais e estão marcados como provisórios em `docs/COMPONENTES.md`.
- O wordmark é uma reconstrução vetorial da prancha aprovada, até o arquivo vetorial do designer.
- Dados do Yahoo Finance: gratuitos, não oficiais e com atraso. 60 dias é o limite de candles de 5 minutos.
- O Time Machine e o backtest não modelam custos, spread, slippage nem dependência entre candles.
- As tarefas rodam em threads do próprio processo do backend. Se ele reiniciar (deploy, falha, ou a suspensão do
  plano gratuito do Render após 15 min sem tráfego), tarefas em andamento são marcadas como interrompidas na próxima
  inicialização (`DP_MARK_INTERRUPTED_ON_START`) e precisam ser iniciadas de novo. Não há execução contínua durante a
  suspensão, e o projeto não usa pings artificiais para evitá-la. O primeiro acesso depois da suspensão leva cerca
  de um minuto.
- Os limites de requisições ficam na memória do processo: valem para uma instância do backend (o padrão no Render
  gratuito). Com várias instâncias, cada uma conta separadamente.
- No laboratório público qualquer visitante pode criar, alterar e excluir dados do workspace compartilhado
  (com confirmação nas exclusões). Não há histórico por pessoa.
- O fluxo com Supabase, Render e Vercel hospedados não foi executado de ponta a ponta neste ambiente (sem
  credenciais). A migration nova e as políticas foram testadas em PostgreSQL 16 local com um stub dos esquemas
  `auth` e `storage`; o Storage foi testado com um servidor simulado.
