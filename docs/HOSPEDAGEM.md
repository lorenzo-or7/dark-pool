# Hospedagem: Supabase + Render + Vercel

Arquitetura: **Vercel** serve o frontend completo, **Render** roda o backend Python (FastAPI) e **Supabase**
guarda o banco (Postgres com RLS) e os arquivos (buckets privados). O GitHub Pages continua publicando só a landing.

Nada neste guia apaga dados. O workspace DARK POOL existente, com seus IDs, estratégias e resultados, é o que fica
público. Nenhum valor secreto vai para o repositório nem para o navegador.

## 1. Supabase

1. **Migration nova.** Aplique `supabase/migrations/20261030000100_public_shared_lab.sql` (SQL Editor, ou
   `npx supabase db push` com o projeto vinculado). Ela só acrescenta: duas funções, três políticas restritivas,
   o bucket privado `snapshots` e suas políticas. A migration v0.1 não é alterada.
2. **Connection string.** Project Settings → Database → Connection string → **Session pooler** (funciona por IPv4,
   que é o que o Render usa). Ela vira `DATABASE_URL` no Render e no seu `.env` local. Use a senha do banco.
3. **Chave de servidor.** Project Settings → API Keys → uma **secret key** (`sb_secret_...`) ou a `service_role`
   legada. Ela vira `SUPABASE_SERVICE_ROLE_KEY`, só no backend. O frontend não usa chave nenhuma.
4. **Preparar o workspace** (no seu computador, com `DATABASE_URL` no `.env` local, fora do git):

   ```bash
   py -3 scripts\setup_public_lab.py --list-workspaces
   ```

   ```bash
   py -3 scripts\setup_public_lab.py --workspace-id ID_DO_WORKSPACE_DARK_POOL
   ```

   O script valida o workspace, cria uma identidade técnica (sem senha, bloqueada para login, membro e nunca
   proprietária) e imprime o valor de `DP_PUBLIC_WORKSPACE_ID`. Pode ser rodado de novo sem efeito colateral.
5. **Arquivos que só existem no seu computador.** Snapshots baixados pelo backend local ficaram em
   `backend\.data\snapshots`. Para que o backend hospedado consiga repetir esses experimentos, envie-os uma vez
   (precisa também de `SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY` no `.env` local):

   ```bash
   py -3 scripts\setup_public_lab.py --workspace-id ID_DO_WORKSPACE_DARK_POOL --upload-local-files backend\.data
   ```

   O script confere o SHA-256 de cada arquivo antes de enviar. O snapshot de referência TSLA não precisa: o backend
   recria a partir do pacote. Resultados já gravados no banco aparecem mesmo sem os arquivos; só "repetir com os
   mesmos dados" depende deles.
6. **Conferir.** Em Storage, os buckets `attachments` e `snapshots` devem estar como *Private*. Em Authentication →
   Users aparece um usuário `laboratorio-publico+...@darkpool.invalid` (banido): é a identidade técnica; não o apague.
   O cadastro público pode continuar desativado.

## 2. Render (backend)

1. New → **Blueprint** → escolha o repositório. O `render.yaml` da raiz cria o serviço `darkpool-api`
   (Python, `rootDir: backend`, plano free, healthcheck em `/api/health`, bind em `0.0.0.0:$PORT`).
2. O Render pede os valores marcados `sync: false`:

   | Variável | Valor |
   |---|---|
   | `DATABASE_URL` | connection string do Session pooler |
   | `DP_PUBLIC_WORKSPACE_ID` | o UUID impresso pelo script |
   | `SUPABASE_URL` | `https://<projeto>.supabase.co` |
   | `SUPABASE_SERVICE_ROLE_KEY` | a secret key |
   | `DP_ALLOWED_ORIGINS` | o endereço da Vercel, ex. `https://dark-pool.vercel.app` (vírgulas para mais de um) |
   | `SEC_USER_AGENT` | `Seu Nome seu@email` (opcional; notícias 8-K e resultados) |
   | `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` | chaves do plano Basic da Alpaca (opcional; candles de 5 min do Time Machine e do backtest ORB). Só aqui, nunca no frontend |
   | `DP_INTRADAY_PROVIDER` | `auto` (Alpaca quando há chaves; senão Yahoo) |

3. Depois do deploy, abra `https://<serviço>.onrender.com/api/health`. Esperado: `"mode": "public"`,
   `"public_lab": "ready"`, `"storage": "supabase"`. Se aparecer `unconfigured`, o campo `detail` diz o que falta.
4. `DP_TRUSTED_PROXY_HOPS=1` faz os limites por IP usarem o endereço que o proxy do Render acrescenta em
   `X-Forwarded-For`. Se todos os visitantes parecerem vir do mesmo IP (limites atingidos cedo demais), ajuste.
5. `PYTHON_VERSION` está fixado no `render.yaml`; confira na documentação do Render se a versão está disponível.

Plano gratuito: o serviço é suspenso após 15 minutos sem tráfego e volta em cerca de um minuto no próximo acesso.
Tarefas que estavam rodando são marcadas como interrompidas ao voltar. O disco é temporário: por isso snapshots e
imagens do diário vão para o Supabase Storage.

## 3. Vercel (frontend completo)

1. Add New → Project → o mesmo repositório. **Root Directory: `frontend`**. O `frontend/vercel.json` define
   `npm ci`, `npm run build`, saída `dist` e o fallback de SPA (qualquer caminho abre `index.html`, então
   `/app/analytics` pode ser aberto e recarregado direto).
2. Variável de ambiente (Production e Preview): `VITE_API_URL=https://<serviço>.onrender.com` (sem `/api`).
   Não defina `VITE_PUBLIC_ONLY`: esse é o build só da landing, usado pelo GitHub Pages.
3. Depois do primeiro deploy, coloque o endereço da Vercel em `DP_ALLOWED_ORIGINS` no Render.

## 4. GitHub Pages (opcional)

Continua igual. Para os botões da landing apontarem para o laboratório, crie a variável de repositório
`DP_LAB_URL` (Settings → Secrets and variables → Actions → Variables) com o endereço da Vercel.

## Variáveis (sem valores)

Backend (Render ou `.env` local): `DP_AUTH_MODE=public`, `DP_PUBLIC_WORKSPACE_ID`, `DATABASE_URL`, `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, `DP_STORAGE=supabase`, `DP_ALLOWED_ORIGINS`, `SEC_USER_AGENT`, `DP_TRUSTED_PROXY_HOPS`,
`DP_JOB_WORKERS`, `DP_JOB_TIMEOUT_S`, `DP_MAX_ACTIVE_JOBS`, `DP_RATE_LIMIT_PER_MIN`, `DP_RATE_LIMIT_WRITES_PER_MIN`,
`DP_RATE_LIMIT_JOBS_PER_MIN`, `DP_MAX_BODY_BYTES`, `DP_MAX_UPLOAD_BYTES`, `DP_MARK_INTERRUPTED_ON_START`.

Frontend (Vercel): `VITE_API_URL`. Landing no Pages: `VITE_LAB_URL` (via `DP_LAB_URL`).

Descrição de cada uma: `.env.example`.
