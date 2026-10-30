# Integrações de dados

Registro de cada fonte de dados integrada ao DARK POOL. Uma seção por integração, preenchida
quando o bloco correspondente é entregue.

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
| Alpaca (Bloco 3) | 150 | sem limite local | 200 por minuto |

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
