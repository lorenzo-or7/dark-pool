import { Badge } from '@/components/ui/badge'
import { localDateTime, shortDate } from '@/lib/format'
import type { DataQuality } from '@/lib/types'

/** Coverage of an Alpaca snapshot (SIP or IEX feed): complete, incomplete (gaps, not filled) and in-progress sessions. */
export function DataQualityPanel({ q }: { q: DataQuality }) {
  const inc = q.incomplete_sessions
  return (
    <div className="mt-4 rounded-[var(--radius-md)] border border-line p-3 text-sm" aria-label="Qualidade dos dados">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-fg">Qualidade dos dados</span>
        <Badge tone="neutral">{q.provider} · {q.feed}</Badge>
        <Badge tone={q.pool_sessions >= q.engine_min_sessions ? 'up' : 'caution'}>
          {q.pool_sessions} sessões completas usadas
        </Badge>
      </div>
      <dl className="grid grid-cols-[160px_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted">Dados até</dt>
        <dd className="num text-fg/90">{localDateTime(q.data_end)}</dd>
        <dt className="text-muted">Sessões no arquivo</dt>
        <dd className="num text-fg/90">
          {q.sessions} ({q.complete_sessions} completas, {inc.length} incompletas
          {q.early_close_sessions ? `, ${q.early_close_sessions} de fechamento antecipado` : ''})
        </dd>
        <dt className="text-muted">Candles ausentes</dt>
        <dd className="num text-fg/90">{q.missing_bars_closed} em sessões encerradas · não preenchidos</dd>
        {q.in_progress_session && (
          <>
            <dt className="text-muted">Sessão em andamento</dt>
            <dd className="num text-fg/90">
              {shortDate(q.in_progress_session.date)}: {q.in_progress_session.bars} de {q.in_progress_session.expected} candles até agora
            </dd>
          </>
        )}
      </dl>
      {inc.length > 0 && (
        <p className="mt-2 text-xs text-muted">
          Sessões incompletas (fora do cálculo):{' '}
          {inc.slice(0, 8).map((s) => `${shortDate(s.date)} (${s.bars}/${s.expected})`).join(', ')}
          {inc.length > 8 ? ` e mais ${inc.length - 8}` : ''}.
        </p>
      )}
      <p className="mt-2 text-[11px] text-faint">{q.note}</p>
    </div>
  )
}
