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
