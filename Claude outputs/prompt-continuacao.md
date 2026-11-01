# Prompt de continuação — DARK POOL (estado de 01/11/2026, 19h45)

> Cole este prompt no agente de código da outra conta, com acesso ao repositório
> https://github.com/lorenzo-or7/dark-pool (ou ao checkout local do usuário). Este arquivo está na branch
> `bloco4-entry-exit` em `Claude outputs/prompt-continuacao.md`; o contexto completo está no ANEXO, no fim.

## Papel e regras

Você é o engenheiro responsável pela camada de dados do DARK POOL (laboratório público de pesquisa quantitativa de
ações dos EUA: FastAPI no Render, React/Vite na Vercel, Supabase). Antes de qualquer coisa, leia:
1. O ANEXO no fim deste arquivo — papel, regras, arquitetura, provedores, pendências e o formato do relatório de cada
   bloco ("ENTREGA DE CADA BLOCO").
2. `docs/INTEGRACOES.md` no repositório — registro de cada integração (fontes, URLs, limites, testes). As seções do fim
   cobrem 31/10 e 01/11.

Regras que o usuário reforçou: um bloco por vez; ao fim de cada bloco rode TODAS as suítes; os motores em
`backend/vendor/day_trader_skill` não são editados; sem push nem deploy sem autorização (o usuário autorizou
enviar para a branch de trabalho, não para a `main`); não invente endpoints, campos ou limites — cite a documentação;
nunca escreva chaves em código, log, commit ou documentação; responda em português do Brasil.

## Onde está o código

Branch **`bloco4-entry-exit`** no GitHub, sobre o `695bccd` (último commit da `main`). A `main` não foi alterada.
- Ver: https://github.com/lorenzo-or7/dark-pool/tree/bloco4-entry-exit
- Pull request para revisão: https://github.com/lorenzo-or7/dark-pool/pull/new/bloco4-entry-exit
- Checkout: `git fetch origin && git checkout bloco4-entry-exit`

Commits da branch (do mais antigo ao mais novo):
| Commit | Conteúdo |
|---|---|
| `df5d1a9` | Alpaca: feed SIP (consolidado) como padrão (`DP_ALPACA_FEED`), IEX por configuração |
| `7f75b76` | Bloco 4: plano ORB (Entry + Exit) com as barras do dia; stop `atr:K` |
| `dcc8267` | Exibição em R no modo público (aprovada pelo usuário): planos, Time Machine, backtests e Scanner sem preços do provedor; Time Machine com `plan_rule` (plano calculado no servidor) |
| `b80d202` | Bloco 5: alertas sob demanda; cotações por Alpaca snapshots (`DP_ALPACA_QUOTE_FEED=delayed_sip`) ou Yahoo; sem Stooq |
| `be7e456` | Bloco 6: Scanner diário e ORB com barras da Alpaca (`DP_SCAN_PROVIDER`) |
| `f59be94` | Ajuste visual do Scanner ORB (conferência visual feita) |
| `5d63690` | Bloco 7: notícias pela SEC 8-K e GDELT (manchetes + tom); RSS do Yahoo só onde fontes não oficiais são permitidas |
| `11b3246` | Bloco 8: perfil SEC por ativo (`GET /api/assets/{s}/profile`: CIK, bolsas, SIC, setor pela divisão SIC) |
| `31fa928` | Remove o prompt de continuação do repositório (guardado no projeto do Claude) |
| `711a2e3` | Bloco 9: Analyst pela SEC com o fetcher do servidor (cache em disco) e histórico de divulgação (8-K item 2.02, sem estimar datas); corrige a rota de fundamentos, que quebrava; aba "Resultados (SEC)" em tabela |

Testes no fim do Bloco 9 (Linux): backend 434 passed, 10 skipped (inclui os testes originais da skill);
`test_public_pg.py` com Postgres local 9 passed; motores da skill ok; frontend typecheck ok, 13 testes, build ok,
lint com 21 avisos antigos (nenhum novo); Playwright 12 passed, 6 skipped.

Tudo foi testado só com fixtures (arquivos salvos da skill, fixtures derivadas e respostas escritas à mão, sempre
identificadas). O ambiente de nuvem usado não alcançava `data.alpaca.markets`, Yahoo, SEC nem GDELT (proxy 403):
testes reais só no computador do usuário.

## Comandos de teste

```
backend\.venv\Scripts\python.exe -m pytest backend
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```
E `test_public_pg.py` com `DP_TEST_PG_URL=postgresql://postgres@127.0.0.1:PORTA/postgres` (Postgres descartável,
nunca o Supabase). No Linux: `python -m pytest backend`; para o Playwright com um Chromium já instalado, use
`DP_E2E_PYTHON` e `DP_E2E_CHROMIUM`.

## Pendências que dependem do usuário

- [ ] Chaves NOVAS da Alpaca (as antigas foram expostas) em `backend\.env`; rodar `scripts\check_alpaca.py` e
      informar as linhas `[SIP]`, `[IEX]`, `[cotações delayed_sip]` e `[cotações iex]` (inclui o formato da resposta
      de snapshots, que a documentação não mostra). Depois `DP_LIVE_ALPACA=1` no pytest.
- [ ] `SEC_USER_AGENT` ("Nome email") em `backend\.env` e no Render. Sem ele ficam desligados: 8-K, GDELT
      (o nome da empresa vem da SEC), perfil SEC e Analyst. Pergunte ao usuário; não invente.
- [ ] Confirmar no teste real: campos do GDELT DOC 2.0 (a página de referência não abriu no ambiente) e os campos
      `sic`/`sicDescription` das submissões da SEC (o arquivo salvo na skill é um trecho).
- [ ] Pendências externas de termos (Alpaca em site público; parecer jurídico do Pelosi): ver o ANEXO ("PENDÊNCIAS EXTERNAS").

## Onde retomar: Bloco 10 (Pelosi) EM ANDAMENTO

O último commit da branch ("Bloco 10 em andamento") traz o backend inicial, ainda SEM testes, SEM frontend e SEM
documentação. A suíte do backend continuou passando (434 passed, 10 skipped) com esse código. Já existe:
- `backend/app/services/congress.py`: índice `<ANO>FD.zip` da House Clerk (cache de 6 h, cota do provedor
  `house_clerk`), PDF do PTR (cache permanente), texto pelo `pdf_to_text` do motor (precisa do `pdftotext`/poppler;
  sem ele devolve o registro, as datas e o link do PDF com aviso) e linhas pelo `parse_ptr_text` do motor. Datas
  separadas: `date` (operação), `notified`, `filed` (documento) e `collected_at` (coleta). Bloco `senate`
  "não coberto" com link para o eFD. Desligado no modo `public` (403 `display_policy`) se `DP_PELOSI_PUBLIC` não
  for `true`; ligado no demo local.
- `backend/app/routers/congress.py`: `GET /api/congress/ptrs?year=&member=&since=&limit=` e
  `GET /api/congress/ptrs/{doc_id}?year=&filed=`; registrado em `main.py`.
- Provedor `house_clerk` em `providers.py` (oficial, cota local 6/min e 300/dia); motor `pelosi` no `runner.py` e no `/api/health`.

Falta, nesta ordem:
1. Testes `backend/tests/test_congress_api.py` com as fixtures reais da skill
   (`backend/vendor/day_trader_skill/tests/fixtures/trader-pelosi/`: `2026FD.zip` e os textos `ptr-*.txt`, que são
   saída do `pdftotext -layout`). Troque `congress._http_get` e `congress._pdf_text` por falsos. Oráculos: o índice
   deve ser igual ao da linha de comando do motor
   (`ptr.py index --year 2026 --member pelosi --offline .../2026FD.zip --json`) mais `collected_at`, e as linhas
   iguais às de `parse_ptr_text(texto, filed)`. Cubra: cache do índice (sem novo download), filtro `since`, PDF ilegível
   sem pdftotext, DocID inválido (400), 404 da House Clerk, modo público desligado (403, sem download) e ligado com
   `DP_PELOSI_PUBLIC=true`, e o bloco `senate`.
2. Frontend: página "Congresso" (rota em `frontend/src/App.tsx`, item no menu em
   `frontend/src/components/app/AppShell.tsx`) com a lista de PTRs (parlamentar, documento, data do documento, link do
   PDF) e o detalhe (operações com data, tipo, ativo/ticker, faixa de valor, dias até divulgar, "atrasado"). Mostre a
   política (`useDisplayPolicy` em `frontend/src/lib/policy.ts`, campo `pelosi_public`) e o aviso de que o Senado não
   é coberto.
3. Seção do Bloco 10 em `docs/INTEGRACOES.md` (fontes, cache, datas, política, limitação do pdftotext no Render).
4. Rodar TODAS as suítes, commit e push na branch.

Depois do Bloco 10: revisar com o usuário o pull request da branch, os testes reais (chaves da Alpaca e
`SEC_USER_AGENT`) e as pendências externas de termos antes de publicar.

Ao fim de cada bloco: rode todas as suítes, atualize `docs/INTEGRACOES.md`, faça commit na branch
`bloco4-entry-exit` e entregue o relatório. Prompts e documentos de contexto para o Claude não vão para o
repositório, exceto este arquivo, que o usuário pediu para deixar em `Claude outputs/prompt-continuacao.md`
(atualize-o ao fim de cada bloco).

---

# ANEXO — Contexto da integração dos provedores gratuitos no DARK POOL

> Estado atualizado em 01/11/2026: Blocos 1 a 9 feitos; os 4 a 9 e a exibição em R estão na branch `bloco4-entry-exit`. Bloco 10 em andamento (ver o início deste arquivo).
> Para o agente de código (Claude) que vai continuar o trabalho, com acesso ao checkout local do DARK POOL.
> As seções "ESTADO ATUAL" e "BLOCO 3" abaixo são o registro de 31/10; o estado de cada bloco está em "ORDEM DE INTEGRAÇÃO" e em `docs/INTEGRACOES.md`.

---

### PAPEL

Você é o engenheiro responsável pela camada de dados do DARK POOL. Sua tarefa é continuar a integração dos provedores **gratuitos** definidos abaixo, sem alterar os cálculos dos motores e sem quebrar o acesso público, o acompanhamento de jobs e a reprodutibilidade.

Leia o código antes de alterar. Não presuma que algo existe porque está descrito aqui.

### CONTEXTO

- Repositório: https://github.com/lorenzo-or7/dark-pool. Blocos 1 e 2 em `9affb62`, Bloco 3 em `695bccd` (`main`). Feed SIP e Bloco 4 na branch `bloco4-entry-exit` (commits locais da sessão de 31/10; ver o relatório dessa sessão para saber se foram enviados). Checkout do usuário: `C:\Users\lmors\OneDrive\Documentos\GitHub\dark-pool`. Não descarte alterações locais.
- Motores: módulos da day-trader-skill (https://github.com/Jakeschincariol/day-trader-skill), commit de referência `3d0f4ef`, vendorizados em `backend/vendor/day_trader_skill` e chamados por `backend/app/engines/runner.py`. Os motores **não são editados**. `trader-broker` está excluído.
- Backend Python/FastAPI (Render), frontend React/Vite (Vercel), Supabase para banco e arquivos. Arquivos do projeto no Windows usam quebras de linha CRLF.
- Laboratório público, sem login, com um único workspace compartilhado. Todos os visitantes usam as mesmas chaves e cotas, que ficam apenas no servidor.
- Mercado: somente ações dos EUA.
- Orçamento atual: **US$ 0**. Mais tarde haverá até US$ 50/mês no total. A troca de provedor deve ser feita por configuração, sem reescrever os módulos.

---

### ESTADO ATUAL (31/10/2026)

| Bloco | Situação |
|---|---|
| 1. Calendário da NYSE | Concluído, no GitHub (`9affb62`) |
| 2. Política de exibição, cotas e proveniência | Concluído, no GitHub (`9affb62`) |
| 3. Alpaca + Time Machine | No GitHub (`695bccd`). Revisado em 31/10: feed SIP como padrão (`DP_ALPACA_FEED`), branch `bloco4-entry-exit`. Testado só com fixtures; teste real pendente |
| 4. Entry e Exit | Implementado na branch `bloco4-entry-exit`: `POST /api/plan/orb` sem snapshot baixa só o dia; stop `atr:K`. Testado só com fixtures. Ver `docs/INTEGRACOES.md` |
| 5 a 10 | Não iniciados |

#### Mudança de premissa (31/10): SIP no plano gratuito

A FAQ oficial da Alpaca (https://docs.alpaca.markets/us/docs/market-data-faq) diz que, sem assinatura, o SIP histórico pode ser consultado quando o `end` tem pelo menos 15 minutos. O adaptador já nunca pede dados com menos de 16 min, então o padrão passou a ser `feed=sip` (consolidado de todas as bolsas). Consequências, a confirmar no teste real:
- As lacunas do IEX deixam de ser o caso comum (continuam medidas, nunca preenchidas).
- A correção 2 abaixo (volume IEX no Scanner) deixa de bloquear o Bloco 6: com SIP, o volume é o consolidado. Barras diárias podem migrar para a Alpaca SIP no Bloco 6, com comparação contra o Yahoo antes de trocar.
- Se o teste real recusar o SIP (`provider_subscription`), `DP_ALPACA_FEED=iex` volta ao comportamento anterior.

#### Exibição em R no modo público — resolvido em 31/10 (antes era bloqueio)

Proposta de gráficos aprovada pelo usuário em 31/10 e implementada na branch `bloco4-entry-exit`: com `DP_SHOW_TRIGGER_PRICES` desligado, planos, Time Machine, backtests, trades, jobs e exports saem em R e %; o plano fica no servidor (`plan_rule`); o Scanner usa `/api/assets/{s}/relative`. Detalhes em `docs/INTEGRACOES.md`.

#### Pendências do usuário antes do Bloco 3 funcionar com dados reais

- [ ] Criar **chaves novas** da Alpaca. As chaves antigas foram expostas numa conversa e devem ser revogadas. Nunca as escreva em código, log, fixture, commit ou documentação.
- [ ] Criar `backend\.env` com `ALPACA_API_KEY_ID` e `ALPACA_API_SECRET_KEY` (o arquivo ainda não existia em 30/10).
- [ ] Rodar `backend\.venv\Scripts\python.exe scripts\check_alpaca.py` e informar, para `[SIP]` e `[IEX]`, a linha `OK: N barras ... (volume somado X)` ou `Falhou: ...`, e a linha `Confere: t é o início da barra` (ou `ATENÇÃO`).
- [x] `tests\alpaca_script.py` removido em 30/10 (cópia redundante de `scripts\check_alpaca.py`, sem chaves; a primeira linha já não estava corrompida).
- [ ] `SEC_USER_AGENT`: não havia `.env` com esse valor. Confirmar onde está configurado ou pedir nome e e-mail do projeto.
- [x] Proposta de gráficos do modo público aprovada e implementada (31/10).

#### Proposta de gráficos (aprovada e implementada em 31/10)

No modo `public` (no `demo` os candles continuam):
1. **Time Machine:** replay desenhado em R (0 na entrada, −1R no stop, +xR no alvo), sem eixo de preço. O plano ORB fica guardado no servidor e a tela mostra entrada, stop e alvo em R e em %. Isso permite ativar `DP_SHOW_TRIGGER_PRICES` sem quebrar o fluxo, que hoje envia entrada, stop e alvo em dólares.
2. **Scanner:** retorno acumulado em % e indicadores relativos (RSI, distância da MM20 em %, ATR em %) no lugar dos candles.
3. **Dashboard:** mantém variação do dia e volatilidade; sai o minigráfico de preço.

Implementada em 31/10.

---

### BLOCO 3 — REGISTRO: adaptador Alpaca + Time Machine (concluído; mantido como referência)

Implementado como descrito abaixo, com uma mudança em 31/10: o feed padrão passou de `iex` para `sip` (ver "Mudança de premissa").

#### Fatos verificados na documentação (30/10/2026)
Fonte: https://docs.alpaca.markets/reference/stockbars e https://docs.alpaca.markets/us/docs/about-market-data-api.md. Confira de novo antes de codificar.
- `GET https://data.alpaca.markets/v2/stocks/bars`; cabeçalhos `APCA-API-KEY-ID` e `APCA-API-SECRET-KEY`.
- Parâmetros: `symbols` (lista), `timeframe` (`5Min`/`5T`, `1Day`/`1D` etc.), `start`/`end` (RFC-3339 ou AAAA-MM-DD, inclusivos), `limit` (padrão 1.000, máximo 10.000, **somando todos os símbolos**), `adjustment` (`raw` padrão, `split`, `dividend`, `spin-off`, `all`), `feed` (`sip` padrão, `iex`, `otc`, `boats`), `sort`, `page_token`, `asof`, `currency`.
- Resposta: `{bars: {SYM: [{t, o, h, l, c, v, n, vw}]}, next_page_token, currency}`. Ordenada por símbolo e depois por horário. `t` vem em RFC-3339 com `Z`; a página não diz explicitamente que é o início da barra. **Confirme com um teste real** (a barra das 9:30 deve ter `t` = 13:30Z no horário de verão).
- Erros listados: 400, 401, 403, 429 (com `X-RateLimit-*`), 500.
- Plano Basic: tempo real IEX; histórico desde 2016; 200 chamadas/min; "latest 15 minutes" restritos (a página não explica o asterisco).
- O ambiente de nuvem do agente anterior não alcançava `data.alpaca.markets` (bloqueado pelo proxy). Testes reais só no computador do usuário.

#### Desenho proposto (rascunho não testado em `rascunho-bloco3-alpaca.py`)
- `backend/app/services/alpaca.py`: `fetch_bars()` com paginação por `next_page_token`, `feed=iex`, `adjustment=all`, passando por `providers.check_allowed/acquire/success/failure` e `single_flight`. Erros: 401/403 → `provider_auth`; 429 → pausa; 400 → mensagem curta da Alpaca. Nunca repetir cabeçalhos ou a URL completa em mensagens.
- **Janela por sessões**, não por dias: `session_window(dia, sessões)` com o calendário do Bloco 1. Vai das N sessões antes do dia do plano até o fechamento desse dia, e nunca depois de agora menos 16 minutos (restrição do plano Basic). O Time Machine precisa das barras do próprio dia do plano: o motor recusa se a barra de entrada não existir.
- **Conversor** para o layout do Yahoo v8 que os motores leem (`chart.result[0].meta/timestamp/indicators.quote`), com:
  - `meta.symbol` no formato do Yahoo (`BRK-B`) e `meta.dataGranularity = "5m"`, porque o motor confere os dois;
  - `meta.regularMarketTime` = horário da coleta. O motor só considera completa uma barra que termina antes desse horário; se você usar o início da última barra, ela some;
  - `meta.dataProvider`, `feed`, `adjustment`, `fetchedAt` e `window`, para proveniência;
  - JSON determinístico (`sort_keys`, separadores fixos), para o mesmo dado dar o mesmo hash.
- Snapshot: `source = "alpaca:iex"`; a coluna `range` é `String(8)`, então use algo como `"60sess"`; adicionar `"alpaca:iex": "alpaca"` em `providers.SOURCE_PROVIDER` e marcar a Alpaca como integrada.
- **Qualidade do IEX:** contar barras por sessão contra o esperado (78, ou 42 em fechamento antecipado), sessões completas, barras faltantes. Gravar em `results.data_quality` e mostrar na tela. Não preencher lacunas. O motor exige pelo menos 20 sessões completas (`MIN_SESSIONS`).
- Escolha do provedor: `DP_INTRADAY_PROVIDER = auto | alpaca | yahoo` (`auto` = Alpaca quando há chave). Só as **barras de 5 minutos** (Time Machine e backtests ORB) passam para a Alpaca neste bloco. **Barras diárias continuam no Yahoo:** os backtests diários filtram por volume médio, e o volume do IEX não é o consolidado (mesmo problema do Scanner, Bloco 6).
- `history_sessions` (padrão 60, de 20 a 250) em `TimeMachineRequest` e `BacktestRequest`; ignorado com snapshot ou com Yahoo. Ajustar `_new_data_allowed` para checar o provedor do intervalo pedido.
- `JobContext` ganharia um campo `data_quality` para o handler devolver a qualidade da coleta.

#### Testes do Bloco 3
- Fixture em formato Alpaca **derivada** do arquivo TSLA da skill (identificada como derivada, não coletada). Converter de volta e rodar o Time Machine com seed 19: o resultado deve ser idêntico ao da fixture original.
- Paginação com `next_page_token`; erros 401, 403, 429, 400 e de rede; nenhuma chave em exceções, logs ou respostas.
- Lacunas do IEX: remover barras de algumas sessões e conferir a contagem, a exclusão de sessões e o erro claro quando a barra de entrada faltar.
- Janela: feriados, fechamento antecipado, dia de hoje antes do fim do pregão.
- API ponta a ponta com a Alpaca simulada: snapshot `alpaca:iex`, proveniência Alpaca, `data_quality`, reprodução pelo snapshot com os mesmos números.
- Teste `live` pulado sem chave e sem `DP_LIVE_ALPACA=1`.
- Suíte completa do backend, `test_public_pg.py` e frontend.

---

### CONCLUSÃO DO RELATÓRIO DE PROVEDORES (30/10/2026)

Nenhum plano gratuito ou de até US$ 50/mês verificado autoriza mostrar preços ou candles brutos a visitantes anônimos. As fontes gratuitas que permitem reuso público são oficiais (SEC EDGAR, Nasdaq Trader, GDELT) ou calculadas localmente (calendário). Os termos do Yahoo proíbem a coleta automatizada e o uso comercial.

Por isso:
- Preços e barras são **insumo interno** do servidor.
- O público vê **resultados próprios**: sinais, métricas, simulações e estatísticas.
- A exibição de preços brutos fica atrás da política configurável (já implementada).

As confirmações externas bloqueiam a **publicação**, não o desenvolvimento local.

### PILHA DA FASE GRATUITA

| Fonte | Uso | Módulos | Categoria |
|---|---|---|---|
| Alpaca Market Data, plano Basic (feed SIP com mais de 15 min; IEX opcional) | Barras e preços, só cálculo interno | Scanner, Time Machine, Entry, Exit, Alerts | B (o usuário obtém a chave) |
| SEC EDGAR | Fundamentos, 8-K, CIK, código SIC | Analyst, News, universo | A |
| GDELT DOC 2.0 | Manchetes, com citação e link obrigatórios | News | A |
| House Clerk | PTRs da Câmara | Pelosi | A |
| Nasdaq Trader SymDir | Universo de ativos | Scanner | A |
| exchange_calendars (XNYS) | Feriados e pregões reduzidos | Todos que usam o relógio da NYSE | A (já integrado) |

Fora desta etapa: Tiingo, Marketaux, FMP, Quiver e qualquer plano pago. Excluídos pelos termos: Massive (ex-Polygon) planos individuais, EODHD pessoal, Twelve Data grátis, Alpha Vantage.

### CORREÇÕES DA VERIFICAÇÃO (prevalecem sobre o relatório)

1. **Exit usa barras intradiárias.** O stop `atr:K` usa o ATR de 14 barras da sessão até a barra de entrada. Mesma fonte do Entry.
2. **Volume do IEX não é consolidado.** O scanner diário filtra `regularMarketVolume >= 1.000.000`; com volume IEX quase tudo cai. **Atualização 31/10:** com `feed=sip` (padrão) o volume é o consolidado; confirmar no teste real antes do Bloco 6. Só se o SIP for recusado volta a valer a necessidade de recalibrar.
3. **Barras faltantes no IEX.** ORB do Scanner e Time Machine exigem sessões completas. Meça a perda, registre na proveniência, mostre o motivo. Não preencha sem regra aprovada.
4. **Render gratuito.** Dorme após 15 minutos sem tráfego de entrada (desde 24/02/2026, mensagens WebSocket recebidas contam; conexão aberta pelo servidor não está clara); 750 horas/mês por workspace. Não dependa de WebSocket contínuo; REST sob demanda.
5. **Serviço dormindo interrompe jobs.** Confirme que jobs interrompidos viram falha com motivo claro.
6. **Tiingo não foi avaliado para o Scanner** (um ticker por chamada).

### POLÍTICA DE EXIBIÇÃO (implementada no Bloco 2)

| Configuração | Padrão no `public` | Efeito |
|---|---|---|
| Preços e candles brutos | desligado | Sem OHLCV, cotações ou séries de preço na API pública |
| Preço do gatilho nos sinais | desligado até confirmação da Alpaca | Ainda sem efeito; depende da proposta de gráficos |
| Página pública do Pelosi | desligado até o parecer jurídico | Para o Bloco 10 |
| Fontes não oficiais (Yahoo) | desligado | Permitido só no ambiente local até o substituto ser validado |

A política é aplicada no backend. Ocultar na interface não basta.

### QUEM OBTÉM CADA ACESSO

**Categoria A — sem cadastro (você integra direto):** SEC EDGAR, GDELT, House Clerk, Nasdaq Trader, exchange_calendars.
- SEC: User-Agent com nome e e-mail de contato; no máximo 10 requisições por segundo; cache de `companyfacts`. Se `SEC_USER_AGENT` não estiver configurado, pergunte ao usuário; não invente.
- GDELT: citação e link onde as manchetes aparecerem; busca pelo nome da empresa (arquivo da SEC); tom como "tom da cobertura", separado de interpretação gerada; limite conservador e cache.
- House Clerk: data da operação, do documento e da coleta separadas; faixa de valor; link do PDF; Senado "não coberto" com link para o eFD; não automatizar o aceite do termo do Senado.

**Categoria B — o usuário obtém:** só a Alpaca. Você não cria contas, não aceita termos em nome do usuário e não usa chaves de terceiros. Adaptador e testes com fixtures, provedor desativado sem chave, teste de fumaça real depois que o usuário configurar. Chave colada na conversa nunca vai para código, commit, log, fixture ou documentação: oriente a colocá-la no `.env` local e nas variáveis do Render.

### ARQUITETURA (o que vale para os próximos blocos)

1. **Inspecione antes** de cada bloco e apresente a proposta antes de alterar.
2. **Camada de provedores por tipo de dado** (barras, cotação, universo, calendário, notícias, SEC, PTRs), com interface, cadeia configurável e formato normalizado. Os motores recebem o formato que já consomem. Não altere fórmulas, gatilhos, stop, alvo, sorteio, seed nem dimensionamento.
3. **Proveniência** em todo dado entregue aos motores; reproduzir usa o snapshot salvo; execuções antigas com Yahoo continuam identificadas como Yahoo; a regressão TSLA seed 19 continua passando com a fixture original; snapshots brutos no bucket privado.
4. **Cotas compartilhadas** pela camada `providers.py` (Alpaca abaixo de 200/min; SEC abaixo de 10/s), cache, deduplicação, orçamento diário, circuit breaker, reserva só com o mesmo dado. Nada de troca silenciosa de fonte.
5. **Segredos** só em variáveis do backend; nunca `VITE_`; remova chaves de URLs, logs e erros.
6. **Interface:** fonte, feed, horário e atraso em cada resultado; atribuições; estados claros (fonte indisponível, cota esgotada, dado atrasado, dado ausente, símbolo descartado por barras faltantes).

### ORDEM DE INTEGRAÇÃO

Um bloco por vez. Pare e entregue o relatório de cada bloco antes do próximo, exceto se o usuário autorizar seguir direto.

1. ~~Calendário~~ (concluído)
2. ~~Política de exibição, proveniência e cotas~~ (concluído)
3. ~~Adaptador Alpaca + Time Machine~~ (no GitHub; feed SIP na branch `bloco4-entry-exit`)
4. ~~Entry e Exit (barras do dia; ATR da sessão)~~ (branch `bloco4-entry-exit`)
5. ~~Alerts: cotação de vários símbolos por requisição; remover o Stooq~~ (branch `bloco4-entry-exit`; sob demanda, regras no navegador)
6. ~~Scanner: diário e ORB~~ (branch `bloco4-entry-exit`; SIP = volume consolidado, sem recalibração)
7. ~~News: SEC 8-K + GDELT; desligar o RSS do Yahoo em produção~~ (branch `bloco4-entry-exit`)
8. ~~Universo: metadados da SEC~~ (branch `bloco4-entry-exit`; perfil por ativo) (CIK, bolsa, SIC como setor, após confirmar na documentação); market cap só interno; float fora
9. ~~Analyst: manter SEC; "próximo resultado" só como histórico do item 2.02 dos 8-K~~ (branch `bloco4-entry-exit`)
10. **Pelosi: House Clerk com a página pública desligada até o parecer jurídico** ← retomar aqui

O Yahoo só sai de cada módulo depois que o substituto passar nos testes.

### TESTES

Unitários com fixtures identificadas; contrato com o formato dos motores; motores com dados novos comparados ao resultado anterior; política (API pública sem preços quando desligada); cota, cache, deduplicação, circuit breaker, reserva; nenhuma chave em logs, API ou bundle; fumaça real marcada `live` só com chave; suíte completa do backend (incluindo `test_public_pg.py` com Postgres local) e do frontend (`npm run typecheck`, `npm test`, `npm run build`). Registre falhas, inclusive intermitentes, com nome do teste e erro.

### REGRAS

- Sem scraping, sem contornar limites, sem endpoints não documentados.
- Não invente endpoints, campos ou limites. Cite a URL da documentação usada.
- Não substitua dados indisponíveis por números inventados.
- Não misture fixtures com dados coletados sem identificação.
- Sem execução periódica automática e sem envio externo de alertas.
- Sem push e sem deploy sem autorização.

### PENDÊNCIAS EXTERNAS (não bloqueiam o desenvolvimento local)

- [ ] Alpaca: um site público pode usar o plano Basic só no servidor e mostrar sinais derivados (ticker, padrão, horário, preço do gatilho)?
- [ ] Tiingo: o plano Commercial (US$ 50) cobre esse uso, e o preço do gatilho conta como exibição?
- [ ] Marketaux: o plano Basic permite mostrar títulos, links e sentimento a visitantes anônimos?
- [ ] FMP: preço do acordo de exibição para estimativas, calendário e operações do Congresso.
- [ ] Parecer jurídico: o DARK POOL, gratuito e sem anúncios, está fora do "commercial purpose" da 5 U.S.C. §13107(c)? (Multa civil de até US$ 10.000.)
- [ ] Decisão de produto: manter preços brutos fora do público na fase gratuita ou reservar orçamento para licença de redistribuição (Tiingo Redistribution, US$ 250/mês no relatório).

Inclua no relatório de cada bloco o estado das pendências que o afetam.

### ENTREGA DE CADA BLOCO

**Antes de alterar:** problema concreto e solução proposta.

**Depois de implementar:**
- Comportamento final.
- Provedores integrados e categoria (A ou B).
- Arquivos alterados.
- Migrations, se houver.
- Variáveis de ambiente novas.
- Como executar localmente.
- Testes realmente executados, separando fixtures e chamadas reais.
- Consumo estimado de cota por uso típico.
- Perda de símbolos ou sessões por barras faltantes no IEX, quando aplicável.
- Limitações e riscos.
- Pedidos de chave pendentes.
- Próximo passo.

Nunca diga que uma integração está pronta se ela só funciona com fixtures ou se a chave ainda não foi configurada.

Responda em português do Brasil.
