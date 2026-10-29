import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, FlaskConical, Play, Radar } from 'lucide-react'
import { lazy, Suspense, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '@/auth/AuthProvider'
import { KpiTile, Sparkline } from '@/components/app/KpiTile'
import { PageHeader } from '@/components/app/AppShell'
import { Badge, DataBadge, StatusBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/field'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { EmptyState, ErrorState, Notice, Skeleton } from '@/components/ui/states'
import { api } from '@/lib/api'
import { fmt, localDateTime, nyDateTime, relative } from '@/lib/format'
import type { Experiment, Quote, Summary, Watchlist } from '@/lib/types'

const EquityChart = lazy(() => import('@/components/charts/charts').then((m) => ({ default: m.EquityChart })))

type Dash = {
  counts: { strategies: number; experiments: number; active_jobs: number }
  recent_experiments: Experiment[]
  backtests: { id: string; title: string; created_at: string }[]
  last_data: { symbol: string; fetched_at: string; source: string; interval: string } | null
  last_scan: { created_at: string; status: string } | null
}

type AnalyticsRes = { summary: Summary; selected: { id: string; title: string; kind: string } | null }

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Bom dia' : h < 18 ? 'Boa tarde' : 'Boa noite'
}

export default function Dashboard() {
  const { me } = useAuth()
  const dash = useQuery({ queryKey: ['dashboard'], queryFn: ({ signal }) => api<Dash>('/dashboard', { signal }), refetchInterval: 15000 })
  const [expId, setExpId] = useState<string | null>(null)
  const [period, setPeriod] = useState<'all' | '6m' | '3m'>('all')
  const selected = expId ?? dash.data?.backtests[0]?.id ?? null
  const analytics = useQuery({
    queryKey: ['analytics', selected, 'all'],
    queryFn: ({ signal }) => api<AnalyticsRes>(`/analytics?experiment_id=${selected}`, { signal }),
    enabled: !!selected,
  })
  const wl = useQuery({ queryKey: ['watchlists'], queryFn: ({ signal }) => api<Watchlist[]>('/watchlists', { signal }) })
  const symbols = wl.data?.[0]?.assets.map((a) => a.symbol).slice(0, 8) ?? []
  const quotes = useQuery({
    queryKey: ['quotes', symbols.join(',')],
    queryFn: ({ signal }) => api<{ quotes: Quote[]; errors: { symbol: string; message: string }[] }>(`/quotes?symbols=${symbols.join(',')}`, { signal }),
    enabled: symbols.length > 0,
    staleTime: 120_000,
  })

  const s = analytics.data?.summary
  const equity = useMemo(() => {
    const e = s?.equity ?? []
    if (period === 'all' || !e.length) return e
    const months = period === '6m' ? 6 : 3
    const last = new Date(e[e.length - 1].date)
    last.setMonth(last.getMonth() - months)
    const cut = last.toISOString().slice(0, 10)
    return e.filter((p) => p.date >= cut)
  }, [s, period])

  const d = dash.data
  const last = d?.recent_experiments[0]

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader
        eyebrow={new Date().toLocaleDateString('pt-BR', { weekday: 'long', day: 'numeric', month: 'long' })}
        title={`${greeting()}, ${me?.display_name ?? ''}`}
        description="Resumo do laboratório: atividade recente, resultados do backtest selecionado e ativos acompanhados."
      >
        <Button asChild variant="primary">
          <Link to="/app/strategies/new">
            <FlaskConical /> Criar estratégia
          </Link>
        </Button>
        <Button asChild>
          <Link to="/app/strategies">
            <Play /> Iniciar backtest
          </Link>
        </Button>
        <Button asChild variant="ghost">
          <Link to="/app/scanner">
            <Radar /> Abrir Market Scanner
          </Link>
        </Button>
      </PageHeader>

      {dash.isError && <ErrorState error={dash.error} retry={() => void dash.refetch()} className="mb-6" />}

      {/* overview */}
      <section aria-label="Visão geral" className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3">
        <div className="panel p-4 md:col-span-1">
          <p className="text-[13px] text-muted">Último experimento</p>
          {dash.isLoading ? (
            <Skeleton className="mt-3 h-10" />
          ) : last ? (
            <Link to={last.kind === 'monte_carlo' ? `/app/time-machine?exp=${last.id}` : `/app/analytics?exp=${last.id}`} className="group mt-2 block">
              <p className="line-clamp-2 text-[15px] text-fg group-hover:text-ember">{last.title}</p>
              <div className="mt-2 flex items-center gap-2">
                <StatusBadge status={last.status} />
                <span className="text-xs text-faint">{relative(last.created_at)}</span>
              </div>
            </Link>
          ) : (
            <p className="mt-3 text-sm text-faint">Nenhum experimento ainda.</p>
          )}
        </div>
        <div className="panel p-4">
          <p className="text-[13px] text-muted">Atividade</p>
          {dash.isLoading ? (
            <Skeleton className="mt-3 h-10" />
          ) : (
            <div className="mt-2 grid grid-cols-3 gap-2">
              {[
                ['Estratégias', d?.counts.strategies],
                ['Concluídos', d?.counts.experiments],
                ['Em execução', d?.counts.active_jobs],
              ].map(([l, v]) => (
                <div key={String(l)}>
                  <p className="num text-2xl text-fg">{fmt.int(v as number)}</p>
                  <p className="text-xs text-muted">{l}</p>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="panel p-4">
          <p className="text-[13px] text-muted">Última coleta de dados</p>
          {dash.isLoading ? (
            <Skeleton className="mt-3 h-10" />
          ) : d?.last_data ? (
            <div className="mt-2">
              <p className="text-[15px] text-fg">
                <span className="num">{d.last_data.symbol}</span> · candles de {d.last_data.interval}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <DataBadge kind="delayed" />
                <span className="text-xs text-faint">{localDateTime(d.last_data.fetched_at)} · Yahoo Finance</span>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-sm text-faint">Nenhum download feito ainda. Os snapshots de referência do pacote não contam.</p>
          )}
        </div>
      </section>

      {/* KPIs */}
      <section aria-labelledby="kpi-h" className="mb-4">
        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <h2 id="kpi-h" className="text-base font-medium text-fg">
            Resultados do backtest
          </h2>
          {d && d.backtests.length > 0 && (
            <Select aria-label="Experimento" className="h-9 sm:w-96" value={selected ?? ''} onChange={(e) => setExpId(e.target.value)}>
              {d.backtests.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.title}
                </option>
              ))}
            </Select>
          )}
        </div>
        {d && d.backtests.length === 0 ? (
          <EmptyState
            title="Ainda não há backtests concluídos"
            action={
              <Button asChild size="sm" variant="primary">
                <Link to="/app/strategies">Escolher uma estratégia e rodar</Link>
              </Button>
            }
          >
            Taxa de acerto, resultado médio e drawdown aparecem aqui depois do primeiro backtest. Nenhum número é exibido antes disso.
          </EmptyState>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
              <KpiTile label="Estratégias cadastradas" value={d?.counts.strategies ?? null} loading={dash.isLoading} />
              <KpiTile label="Experimentos executados" value={d?.counts.experiments ?? null} loading={dash.isLoading} />
              <KpiTile
                label="Taxa de acerto histórica"
                value={s?.win_rate != null ? s.win_rate * 100 : null}
                decimals={1}
                suffix="%"
                kind="backtest"
                loading={analytics.isLoading}
                empty={s ? s.sample_note : 'Sem dados'}
                footnote={s?.win_rate_ci95 ? `IC 95 %: ${fmt.pct(s.win_rate_ci95[0])} a ${fmt.pct(s.win_rate_ci95[1])}` : undefined}
              />
              <KpiTile
                label="Resultado médio"
                value={s?.avg_r ?? null}
                decimals={3}
                suffix="R"
                kind="backtest"
                loading={analytics.isLoading}
                spark={s?.equity.slice(-40).map((p) => ({ label: p.date, value: p.cum_r }))}
                footnote={s ? `${s.trades} operações · erro padrão ${fmt.num(s.std_error_r, 3)} R` : undefined}
              />
              <KpiTile label="Drawdown máximo" value={s ? s.max_drawdown_r : null} decimals={2} suffix="R" kind="backtest" loading={analytics.isLoading} className="col-span-2 lg:col-span-1" />
            </div>
            {s && s.sample !== 'ok' && (
              <Notice tone="caution" className="mt-3">
                {s.sample_note}
              </Notice>
            )}
          </>
        )}
      </section>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.6fr_1fr]">
        {/* main chart */}
        <section className="panel p-4 sm:p-5" aria-labelledby="eq-h">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 id="eq-h" className="text-base font-medium text-fg">
                Evolução do resultado
              </h2>
              <p className="text-xs text-muted">{analytics.data?.selected?.title ?? 'Selecione um backtest'} · R acumulado por operação</p>
            </div>
            <SegmentedControl
              label="Período"
              size="sm"
              value={period}
              onChange={setPeriod}
              options={[
                { value: 'all', label: 'Tudo' },
                { value: '6m', label: '6 meses' },
                { value: '3m', label: '3 meses' },
              ]}
            />
          </div>
          {analytics.isLoading ? (
            <Skeleton className="h-[260px]" />
          ) : equity.length > 1 ? (
            <Suspense fallback={<Skeleton className="h-[260px]" />}>
              <EquityChart data={equity} height={260} />
            </Suspense>
          ) : (
            <EmptyState title="Sem curva para mostrar">Rode um backtest para ver a evolução das operações simuladas.</EmptyState>
          )}
        </section>

        {/* market watch */}
        <section className="panel p-4 sm:p-5" aria-labelledby="mw-h">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 id="mw-h" className="text-base font-medium text-fg">
              Market Watch
            </h2>
            <div className="flex items-center gap-2">
              <DataBadge kind="delayed" />
              <Link to="/app/scanner" className="text-xs text-muted hover:text-ember">
                Scanner <ArrowUpRight className="inline size-3" />
              </Link>
            </div>
          </div>
          {symbols.length === 0 ? (
            <EmptyState title="Watchlist vazia">Adicione ativos pelo Market Scanner.</EmptyState>
          ) : quotes.isLoading ? (
            <div className="space-y-2">
              {symbols.map((s2) => (
                <Skeleton key={s2} className="h-9" />
              ))}
            </div>
          ) : quotes.isError ? (
            <ErrorState error={quotes.error} retry={() => void quotes.refetch()} />
          ) : (
            <>
              <table className="w-full text-sm">
                <caption className="sr-only">Cotações com atraso dos ativos da watchlist</caption>
                <thead>
                  <tr className="text-left text-[11px] text-faint">
                    <th className="pb-2 font-normal">Ativo</th>
                    <th className="pb-2 text-right font-normal">Último</th>
                    <th className="pb-2 text-right font-normal">Var. dia</th>
                    <th className="hidden pb-2 pl-3 font-normal sm:table-cell">1 mês</th>
                  </tr>
                </thead>
                <tbody>
                  {quotes.data?.quotes.map((q) => (
                    <tr key={q.symbol} className="border-t border-line">
                      <td className="py-2">
                        <Link to={`/app/scanner?symbol=${q.symbol}`} className="num text-fg hover:text-ember">
                          {q.symbol}
                        </Link>
                      </td>
                      <td className="num py-2 text-right text-fg">{fmt.num(q.last)}</td>
                      <td className={`num py-2 text-right ${(q.change_pct ?? 0) >= 0 ? 'text-up' : 'text-down'}`}>{fmt.signedPct(q.change_pct)}</td>
                      <td className="hidden py-2 pl-3 sm:table-cell">
                        <Sparkline values={q.spark} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {quotes.data && quotes.data.errors.length > 0 && (
                <p className="mt-2 text-xs text-caution">Sem dados para: {quotes.data.errors.map((e) => e.symbol).join(', ')}.</p>
              )}
              <p className="mt-3 text-[11px] text-faint">
                Fechamento diário até {nyDateTime(quotes.data?.quotes[0]?.as_of)} · Yahoo Finance, com atraso
              </p>
            </>
          )}
        </section>
      </div>

      {/* recent experiments */}
      <section className="panel mt-4 p-4 sm:p-5" aria-labelledby="re-h">
        <div className="mb-3 flex items-center justify-between">
          <h2 id="re-h" className="text-base font-medium text-fg">
            Experimentos recentes
          </h2>
          <Link to="/app/analytics" className="text-xs text-muted hover:text-ember">
            Ver em Analytics
          </Link>
        </div>
        {d && d.recent_experiments.length === 0 ? (
          <p className="text-sm text-faint">Nada executado ainda. Comece pelo Time Machine com os dados de referência.</p>
        ) : (
          <ul className="divide-y divide-line">
            {(d?.recent_experiments ?? []).map((e) => (
              <li key={e.id} className="flex flex-col gap-1 py-2.5 sm:flex-row sm:items-center sm:gap-3">
                <div className="flex items-center gap-2">
                  <StatusBadge status={e.status} />
                  <Badge tone={e.kind === 'monte_carlo' ? 'sim' : 'neutral'}>{e.kind === 'monte_carlo' ? 'Monte Carlo' : 'Backtest'}</Badge>
                </div>
                <Link
                  to={e.kind === 'monte_carlo' ? `/app/time-machine?exp=${e.id}` : `/app/analytics?exp=${e.id}`}
                  className="min-w-0 flex-1 truncate text-sm text-fg hover:text-ember"
                >
                  {e.title}
                </Link>
                <span className="text-xs text-faint">{e.status === 'failed' && e.error ? e.error.slice(0, 80) : relative(e.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
