import { useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { lazy, Suspense, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/app/AppShell'
import { KpiTile, Sparkline } from '@/components/app/KpiTile'
import type { RadarSeries } from '@/components/charts/charts'
import { Badge, DataBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/field'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { EmptyState, ErrorState, Notice, Skeleton } from '@/components/ui/states'
import { api, download } from '@/lib/api'
import { fmt, relative } from '@/lib/format'
import type { Summary } from '@/lib/types'
import { cn } from '@/lib/utils'

const charts = () => import('@/components/charts/charts')
const EquityChart = lazy(() => charts().then((m) => ({ default: m.EquityChart })))
const RHistogram = lazy(() => charts().then((m) => ({ default: m.RHistogram })))
const PeriodArea = lazy(() => charts().then((m) => ({ default: m.PeriodArea })))
const RadarScore = lazy(() => charts().then((m) => ({ default: m.RadarScore })))

type Exp = { id: string; title: string; kind: string; created_at: string; dataset: string }
type Res = { experiments: Exp[]; selected: Exp | null; dataset: string; summary: Summary; source_kind: string | null }
type Cmp = { items: { id: string; title: string; kind: string; summary: Summary; period: { from: string | null; to: string | null } }[]; same_period: boolean; warning: string | null }

const COLORS = ['#ff4103', '#7fb6d1', '#3ecf8e', '#f0b445']

const AXES = [
  { key: 'win', label: 'Acerto' },
  { key: 'payoff', label: 'Payoff' },
  { key: 'pf', label: 'Profit factor' },
  { key: 'exp', label: 'Expectativa' },
  { key: 'dd', label: 'Drawdown' },
  { key: 'n', label: 'Amostra' },
]

function scores(s: Summary) {
  const c = (x: number) => Math.max(0, Math.min(100, x))
  return {
    win: c((s.win_rate ?? 0) * 100),
    payoff: c(((s.payoff_ratio ?? 0) / 3) * 100),
    pf: c(((s.profit_factor ?? 0) / 3) * 100),
    exp: c((((s.avg_r ?? -1) + 1) / 2) * 100),
    dd: c(100 - (s.max_drawdown_r / 10) * 100),
    n: c((s.trades / 100) * 100),
  }
}

/** Progress Metric Card (after makviesainte; source needs a 21st.dev login): headline figure, progress and a switchable curve/bars view. */
function ProgressMetric({ s }: { s: Summary }) {
  const [view, setView] = useState<'bars' | 'curve'>('bars')
  const months = s.by_month
  const pct = months.length ? s.positive_months / months.length : 0
  const max = Math.max(1, ...months.map((m) => Math.abs(m.sum_r)))
  return (
    <div className="panel flex flex-col gap-3 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[13px] text-muted">Consistência entre períodos</p>
          <p className="num mt-1 text-[28px] leading-none text-fg">
            {s.positive_months}/{months.length}
            <span className="ml-1 text-base text-muted">meses positivos</span>
          </p>
        </div>
        <SegmentedControl label="Visualização" size="sm" value={view} onChange={setView} options={[{ value: 'bars', label: 'Barras' }, { value: 'curve', label: 'Curva' }]} />
      </div>
      <div className="h-1.5 rounded-full bg-line" role="progressbar" aria-valuenow={Math.round(pct * 100)} aria-valuemin={0} aria-valuemax={100} aria-label="Meses positivos">
        <div className="h-1.5 rounded-full bg-ember" style={{ width: `${pct * 100}%` }} />
      </div>
      {view === 'bars' ? (
        <div className="flex h-24 items-center gap-1" aria-hidden>
          {months.map((m) => (
            <div key={m.month} className="flex h-full flex-1 flex-col justify-center" title={`${m.month}: ${fmt.r(m.sum_r, 2)}`}>
              <div className="flex h-1/2 items-end">
                {m.sum_r > 0 && <div className="w-full rounded-t-[2px] bg-up/70" style={{ height: `${(m.sum_r / max) * 100}%` }} />}
              </div>
              <div className="flex h-1/2 items-start border-t border-line-strong">
                {m.sum_r < 0 && <div className="w-full rounded-b-[2px] bg-down/70" style={{ height: `${(-m.sum_r / max) * 100}%` }} />}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <Sparkline values={months.reduce<number[]>((acc, m) => [...acc, (acc.at(-1) ?? 0) + m.sum_r], [])} className="h-24 w-full" />
      )}
      <p className="text-[11px] text-faint">Soma de R por mês, na ordem cronológica.</p>
    </div>
  )
}

function Compare({ exps }: { exps: Exp[] }) {
  const [ids, setIds] = useState<string[]>(() => exps.slice(0, 2).map((e) => e.id))
  const q = useQuery({
    queryKey: ['compare', ids.join(',')],
    queryFn: ({ signal }) => api<Cmp>(`/analytics/compare?ids=${ids.join(',')}`, { signal }),
    enabled: ids.length > 0,
  })
  const series: RadarSeries[] = (q.data?.items ?? []).map((it, i) => ({ name: it.title.slice(0, 40), color: COLORS[i % COLORS.length], values: scores(it.summary) }))
  return (
    <section className="panel p-4 sm:p-5" aria-labelledby="cmp-h">
      <h2 id="cmp-h" className="text-base font-medium text-fg">
        Comparar experimentos
      </h2>
      <p className="mt-1 text-xs text-muted">Escolha até 4. Compare apenas experimentos com o mesmo período e a mesma base de dados.</p>
      <fieldset className="mt-3 flex flex-wrap gap-2">
        <legend className="sr-only">Experimentos para comparar</legend>
        {exps.slice(0, 20).map((e) => {
          const on = ids.includes(e.id)
          return (
            <label key={e.id} className={cn('flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-xs', on ? 'border-ember/50 text-fg' : 'border-line-strong text-muted hover:text-fg')}>
              <input
                type="checkbox"
                className="accent-[#ff4103]"
                checked={on}
                disabled={!on && ids.length >= 4}
                onChange={() => setIds((x) => (on ? x.filter((y) => y !== e.id) : [...x, e.id]))}
              />
              <span className="max-w-[220px] truncate">{e.title}</span>
            </label>
          )
        })}
      </fieldset>
      {q.data?.warning && (
        <Notice tone="caution" className="mt-3">
          {q.data.warning}
        </Notice>
      )}
      {q.isError && <ErrorState error={q.error} className="mt-3" />}
      {q.data && q.data.items.length > 0 && (
        <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_380px]">
          {/* Inline Analytics Table (after ruixen.ui; source needs a 21st.dev login) */}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] text-sm">
              <caption className="sr-only">Métricas por experimento</caption>
              <thead>
                <tr className="text-left text-[11.5px] text-faint">
                  <th className="pb-2 font-normal">Experimento</th>
                  <th className="pb-2 text-right font-normal">Ops.</th>
                  <th className="pb-2 text-right font-normal">Acerto</th>
                  <th className="pb-2 text-right font-normal">Média</th>
                  <th className="pb-2 text-right font-normal">PF</th>
                  <th className="pb-2 text-right font-normal">DD</th>
                  <th className="pb-2 pl-3 font-normal">Curva</th>
                </tr>
              </thead>
              <tbody>
                {q.data.items.map((it, i) => (
                  <tr key={it.id} className="border-t border-line">
                    <td className="max-w-[240px] py-2.5 pr-3">
                      <span className="mr-2 inline-block size-2 rounded-full" style={{ background: COLORS[i % COLORS.length] }} aria-hidden />
                      <Link to={`/app/analytics?exp=${it.id}`} className="text-fg hover:text-ember">
                        {it.title}
                      </Link>
                      <p className="num text-[11px] text-faint">
                        {it.period.from ?? '—'} → {it.period.to ?? '—'}
                      </p>
                    </td>
                    <td className="num py-2.5 text-right">{it.summary.trades}</td>
                    <td className="num py-2.5 text-right">{fmt.pct(it.summary.win_rate)}</td>
                    <td className="num py-2.5 text-right">{fmt.r(it.summary.avg_r, 2)}</td>
                    <td className="num py-2.5 text-right">{fmt.num(it.summary.profit_factor)}</td>
                    <td className="num py-2.5 text-right">{fmt.num(it.summary.max_drawdown_r)}R</td>
                    <td className="py-2.5 pl-3">
                      <Sparkline values={it.summary.equity.map((p) => p.cum_r)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <Suspense fallback={<Skeleton className="h-[280px]" />}>
              <RadarScore axes={AXES} series={series} height={280} />
            </Suspense>
            <p className="text-[11px] leading-relaxed text-faint">
              Escala 0–100: acerto em %; payoff e profit factor até 3 = 100; expectativa de −1R (0) a +1R (100); drawdown 0R = 100 e 10R = 0; amostra 100 operações = 100.
            </p>
          </div>
        </div>
      )}
    </section>
  )
}

export default function Analytics() {
  const [sp, setSp] = useSearchParams()
  const [dataset, setDataset] = useState<'all' | 'development' | 'out_of_sample'>('all')
  const exp = sp.get('exp')
  const q = useQuery({
    queryKey: ['analytics', exp, dataset],
    queryFn: ({ signal }) => api<Res>(`/analytics?dataset=${dataset}${exp ? `&experiment_id=${exp}` : ''}`, { signal }),
  })
  const s = q.data?.summary
  const sel = q.data?.selected
  const kind = q.data?.source_kind === 'timemachine_history' ? 'historical' : 'backtest'
  const exps = useMemo(() => q.data?.experiments ?? [], [q.data])

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader eyebrow="Resultados" title="Analytics" description="Métricas calculadas sobre as operações simuladas de cada experimento. Nada aqui mistura períodos ou bases de dados sem avisar.">
        {sel && (
          <>
            <Button size="sm" variant="ghost" onClick={() => void download(`/experiments/${sel.id}/export?format=json`, `darkpool-${sel.id.slice(0, 8)}.json`)}>
              <Download /> JSON
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void download(`/experiments/${sel.id}/export?format=csv`, `darkpool-${sel.id.slice(0, 8)}.csv`)}>
              <Download /> CSV
            </Button>
          </>
        )}
      </PageHeader>

      {q.isLoading ? (
        <Skeleton className="h-80" />
      ) : q.isError ? (
        <ErrorState error={q.error} retry={() => void q.refetch()} />
      ) : !exps.length ? (
        <EmptyState
          title="Nenhum experimento concluído"
          action={
            <Button asChild size="sm" variant="primary">
              <Link to="/app/strategies">Rodar um backtest</Link>
            </Button>
          }
        >
          As métricas aparecem depois que um backtest ou uma simulação termina.
        </EmptyState>
      ) : (
        <>
          <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:flex-wrap lg:items-center">
            <Select aria-label="Experimento" value={sel?.id ?? ''} onChange={(e) => setSp({ exp: e.target.value })} className="lg:max-w-xl">
              {exps.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.title} · {relative(e.created_at)}
                </option>
              ))}
            </Select>
            <SegmentedControl
              label="Conjunto de dados"
              value={dataset}
              onChange={setDataset}
              options={[
                { value: 'all', label: 'Tudo' },
                { value: 'development', label: 'Desenvolvimento' },
                { value: 'out_of_sample', label: 'Fora da amostra' },
              ]}
            />
            <div className="flex min-w-0 flex-wrap gap-2">
              <DataBadge kind={kind} />
              {sel?.kind === 'monte_carlo' && <Badge tone="sim">Histórico da regra no Time Machine</Badge>}
            </div>
          </div>
          {dataset !== 'all' && sel?.dataset !== 'split' && (
            <Notice tone="caution" className="mb-4">
              Este experimento não foi separado em desenvolvimento e fora da amostra. Rode o backtest com uma data de corte para usar essa visão.
            </Notice>
          )}
          {s && s.sample !== 'ok' && (
            <Notice tone="caution" className="mb-4">
              {s.sample_note}
            </Notice>
          )}
          {s && (
            <>
              {/* Analytics Bento (after romanvasnev; source needs a 21st.dev login) */}
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <KpiTile
                  label="Taxa de acerto"
                  value={s.win_rate != null ? s.win_rate * 100 : null}
                  decimals={1}
                  suffix="%"
                  empty={s.sample_note}
                  footnote={s.win_rate_ci95 ? `IC 95 %: ${fmt.pct(s.win_rate_ci95[0])} a ${fmt.pct(s.win_rate_ci95[1])}` : undefined}
                />
                <KpiTile label="Expectativa por operação" value={s.expectancy_r} decimals={3} suffix="R" empty={s.sample_note} footnote={s.std_error_r != null ? `erro padrão ${fmt.num(s.std_error_r, 3)} R` : undefined} />
                <KpiTile label="Profit factor" value={s.profit_factor} decimals={2} empty={s.losses === 0 && s.trades ? 'Sem perdas no período' : s.sample_note} footnote="ganhos brutos ÷ perdas brutas, em R" />
                <KpiTile label="Drawdown máximo" value={s.max_drawdown_r} decimals={2} suffix="R" footnote="maior queda do R acumulado" />
                <KpiTile label="Operações" value={s.trades} footnote={`${s.wins} ganhos · ${s.losses} perdas · ${s.flat} neutras`} />
                <KpiTile label="Resultado médio" value={s.avg_r} decimals={3} suffix="R" />
                <KpiTile label="Ganho médio ÷ perda média" value={s.payoff_ratio} decimals={2} footnote={`ganho ${fmt.r(s.avg_win_r, 2)} · perda ${fmt.r(s.avg_loss_r, 2)}`} />
                <KpiTile label="R acumulado" value={s.total_r} decimals={2} suffix="R" />
              </div>

              <div className="mt-4 grid gap-4 xl:grid-cols-[1.6fr_1fr]">
                <section className="panel p-4 sm:p-5" aria-labelledby="eq-h">
                  <h2 id="eq-h" className="text-base font-medium text-fg">
                    Curva de resultados
                  </h2>
                  <p className="mb-3 text-xs text-muted">R acumulado, uma operação por ponto</p>
                  {s.equity.length > 1 ? (
                    <Suspense fallback={<Skeleton className="h-[260px]" />}>
                      <EquityChart data={s.equity} height={260} />
                    </Suspense>
                  ) : (
                    <p className="text-sm text-faint">Operações insuficientes para uma curva.</p>
                  )}
                </section>
                <ProgressMetric s={s} />
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <section className="panel p-4 sm:p-5" aria-labelledby="dist-h">
                  <h2 id="dist-h" className="text-base font-medium text-fg">
                    Distribuição dos resultados
                  </h2>
                  <p className="mb-3 text-xs text-muted">Operações por faixa de R</p>
                  <Suspense fallback={<Skeleton className="h-[220px]" />}>
                    <RHistogram data={s.distribution} height={220} />
                  </Suspense>
                </section>
                <section className="panel p-4 sm:p-5" aria-labelledby="per-h">
                  <h2 id="per-h" className="text-base font-medium text-fg">
                    Evolução por período
                  </h2>
                  <p className="mb-3 text-xs text-muted">Soma de R (área) e número de operações (barras) por mês</p>
                  <Suspense fallback={<Skeleton className="h-[220px]" />}>
                    <PeriodArea data={s.by_month} height={220} />
                  </Suspense>
                </section>
              </div>
            </>
          )}

          <div className="mt-4">{exps.length > 1 ? <Compare exps={exps} /> : null}</div>
        </>
      )}
    </div>
  )
}
