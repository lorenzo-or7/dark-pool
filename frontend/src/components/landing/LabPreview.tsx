/**
 * A product-like preview of the lab. The numbers are a real Time Machine run
 * on the skill's fixed reference file, labelled as such; nothing is made up.
 */
import { Suspense, lazy } from 'react'
import { EclipseMark } from '@/brand/EclipseMark'
import { DataBadge } from '@/components/ui/badge'
import { REFERENCE_RUN as R } from '@/data/reference-run'
import { fmt } from '@/lib/format'

const FanChart = lazy(() => import('@/components/charts/charts').then((m) => ({ default: m.FanChart })))

const nav = ['Dashboard', 'Market Scanner', 'Strategy Lab', 'Time Machine', 'Analytics', 'Trading Journal']

export function LabPreview() {
  const odds = [
    { l: 'Alvo primeiro', v: R.p_target, c: 'bg-up' },
    { l: 'Stop primeiro', v: R.p_stop, c: 'bg-down' },
    { l: 'Nenhum até 16:00', v: R.p_neither, c: 'bg-muted' },
  ]
  return (
    <figure className="overflow-hidden rounded-[18px] border border-line-strong bg-abyss shadow-[0_40px_120px_-40px_rgba(0,0,0,0.8)]">
      <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <span className="size-2.5 rounded-full bg-line-strong" />
        <span className="size-2.5 rounded-full bg-line-strong" />
        <span className="size-2.5 rounded-full bg-line-strong" />
        <span className="num ml-3 truncate text-[11px] text-faint">darkpool.local/app/time-machine</span>
      </div>
      <div className="grid md:grid-cols-[200px_1fr]">
        <aside className="hidden border-r border-line p-3 md:block" aria-hidden>
          <div className="mb-5 flex items-center gap-2 px-2 pt-1">
            <EclipseMark className="size-5" />
            <span className="eyebrow text-[9px] text-fg">Dark Pool</span>
          </div>
          {nav.map((n) => (
            <div key={n} className={`relative mb-0.5 rounded-[8px] px-3 py-2 text-[12.5px] ${n === 'Time Machine' ? 'bg-raised text-fg' : 'text-muted'}`}>
              {n === 'Time Machine' && <span className="absolute top-2 bottom-2 left-0 w-0.5 rounded-full bg-ember" />}
              {n}
            </div>
          ))}
        </aside>
        <div className="min-w-0 p-4 sm:p-6">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-display text-lg text-fg">
              {R.symbol} · {R.date.split('-').reverse().join('/')} · entrada {R.entry_time} ET
            </h3>
            <DataBadge kind="simulated" />
            <DataBadge kind="fixture" />
          </div>
          <p className="num mt-1 text-xs text-muted">
            entrada {R.entry.toFixed(2)} · stop {R.stop.toFixed(2)} · alvo {R.target.toFixed(2)} · {fmt.int(R.replays)} replays · seed {R.seed} ·{' '}
            {R.pool_sessions} sessões ({R.pool_from} a {R.pool_to})
          </p>
          <div className="mt-5 grid grid-cols-3 gap-2 sm:gap-3">
            {odds.map((o) => (
              <div key={o.l} className="rounded-[var(--radius-md)] border border-line bg-surface p-3">
                <p className="text-[11px] text-muted sm:text-xs">{o.l}</p>
                <p className="num mt-1 text-lg text-fg sm:text-2xl">{fmt.pct(o.v)}</p>
                <div className="mt-2 h-1 rounded-full bg-line">
                  <div className={`h-1 rounded-full ${o.c}`} style={{ width: `${o.v * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 rounded-[var(--radius-md)] border border-line bg-surface/60 p-2 sm:p-3">
            <Suspense fallback={<div className="h-[240px]" />}>
              <FanChart bands={R.bands as unknown as number[][]} times={R.band_times as unknown as string[]} entry={R.entry} stop={R.stop} target={R.target} height={240} />
            </Suspense>
          </div>
          <p className="mt-3 text-[13px] text-fg/90">
            Mediana às 16:00 <span className="num">{fmt.price(R.median_close)}</span>, 90 % entre{' '}
            <span className="num">{R.p5_close.toFixed(2)}</span> e <span className="num">{R.p95_close.toFixed(2)}</span>. Resultado médio{' '}
            <span className="num">{fmt.r(R.avg_R)}</span>. Histórico: a regra disparou {R.history.triggered} vezes em {R.history.sessions} sessões ({R.history.target} alvo,{' '}
            {R.history.stop} stop, {R.history.close} nenhum).
          </p>
        </div>
      </div>
      <figcaption className="border-t border-line px-4 py-3 text-xs text-muted">
        Execução real do Time Machine sobre o arquivo de referência do Day Trader Skill (TSLA, 60 dias de candles de 5 min). Veredito da ferramenta:
        próximo de cara ou coroa. Simulações não são previsões.
      </figcaption>
    </figure>
  )
}
