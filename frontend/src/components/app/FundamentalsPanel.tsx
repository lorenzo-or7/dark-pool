import { fmt, shortDate } from '@/lib/format'

/** GET /api/assets/{s}/fundamentals (Bloco 9): trader-analyst on SEC data. */
export type Fundamentals = {
  result: {
    entity: string
    rows: {
      end: string
      fiscal: string
      derived: boolean
      revenue: number | null
      net_income: number | null
      eps_diluted: number | null
      gross_margin: number | null
      operating_margin: number | null
      net_margin: number | null
      revenue_yoy: number | null
      eps_yoy: number | null
      form: string
    }[]
    ttm: { revenue: number | null; net_income: number | null; eps_diluted: number | null }
  }
  filings: {
    report: { form: string; filed: string; period: string; url: string } | null
    earnings_8k: { filed: string; url: string; exhibit: string | null } | null
  } | null
  changes: string[]
  note: string | null
  earnings_history: { filed: string; url: string; items: string }[]
  earnings_history_note: string
  source: string
  disclaimer: string
}

const money = (v: number | null | undefined) => (v == null ? '—' : `US$ ${fmt.compact(v)}`)
const pct = (v: number | null | undefined) => (v == null ? '—' : `${fmt.num(v, 1)} %`)

/** Reported quarters, what changed, the latest filings and the history of earnings 8-Ks. */
export function FundamentalsPanel({ d }: { d: Fundamentals }) {
  const rows = d.result.rows
  return (
    <div className="space-y-4 text-sm">
      {rows.length === 0 ? (
        <p className="text-faint">A SEC não tem trimestres em XBRL para esta empresa.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="num w-full min-w-[720px] whitespace-nowrap text-xs">
            <caption className="sr-only">Resultados trimestrais reportados à SEC</caption>
            <thead className="text-left text-muted">
              <tr>
                {['Trimestre', 'Receita', 'Var. anual', 'Margem bruta', 'Margem operacional', 'Margem líquida', 'Lucro líquido', 'LPA diluído'].map((h) => (
                  <th key={h} scope="col" className="py-1.5 pr-3 font-normal">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((r) => (
                <tr key={r.end}>
                  <td className="py-1.5 pr-3 text-fg">
                    {r.fiscal}
                    {r.derived && <span className="ml-1 text-faint" title="4º trimestre = ano fiscal menos os três trimestres">(derivado)</span>}
                  </td>
                  <td className="pr-3">{money(r.revenue)}</td>
                  <td className={(r.revenue_yoy ?? 0) >= 0 ? 'pr-3 text-up' : 'pr-3 text-down'}>{fmt.signedPct(r.revenue_yoy, 1)}</td>
                  <td className="pr-3">{pct(r.gross_margin)}</td>
                  <td className="pr-3">{pct(r.operating_margin)}</td>
                  <td className="pr-3">{pct(r.net_margin)}</td>
                  <td className="pr-3">{money(r.net_income)}</td>
                  <td className="pr-3">{r.eps_diluted == null ? '—' : fmt.num(r.eps_diluted)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-[11px] text-faint">
            Últimos 12 meses: receita {money(d.result.ttm.revenue)} · lucro líquido {money(d.result.ttm.net_income)} · LPA {d.result.ttm.eps_diluted == null ? '—' : fmt.num(d.result.ttm.eps_diluted)}
          </p>
        </div>
      )}
      {d.changes.length > 0 && (
        <ul className="list-disc space-y-1 pl-4 text-xs text-muted">
          {d.changes.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      )}
      {d.note && <p className="text-xs text-caution">{d.note}</p>}
      {d.filings && (
        <p className="text-xs text-muted">
          {d.filings.report && (
            <a href={d.filings.report.url} target="_blank" rel="noopener noreferrer" className="hover:text-ember">
              {d.filings.report.form} do período até {shortDate(d.filings.report.period)} (arquivado {shortDate(d.filings.report.filed)})
            </a>
          )}
          {d.filings.earnings_8k && (
            <>
              {' · '}
              <a href={d.filings.earnings_8k.exhibit ?? d.filings.earnings_8k.url} target="_blank" rel="noopener noreferrer" className="hover:text-ember">
                Comunicado de resultados (8-K de {shortDate(d.filings.earnings_8k.filed)})
              </a>
            </>
          )}
        </p>
      )}
      <div>
        <p className="text-xs text-fg">Histórico de divulgação de resultados</p>
        {d.earnings_history.length ? (
          <p className="num mt-1 text-xs text-muted">
            {d.earnings_history.map((h, i) => (
              <span key={h.url}>
                {i > 0 && ' · '}
                <a href={h.url} target="_blank" rel="noopener noreferrer" className="hover:text-ember">
                  {shortDate(h.filed)}
                </a>
              </span>
            ))}
          </p>
        ) : (
          <p className="mt-1 text-xs text-faint">Nenhum 8-K com item 2.02 no histórico recente da SEC.</p>
        )}
        <p className="mt-1 text-[11px] text-faint">{d.earnings_history_note}</p>
      </div>
      <p className="text-[11px] text-faint">
        {d.source}. {d.disclaimer}
      </p>
    </div>
  )
}
