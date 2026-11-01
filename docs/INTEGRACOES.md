# Integrações de dados

Registro de cada fonte de dados integrada ao DARK POOL. Uma seção por integração, preenchida
quando o bloco correspondente é entregue.

Estado (31/10/2026): Blocos 1 (calendário) e 2 (política, cotas e proveniência) no GitHub
(`9affb62`); Bloco 3 (Alpaca + Time Machine) no GitHub (`695bccd`). Na branch `bloco4-entry-exit`:
feed SIP como padrão da Alpaca e Bloco 4 (plano ORB com as barras do dia e stop por ATR). Os Blocos
3 e 4 foram testados só com fixtures; o teste real com chaves continua pendente.

Decisões de base (relatório de provedores, 30/10/2026):
- Fase gratuita: preços e barras são insumo interno do servidor; o público vê sinais, métricas e
  simulações. Nenhum plano gratuito verificado autoriza exibir preços brutos a visitantes anônimos.
- Os motores da day-trader-skill (`backend/vendor/day_trader_skill`) não são editados.

---

## Calendário da NYSE

| Item | Valor |
|---|---|
| Origem | Biblioteca `exchange_calendars` 4.13.2 (Apache-2.0), calendário `XNYS`. Calculado no servidor, sem rede e sem chave. |
| Referência oficial | https://www.nyse.com/markets/hours-calendars (publica 2025 a 2027) |
| Código | `backend/app/services/market_calendar.py` |
| Entradas | Uma data, ou o horário atual |
| Saídas | Pregão ou não, motivo (fim de semana ou nome do feriado), abertura e fechamento em Nova York, fechamento antecipado, próxima abertura e próximo fechamento |
| Rota | `GET /api/market/calendar?date=AAAA-MM-DD` (sem preços) e o campo `calendar` de `GET /api/health` |
| Frequência | Sob demanda. O calendário é montado na primeira consulta e refeito uma vez por ano, de 2016 até três anos à frente. |
| Persistência | Nenhuma. É recalculado a partir das regras da biblioteca. |
| Limites | O calendário embutido nos motores só cobre 2026 e 2027. |

### Como os motores usam o calendário

Seis motores vendorizados trazem a própria tabela da NYSE (Entry, Exit, Risk, Alerts, Scanner;
o Time Machine guarda só os fechamentos antecipados), com 2026 e 2027. Para não editar os motores:

- `POST /api/timemachine` e `POST /api/plan/orb` recusam, antes de criar tarefa ou chamar o motor,
  uma data fora de 2026–2027 (`calendar_out_of_range`) ou um dia sem pregão (`market_closed`),
  com HTTP 422 e mensagem em português.
- A partir de 30 de setembro do último ano coberto pelos motores, o `/api/health` passa a
  `calendar.status = "warning"` pedindo a atualização da skill.

### Tratamento de falhas

- Data fora do intervalo do servidor: HTTP 422 `calendar_out_of_range`.
- Falha ao montar o calendário: o `/api/health` mostra `calendar.status = "unavailable"` e continua respondendo.

### Testes (`backend/tests/test_calendar.py`)

- O calendário do servidor confere com a tabela oficial da NYSE de 2026 e 2027 (feriados e fechamentos às 13h).
- A tabela embutida em cada um dos seis motores confere com o calendário do servidor.
- O teste `test_official_reference_is_current` falha quando o ano atual passar de 2027, para obrigar a conferência da nova tabela publicada pela NYSE.
- Detalhes de um dia comum, de um fechamento antecipado, de um feriado e de um fim de semana.
- Estado aberto/fechado em minutos conhecidos.
- Rotas: calendário sem preços, `/api/health`, Time Machine e plano ORB recusando feriado, fim de semana e ano não coberto, sem criar tarefa.

### Observações para a hospedagem

`exchange_calendars` depende de `pandas` e `numpy`. Eles só são importados na primeira consulta
ao calendário, mas aumentam o tempo de instalação e o uso de memória no Render gratuito (512 MB).

---

## Política de exibição (Bloco 2)

Código: `backend/app/services/policy.py`. Configuração compartilhada, aplicada pela API.

| Variável | Padrão no `demo` | Padrão no `public` | Efeito quando desligada |
|---|---|---|---|
| `DP_SHOW_RAW_PRICES` | ligada | desligada | `/api/assets/{s}/chart` e `/api/snapshots/{id}/bars` respondem 403 `display_policy`; `/api/quotes` devolve `last`, `volume`, `avg_volume` nulos e `spark` vazio (mantém variação do dia e volatilidade); resultados de varredura sem `price` e `volume` |
| `DP_SHOW_TRIGGER_PRICES` | ligada | desligada | Ainda sem efeito nas rotas: ocultar o preço do gatilho exige refazer o fluxo do Time Machine (proposta pendente de aprovação) |
| `DP_PELOSI_PUBLIC` | desligada | desligada | Reservada para o Bloco 10 |
| `DP_ALLOW_UNOFFICIAL_SOURCES` | ligada | desligada | Yahoo recusado com 503 `source_disabled`: gráficos, cotações, notícias, varreduras e Time Machine/backtest sem snapshot. Snapshots já salvos continuam utilizáveis |

Linha em branco no `.env` = padrão do modo.

## Cotas compartilhadas e circuit breaker

Código: `backend/app/services/providers.py`. Estado em memória do processo (uma instância no Render
gratuito); um reinício zera os contadores.

| Provedor | Limite local por minuto | Por dia | Limite publicado |
|---|---|---|---|
| Yahoo Finance | 60 | 3.000 | não publicado |
| SEC EDGAR | 300 | 20.000 | 10 por segundo |
| Nasdaq Trader | 6 | 60 | não publicado |
| Alpaca | 150 (1 por página de até 10.000 candles) | sem limite local | 200 por minuto |

- HTTP 429 pausa o provedor por 120 s; três falhas seguidas pausam por 30 s (`provider_paused`).
- Downloads idênticos em andamento são feitos uma vez e compartilhados (single-flight).
- Chamadas que os motores fazem sozinhos (scanner, news, analyst, universo) são cobradas antes de
  rodar, por estimativa: scanner diário = 1 por 20 ativos; news = 1 Yahoo + 2 SEC; analyst = 4 SEC;
  universo = 2 Nasdaq Trader.
- Estado e uso aparecem em Configurações → Fontes de dados, sem chaves.

## Proveniência

- `providers.provenance_for_source()` descreve a origem de um snapshot a partir do campo `source`:
  provedor, tipo (oficial, não oficial, biblioteca, comercial), atraso, termos, atribuição e se é fixture.
- O hash do snapshot continua sendo o do conteúdo baixado. A proveniência fica ao lado, em
  `results.snapshot.provenance` de cada experimento; experimentos antigos recebem o campo na leitura.
- Execuções feitas com Yahoo continuam identificadas como Yahoo.
- Execuções com Alpaca ficam identificadas como `alpaca:iex` (provedor `alpaca`, `feed: iex`).

---

## Alpaca Market Data, plano Basic, feed SIP ou IEX (Bloco 3)

Categoria B: o usuário cria a conta e as chaves. Sem chaves, o provedor fica `missing_key` e nada muda.

| Item | Valor |
|---|---|
| Documentação usada (30 e 31/10/2026) | https://docs.alpaca.markets/reference/stockbars, https://docs.alpaca.markets/us/reference/stockbarsingle-1, https://docs.alpaca.markets/us/docs/about-market-data-api.md, https://docs.alpaca.markets/us/docs/market-data-faq |
| Endpoint | `GET https://data.alpaca.markets/v2/stocks/bars`, cabeçalhos `APCA-API-KEY-ID` e `APCA-API-SECRET-KEY` |
| Parâmetros enviados | `symbols`, `timeframe=5Min`, `start`, `end` (ambos inclusivos), `limit=10000`, `adjustment=all`, `feed=sip` (ou `iex`), `sort=asc`, `page_token` |
| Feed | `DP_ALPACA_FEED` = `sip` (padrão) ou `iex`. Segundo a FAQ da Alpaca, sem assinatura o SIP histórico pode ser consultado quando o `end` tem pelo menos 15 minutos. O adaptador nunca pede dados com menos de 16 min, então o plano gratuito serve o SIP (consolidado de todas as bolsas). No exemplo da própria FAQ (AAPL, 29/09/2023), o volume diário IEX foi 923.134 contra 51.861.083 no SIP (~1,8%). |
| Código | `backend/app/services/alpaca.py`; escolha do provedor em `providers.bars_provider()`; jobs em `services/tasks.py` |
| Uso | Candles de 5 min de execuções novas do Time Machine, dos backtests ORB e do plano ORB (Bloco 4). Candles diários continuam no Yahoo. |
| Escolha | `DP_INTRADAY_PROVIDER` = `auto` (padrão: Alpaca quando há as duas chaves), `alpaca` ou `yahoo` |
| Janela | `history_sessions` (20 a 250, padrão 60) sessões da NYSE. Time Machine: N sessões antes do dia do plano + o próprio dia. Backtest ORB: as últimas N sessões já encerradas. Ignorado com snapshot ou com Yahoo. |
| Persistência | Snapshot `source = "alpaca:sip"` ou `"alpaca:iex"`, `range = "<N>sess"`, arquivo no bucket privado como os demais. Snapshots `alpaca:iex` antigos continuam reproduzíveis com o próprio rótulo. |
| Frequência | Sob demanda, uma coleta por execução sem snapshot. Sem execução periódica. |
| Falhas | recusa de assinatura (corpo com `subscription` ou código 42210000, em 403 ou 422) `provider_subscription`, sem acionar o circuit breaker; 401/403 `provider_auth`; 429 `rate_limited` (pausa 120 s); 400/422 `provider_bad_request` com o texto curto da Alpaca; outros `provider_error`; rede `provider_unreachable`/`provider_timeout`. A tarefa falha com o motivo. Não há troca para o Yahoo. |
| Segredos | Só nos cabeçalhos. Mensagens de erro passam por `scrub()`, que remove chave e secret. `scripts/check_alpaca.py` não imprime nenhum trecho das chaves. |

### Conversão para o formato dos motores

As barras viram o layout do Yahoo v8 (`chart.result[0].meta/timestamp/indicators.quote`), que os
motores já leem; nenhum motor foi editado.

- `timestamp`: o `t` da Alpaca (início da barra, UTC), sem alteração. Barras fora do pregão regular
  (pré e pós-mercado) ficam de fora e são contadas em `meta.leftOut`.
- `data_end`: instante na grade de 5 min, nunca depois do fechamento da última sessão nem de
  agora − 16 min (o plano Basic restringe os 15 min mais recentes). Só se pedem barras que começam
  antes dele (`end = data_end − 1 s`), e o conversor descarta qualquer uma que venha depois.
- `meta.regularMarketTime = data_end`, não o horário da coleta. O motor só considera completa a
  barra que termina até esse instante, e todas as barras guardadas terminam até ele.
- `meta.symbol` no formato do Yahoo (`BRK-B`) e `dataGranularity = "5m"`, que o motor confere.

### O que entra no hash do snapshot

O hash é o SHA-256 do texto JSON canônico (chaves ordenadas, separadores fixos, ASCII). Participam:
as barras guardadas (timestamp, open, high, low, close, volume), `meta.symbol`, `dataGranularity`,
`exchangeTimezoneName`, `currency`, `regularMarketTime` (= `data_end`), `dataProvider`, `feed`
(SIP e IEX geram hashes diferentes),
`adjustment`, `window` (dia do plano, lista de sessões, início, `data_end`, sessões pedidas) e
`leftOut`. Não participam: o horário da coleta (fica na coluna `fetched_at`), a ordem em que as
barras chegaram, os campos `n` e `vw` da Alpaca, o relatório de qualidade (recalculado do texto) e a
proveniência (derivada de `source`). Assim, duas coletas da mesma janela com os mesmos dados geram
o mesmo snapshot. Com `adjustment=all`, um desdobramento ou dividendo posterior muda os preços
antigos e, portanto, o hash. O teste `test_golden_hash_is_stable` fixa o hash de uma entrada fixa (um para IEX, um para SIP).

### Qualidade dos dados (`results.data_quality`)

Horário sem nenhum negócio no feed não tem candle: raro no SIP para ações listadas, comum no IEX
(uma bolsa só). Nada é preenchido. Por sessão: `closed` (encerrada até `data_end`; menos candles que o esperado = lacuna),
`in_progress` (o `data_end` cai dentro dela; o esperado são só os horários já encerrados, e ela não
conta como incompleta) ou `not_started`. Esperado: 78 candles, ou 42 num fechamento às 13h.
`pool_sessions` = sessões encerradas com 78 candles antes do dia do plano, as que o motor usa.

Antes de chamar o motor, o Time Machine recusa com motivo claro: candle de entrada ausente
(`entry_bar_missing`, distinguindo lacuna do feed de sessão ainda em andamento) e menos de 20 sessões
completas (`not_enough_sessions`). O motor continua checando por conta própria.

### Consumo de cota

A Alpaca devolve também barras de pré e pós-mercado (descartadas depois). Estimativa: até ~192
barras por sessão → 60 sessões ≈ 2 chamadas; 250 sessões ≈ 5 chamadas. Reproduzir por snapshot
não chama a Alpaca.

### Testes (`backend/tests/test_alpaca.py`)

Todos com a fixture DERIVADA de `tests/alpaca_fixtures.py` (barras do arquivo TSLA da skill
reescritas no formato da Alpaca; não coletadas) e uma camada HTTP falsa. Cobrem: janela por sessões
(feriado, fechamento antecipado, dia em andamento, antes da abertura, limites 20–250), JSON
determinístico e hashes fixos (IEX e SIP), timestamps preservados e `regularMarketTime = data_end`, mesmo resultado
do Time Machine (seed 19) que o arquivo original, paginação, cota, erros 400/401/403/429/500 e de
rede sem chaves nas mensagens, lacunas contadas e não preenchidas, candle de entrada ausente,
histórico curto, ponta a ponta na API (snapshot `alpaca:sip`, proveniência, `data_quality`,
reprodução sem nova coleta), backtest ORB, escolha por configuração e ausência de troca silenciosa,
`DP_ALPACA_FEED=iex` de ponta a ponta (e reprodução de um snapshot IEX com o padrão já em SIP),
recusa de assinatura sem culpar as chaves.
O teste real (`test_live_alpaca_smoke`) só roda com `DP_LIVE_ALPACA=1` e chaves em `backend/.env`.

### Pendente

- Teste real com chaves no Windows do usuário: `scripts/check_alpaca.py` (testa SIP e IEX e mostra
  o volume de cada um) e `DP_LIVE_ALPACA=1`. Confirma o que a documentação não diz explicitamente:
  que `t` é o início da barra (9:30 → 13:30Z no horário de verão), e que o SIP com mais de 15 min
  responde sem assinatura. Se o SIP for recusado, `DP_ALPACA_FEED=iex` volta ao comportamento anterior.
- Confirmação por escrito da Alpaca sobre uso do plano Basic num site público (só cálculo no servidor).

---

## Plano ORB: trader-entry + trader-exit com as barras do dia (Bloco 4)

`POST /api/plan/orb` aceita um snapshot (como antes) ou só `symbol` + `date`. Sem snapshot, baixa
apenas o pregão regular do dia do plano pelo provedor de 5 min (`DP_INTRADAY_PROVIDER`, o mesmo do
Time Machine), congela um snapshot e só então chama os motores. Nenhum motor foi editado.

| Item | Valor |
|---|---|
| Código | `backend/app/services/day_bars.py`; `alpaca.fetch_day_chart()`; rota em `routers/lab.py` |
| Alpaca | Uma chamada, janela de uma sessão (`range = "1sess"`), mesmo conversor, hash e `data_quality` do Bloco 3 |
| Yahoo | O menor período que contém o dia: `1d` (hoje), `5d` (até 6 dias), `60d` (até 58 dias); mais antigo → 422 `out_of_range` |
| Snapshot | Endereçado por conteúdo: o mesmo dia já encerrado reaproveita a mesma linha. Auditoria `download`/`snapshot` com `purpose = plan.orb` |
| Stops | `or_mid`, `or_low`, `pct` e, novo, `atr` com `atr_k` (0,25 a 10, padrão 1,5): K × ATR de 14 candles da sessão até o candle de entrada, pelo leitor e pelo `atr_of` do próprio trader-exit. Com menos de 3 candles fechados até a entrada (só com lacunas no feed), recusa com motivo |
| Avaliação | No menor entre 16:05 ET e o `regularMarketTime` dos dados. Antes, uma sessão em andamento cujos dados acabam às 10:00 era lida às 16:05 e aparecia como "expired"; agora aparece como "waiting" |
| Resposta | Plano, faixa, gatilho, `stop_detail`, `reward_risk`, ATR, `snapshot` (com proveniência e feed), `data_quality` (Alpaca), `evaluated_at` e notas |
| Política | Com `DP_SHOW_TRIGGER_PRICES` desligado (padrão do `public`) e dados que não sejam a referência do pacote, o plano volta em R e % (ver "Exibição em R"), com `plan_rule` para rodar o Time Machine no servidor |
| Falhas | Provedor desligado/sem chave/pausado → 503; erro da Alpaca → 502 com o código; janela inválida, sem dados ou dia ainda não liberado → 422. Sem troca para o Yahoo |

Limite conhecido: o histórico do Time Machine (`history_replay`) não conhece stop por ATR. Com um
plano ATR, ele reexecuta as sessões passadas com o mesmo stop em % da entrada (regra `pct` do
próprio motor), e a resposta do plano avisa isso.

Consumo de cota: 1 chamada da Alpaca por plano sem snapshot (cerca de 80 a 190 barras, uma página).

Testes (`backend/tests/test_plan_orb.py`, fixtures): números de referência da skill (or-mid 358,32 /
370,04; atr:1.5 359,35 / 373,84 com ATR 3,2182 sobre 9 candles), download só do dia (uma chamada,
`start` na abertura e `end` = `data_end` − 1 s), snapshot reaproveitado, recálculo pelo snapshot sem
nova coleta, sessão em andamento como "waiting", recusa do ATR com menos de 3 candles, erros sem
chaves, validação, Yahoo com o período mais curto e a política do modo público.

---

## Exibição em R no modo público (aprovada em 31/10/2026)

Com `DP_SHOW_TRIGGER_PRICES` desligado (padrão do `public`), nada que venha de preços de um provedor
sai da API em dólares. O banco guarda os números completos (para reproduzir); a conversão é feita na
saída por `backend/app/services/price_view.py`. Execuções sobre a referência do pacote (arquivo TSLA
da skill, MIT) continuam em dólares.

| Onde | O que muda |
|---|---|
| `POST /api/plan/orb` | Plano em R e % da entrada (0R, −1R, +xR; `stop_pct`, `target_pct`, `risk_pct`, `atr_pct`), faixa de abertura em % da entrada, gatilho sem preço nem volume, `plan_rule` |
| `POST /api/timemachine` | Aceita `plan_rule` no lugar de entrada/stop/alvo: o job calcula o plano (trader-entry + trader-exit) no dia do plano dentro do mesmo snapshot. Sem disparo → falha `plan_not_triggered` com o motivo |
| `GET /api/experiments/{id}` e export JSON/CSV | Plano em R; Monte Carlo (mediana, p5, p95, faixas, caminhos, histograma) em R (`mc.unit = "R"`); trades sem preços (só R, datas, resultado); avisos do motor que citam preços são omitidos; CSV sem colunas de preço |
| `GET /api/experiments`, `GET /api/jobs/{id}` | `params` sem entrada/stop/alvo |
| `GET /api/assets/{s}/relative` (novo) | Para o Scanner: retorno acumulado em %, RSI 14, distância da MM20 em %, ATR 14 e histograma do MACD em % do preço. Sem OHLC nem volume |
| Frontend | Time Machine: "Plano calculado e guardado no servidor", leque e histograma em R, tabela sem colunas de preço, dimensionamento oculto. Scanner: gráfico de retorno % no lugar dos candles quando `DP_SHOW_RAW_PRICES` está desligado. Dashboard: o minigráfico já saía no Bloco 2 |

Testes: `backend/tests/test_price_view.py` e `test_plan_orb.py` (fluxo público completo: plano →
Time Machine pela regra → experimento, trades, job, lista e exports sem nenhum preço do provedor;
mesma simulação pela regra e pelos preços digitados).

---

## Alertas: trader-alerts sob demanda, cotações de vários símbolos (Bloco 5)

`POST /api/alerts/check` recebe as regras do visitante (formato do próprio trader-alerts: `above`,
`below`, `stop`, `target`, `pct_move`, `opening_bell`, `time`; até 50) e o estado do que já disparou.
As regras e o estado ficam no navegador (`localStorage`). O servidor busca as cotações, chama o
`evaluate` do motor (puro, sem edição) e devolve o que disparou e o novo estado. Nada roda sozinho e
nada é enviado para fora (sem e-mail, push ou webhook). A dica de `trader-broker` que o motor inclui
nas mensagens é removida: o laboratório não tem corretora.

| Item | Valor |
|---|---|
| Código | `routers/alerts.py`, `services/quotes.py`, `alpaca.fetch_snapshots()`; schema `AlertCheckRequest` |
| Alpaca | `GET https://data.alpaca.markets/v2/stocks/snapshots?symbols=A,B,...&feed=...` (https://docs.alpaca.markets/reference/stocksnapshots-1): uma requisição para até 100 símbolos. Usa `latestTrade.p` (ou `dailyBar.c`), `dailyBar` e `prevDailyBar.c`. A página de referência não mostra o corpo; o parser aceita o exemplo da v2 (chaves por símbolo no topo) e um envelope `snapshots`. O teste real confirma qual (o `check_alpaca.py` informa o formato) |
| Feed | `DP_ALPACA_QUOTE_FEED` = `delayed_sip` (padrão: consolidado com 15 min de atraso, na lista de feeds da referência) ou `iex` (tempo real, uma bolsa) |
| Provedor | `DP_QUOTE_PROVIDER` = `auto` (Alpaca com chaves, senão Yahoo), `alpaca` ou `yahoo`. Sem troca automática |
| Yahoo | Uma requisição por símbolo pela cota de `market_data.fetch_chart_raw` (`1d`/`5m`), lida pelo `parse_yahoo` do próprio motor. Sujeito a `DP_ALLOW_UNOFFICIAL_SOURCES` |
| Stooq | Não é usado (o endpoint respondia 404 quando a skill foi escrita e não é uma API documentada). O motor continua com o código, sem edição |
| Política | Com `DP_SHOW_RAW_PRICES` desligado, as mensagens trocam os preços por `[preço oculto]` e as cotações saem só com a variação %. A comparação usa os preços no servidor |
| Falhas | Provedor desligado/sem chave/pausado/429 → 503; outros erros da Alpaca → 502 com o código (`provider_subscription` se o feed não for coberto); símbolo sem cotação → item em `errors`, os outros seguem |
| Frontend | Painel "Alertas" no Dashboard: adicionar (acima de, abaixo de, variação %), sino de abertura, "Verificar agora". Sem verificação automática |

Consumo de cota: 1 chamada da Alpaca por verificação (até 100 símbolos); no Yahoo, 1 por símbolo.

Testes (`backend/tests/test_alerts_api.py`, fixtures; `frontend/src/components/app/AlertsPanel.test.tsx`):
uma requisição para todos os símbolos e feed padrão, envelope e feed IEX, símbolo sem cotação, regras
de outro dia sem download, nada dispara duas vezes com o estado devolvido, erros 403 de assinatura,
401, 429 e 500 sem chaves, caminho Yahoo idêntico ao motor lendo os mesmos arquivos salvos da skill,
validação (campos extras, preço negativo, horário inválido, mais de 50 regras), política do modo
público e o painel guardando as regras no navegador e verificando só quando pedido.

---

## Scanner diário e ORB com barras da Alpaca (Bloco 6)

O trader-scanner aceita um pacote offline `{TICKER: gráfico v8}`. Com a Alpaca, o servidor baixa as
barras de todos os ativos (vários por requisição), monta esse pacote e chama o motor com `--offline`
e `--now`/`--at`. O motor não foi editado; as regras (setups diários, faixa de abertura, "todos os
candles até o corte") são as dele.

| Item | Valor |
|---|---|
| Código | `alpaca.fetch_bars_multi()`, `alpaca.scanner_chart()`, `alpaca.daily_window()`; job `_run_scan` em `services/tasks.py` (`scan.daily` e `scan.orb`) |
| Requisição | `GET /v2/stocks/bars` com até 200 símbolos por série de páginas (`limit=10000` conta barras de todos), `feed=sip` (ou `DP_ALPACA_FEED`), `adjustment=all` |
| Diária | `timeframe=1Day`, 70 sessões até agora − 16 min. `meta.regularMarketPrice/regularMarketVolume` = fechamento e volume da última barra (o que o filtro de liquidez do motor lê; com SIP o volume é o consolidado). Uma sessão em andamento chega como barra parcial e o próprio motor a descarta até o fechamento |
| ORB | `timeframe=5Min` do pregão escolhido (padrão: hoje) da abertura até o corte. Corte padrão: agora (no máximo agora − 16 min, arredondado à grade de 5 min) ou 15:30 para um dia passado; um corte ainda não liberado falha com `not_available_yet`. O motor confere "todos os candles de 9:30 ao corte" |
| Yahoo | `DP_SCAN_PROVIDER=yahoo` (ou sem chaves): o motor lê o spark do Yahoo sozinho, como antes; ORB só do pregão de hoje |
| Política | Com `DP_SHOW_RAW_PRICES` desligado: `price`, `volume`, `or_high` e `or_low` saem nulos; ficam padrão, horário do gatilho, % acima da faixa e RSI |
| Frontend | Scanner: "Diária (pré-abertura)" ou "ORB (5 min)" com faixa, pregão e corte; colunas do ORB (gatilho, % acima da faixa, fechamento, faixa) |

Consumo de cota: diária ≈ 1 chamada a cada 140 ativos (70 barras); ORB ≈ 1 chamada a cada 125
ativos com o corte no fim do dia (menos de manhã). Universo de 6.000 ativos: ~45 a 50 chamadas,
abaixo do limite de 150/min configurado.

Testes (`backend/tests/test_scanner_alpaca.py`, fixtures DERIVADAS de `tests/scanner_fixtures.py`;
o oráculo é o motor lendo os arquivos ORIGINAIS da skill): diária com os mesmos padrões e preços que
o motor no spark original (19 ativos); paginação e lotes; filtro de liquidez pelo volume da última
barra; ORB de 19/10 às 10:15 com as mesmas 42 rupturas do motor no `wall5m` original (TSLA 364,18 às
10:15, faixa até 362,18), em 2 lotes; corte ao vivo limitado ao atraso do plano gratuito; Yahoo só
hoje; validação; política do modo público.

---

## Notícias: SEC 8-K + GDELT, Yahoo RSS só onde permitido (Bloco 7)

`GET /api/assets/{s}/news?hours=168` (1 a 2160). O trader-news não foi editado: o servidor passa
ao `collect` do motor o próprio "fetcher" (`services/news.py`), que manda cada requisição pela cota
compartilhada, põe o `SEC_USER_AGENT` nas chamadas da SEC e responde "desligado" ao RSS do Yahoo
quando `DP_ALLOW_UNOFFICIAL_SOURCES` está desligado (padrão do `public`). Os parsers do motor
(`parse_sec_atom`, `tag`, `dedupe`) montam os itens.

| Fonte | Como | Categoria |
|---|---|---|
| SEC EDGAR 8-K | `https://www.sec.gov/cgi-bin/browse-edgar?...&type=8-K&output=atom` (URL do próprio motor), com `SEC_USER_AGENT`; `company_tickers.json` baixado no máximo 1 vez por dia e guardado em disco (`DP_DATA_DIR/cache`). Cota local 300/min (a SEC publica 10/s) | A (oficial) |
| GDELT DOC 2.0 | `GET https://api.gdeltproject.org/api/v2/doc/doc` com `query="<nome>" sourcelang:english`, `mode=ArtList` (25 manchetes, 7 dias, `sort=DateDesc`) e `mode=TimelineTone` (tom médio). Nome da empresa = título da lista da SEC sem sufixos (Inc., Corp., Co...). Cache de 15 min; cota local 10/min. Cada manchete leva o link original e o veículo; atribuição "GDELT Project" na resposta e na tela | A (aberto, sem chave) |
| Yahoo RSS | Só com `DP_ALLOW_UNOFFICIAL_SOURCES` ligado (demo local). No `public` nem é chamado | não oficial |

Ressalva: a página de referência do GDELT (https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)
não abre no ambiente em que isto foi escrito. Os parâmetros e campos (`articles[].url/title/
seendate/domain/language/sourcecountry`, `timeline[].data[].value`) foram conferidos em vários
clientes de terceiros. Confirmar no teste real.

Sem `SEC_USER_AGENT`: sem 8-K e sem GDELT (o nome da empresa vem da SEC), com aviso. O tom é a
medida do GDELT sobre o texto das notícias, mostrado como número com explicação, nunca como sinal.
Falha de uma fonte não derruba as outras: vai para `errors`.

Testes (`backend/tests/test_news_api.py`): itens da SEC e do Yahoo iguais aos do motor lendo os
mesmos arquivos salvos da skill; GDELT (resposta ESCRITA À MÃO no formato documentado) com link,
veículo e horário, link inseguro descartado, tom médio; consulta pelo nome da empresa; User-Agent
nas chamadas da SEC; lista de tickers baixada uma vez e GDELT em cache; GDELT recusando sem derrubar
a SEC; sem User-Agent; modo público sem chamar o Yahoo; ticker desconhecido; limpeza do nome.

---

## Universo: metadados da SEC (Bloco 8)

`GET /api/assets/{s}/profile` (`services/sec_profile.py`): CIK, nome registrado, bolsas, SIC e
descrição, setor = divisão SIC, fim do ano fiscal, categoria do emissor, estado de constituição e
link para a página da empresa no EDGAR. Exige `SEC_USER_AGENT` (sem ele: 424). O universo de ações
continua vindo da Nasdaq Trader (`scan.py universe`).

| Item | Valor |
|---|---|
| CIK e nome | `https://www.sec.gov/files/company_tickers.json` (o mesmo arquivo do Bloco 7, 1 vez por dia) |
| Bolsas, SIC, categoria | `https://data.sec.gov/submissions/CIK##########.json`, documentado em https://www.sec.gov/edgar/sec-api-documentation (nome, nomes anteriores, bolsas e tickers). Os campos `sic`, `sicDescription`, `category`, `fiscalYearEnd`, `stateOfIncorporation` são os lidos por todas as bibliotecas cliente; o arquivo de submissões salvo na skill é um trecho sem eles. Confirmar no teste real |
| Setor | Divisão do Manual SIC (https://www.osha.gov/data/sic-manual) pelos dois primeiros dígitos: A 01–09, B 10–14, C 15–17, D 20–39, E 40–49, F 50–51, G 52–59, H 60–67, I 70–89, J 91–97, K 99. Faixas sem divisão (18–19, 68–69, 98) ficam sem setor |
| Cache | Submissões em disco por 7 dias, sem o histórico de filings (`DP_DATA_DIR/cache/sec_submissions`) |
| Fora | Valor de mercado (só uso interno, não calculado) e free float, conforme o relatório de provedores |
| Frontend | Detalhe do ativo no Scanner: setor, SIC, bolsas e CIK com link para a SEC |

Consumo: 1 chamada à SEC por ativo a cada 7 dias (mais a lista de tickers, 1 por dia).

Testes (`backend/tests/test_sec_profile.py`): perfil a partir dos arquivos salvos da SEC na skill,
com os campos ausentes do trecho ACRESCENTADOS À MÃO e marcados; cache em disco sem filings e sem
nova chamada; símbolo desconhecido; erro da SEC; sem User-Agent; tabela de divisões SIC, incluindo
os limites e as faixas sem divisão.
