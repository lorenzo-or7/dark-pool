import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import { FlaskConical, Plus, Rewind, Search, Trash2, X } from 'lucide-react'
import { lazy, Suspense, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/app/AppShell'
import { DataTable, type Column } from '@/components/app/DataTable'
import { JobProgress } from '@/components/app/JobProgress'
import { Sparkline } from '@/components/app/KpiTile'
import { CandlestickChart } from '@/components/charts/CandlestickChart'
import { Badge, DataBadge, StatusBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field, Input, Select } from '@/components/ui/field'
import { RangeSlider } from '@/components/ui/range-slider'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { EmptyState, ErrorState, Notice, Skeleton, Spinner } from '@/components/ui/states'
import { api, ApiError } from '@/lib/api'
import { fmt, localDateTime, nyDateTime, relative, shortDate } from '@/lib/format'
import type { Bar, Job, Provenance, Quote, Watchlist } from '@/lib/types'
import { useDisplayPolicy } from '@/lib/policy'
import { cn } from '@/lib/utils'

const ReturnChart = lazy(() => import('@/components/charts/charts').then((m) => ({ default: m.ReturnChart })))

const SETUP_LABEL: Record<string, string> = {
  breakout_20d: 'Rompimento 20d',
  bull_flag: 'Bandeira de alta',
  reclaim_ma20: 'Retomou MM20',
  oversold: 'Sobrevenda',
  oversold_bounce: 'Repique',
  orb: 'Rompimento da faixa de abertura',
}

type ChartRes = {
  symbol: string
  name: string | null
  range: string
  interval: string
  bars: Bar[]
  indicators: Record<'sma20' | 'sma50' | 'rsi14' | 'macd' | 'macd_signal' | 'macd_hist' | 'atr14', (number | null)[]>
  quote: { last: number | null; previous_close: number | null; change_pct: number | null; volume: number | null; '52w_high': number | null; '52w_low': number | null }
  provenance: Provenance
  warnings: string[]
}

// price and volume are null when the lab's display policy hides raw prices (public lab).
type Hit = {
  symbol: string
  setups: string[]
  price: number | null
  close_date?: string
  rsi?: number | null
  volume?: number | null
  /** orb: close time of the trigger bar, % above the range high, range high / low (null when prices are hidden) */
  at?: string
  pct_over?: number
  or_high?: number | null
  or_low?: number | null
}
type ScanRow = {
  id: string
  status: string
  params: Record<string, unknown>
  error: string | null
  job_id: string
  created_at: string
  result?: {
    mode?: 'daily' | 'orb'
    or_minutes?: number
    as_of: string
    universe: number
    scanned: number
    failed: number
    hits: Hit[]
    source: string
    note: string
    partial: boolean
    criteria: Record<string, string>
    filters: { min_price: number; min_volume: number }
    prices_hidden?: boolean
  }
}

// ---------------------------------------------------------------- asset search

function AssetSearch({ onPick }: { onPick: (s: string) => void }) {
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  const [job, setJob] = useState<string | null>(null)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 220)
    return () => clearTimeout(t)
  }, [q])
  const universe = useQuery({ queryKey: ['universe'], queryFn: ({ signal }) => api<{ loaded: boolean; symbols: number; updated_at: string | null }>('/universe', { signal }) })
  const res = useQuery({
    queryKey: ['search', debounced],
    queryFn: ({ signal }) => api<{ loaded: boolean; results: { symbol: string; name: string }[] }>(`/assets/search?q=${encodeURIComponent(debounced)}`, { signal }),
    enabled: debounced.length > 0,
  })
  const refresh = useMutation({
    mutationFn: () => api<{ job: Job }>('/universe/refresh', { method: 'POST' }),
    onSuccess: (r) => setJob(r.job.id),
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    const v = q.trim().toUpperCase()
    if (/^[A-Z]{1,5}(\.[A-Z])?$/.test(v)) onPick(v)
  }

  return (
    <div className="panel p-4">
      <form onSubmit={submit} role="search" className="relative">
        <label htmlFor="asset-q" className="sr-only">
          Pesquisar ativo por ticker ou nome
        </label>
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint" aria-hidden />
        <Input id="asset-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ticker ou nome (ex.: TSLA, Apple)" className="pl-9" autoComplete="off" />
      </form>
      <div className="mt-2 text-xs text-faint">
        {universe.data?.loaded ? (
          <>
            {fmt.int(universe.data.symbols)} ações dos EUA · lista de {localDateTime(universe.data.updated_at)} ·{' '}
            <button className="underline-offset-2 hover:text-ember hover:underline" onClick={() => refresh.mutate()} disabled={!!job}>
              atualizar
            </button>
          </>
        ) : universe.isLoading ? (
          'Verificando lista de ações…'
        ) : (
          <span>
            A busca por nome precisa da lista da Nasdaq Trader.{' '}
            <button className="text-ember hover:underline" onClick={() => refresh.mutate()} disabled={!!job}>
              Baixar lista
            </button>{' '}
            (você ainda pode digitar um ticker e apertar Enter).
          </span>
        )}
      </div>
      {job && (
        <div className="mt-3">
          <JobProgress
            jobId={job}
            label="Atualizando universo de ações"
            onDone={() => {
              setJob(null)
              void qc.invalidateQueries({ queryKey: ['universe'] })
              void qc.invalidateQueries({ queryKey: ['search'] })
            }}
          />
        </div>
      )}
      {refresh.isError && <ErrorState error={refresh.error} className="mt-3" />}
      {debounced && (
        <ul className="mt-3 max-h-64 overflow-y-auto" aria-label="Resultados da busca">
          {res.isLoading && <Spinner />}
          {res.data && res.data.results.length === 0 && <li className="py-2 text-sm text-faint">{res.data.loaded ? 'Nenhum ativo encontrado.' : 'Lista de ações não baixada.'}</li>}
          {res.data?.results.map((r) => (
            <li key={r.symbol}>
              <button onClick={() => onPick(r.symbol)} className="flex w-full items-baseline gap-3 rounded-[8px] px-2 py-2 text-left hover:bg-raised">
                <span className="num w-16 shrink-0 text-sm text-fg">{r.symbol}</span>
                <span className="truncate text-xs text-muted">{r.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- asset detail

const RANGES = [
  { value: '5d', label: '5D' },
  { value: '1mo', label: '1M' },
  { value: '3mo', label: '3M' },
  { value: '6mo', label: '6M' },
  { value: '1y', label: '1A' },
  { value: '2y', label: '2A' },
] as const

type RelativeRes = {
  symbol: string
  name: string | null
  range: string
  interval: string
  time: number[]
  series: Record<'return_pct' | 'rsi14' | 'dist_sma20_pct' | 'atr14_pct' | 'macd_hist_pct', (number | null)[]>
  quote: { change_pct: number | null }
  provenance: Provenance
  warnings: string[]
}

/** Public lab (prices hidden): return in % since the start of the period and relative indicators. */
function RelativeDetail({ q }: { q: UseQueryResult<RelativeRes> }) {
  const d = q.data
  const last = (xs: (number | null)[] | undefined) => (xs ? ([...xs].reverse().find((x) => x != null) ?? null) : null)
  return (
    <div className="mt-3">
      {q.isLoading ? (
        <Skeleton className="h-[300px]" />
      ) : q.isError ? (
        <ErrorState error={q.error} retry={() => void q.refetch()} />
      ) : d && d.time.length ? (
        <Suspense fallback={<Skeleton className="h-[300px]" />}>
          <ReturnChart time={d.time} values={d.series.return_pct} intraday={d.interval === '5m'} height={300} />
        </Suspense>
      ) : (
        <EmptyState title="Sem dados para este período" />
      )}
      {d && (
        <>
          <p className="mt-2 text-[11px] leading-relaxed text-faint">
            Retorno acumulado desde o início do período. Preços e candles não são exibidos neste laboratório público. {d.provenance.source_label} · coletado {localDateTime(d.provenance.fetched_at)}.
          </p>
          <dl className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius-md)] border border-line bg-line sm:grid-cols-4">
            {[
              ['Retorno no período', fmt.signedPct(last(d.series.return_pct))],
              ['RSI 14', fmt.num(last(d.series.rsi14), 1)],
              ['Distância da MM20', fmt.signedPct(last(d.series.dist_sma20_pct))],
              ['ATR 14 (% do preço)', `${fmt.num(last(d.series.atr14_pct), 2)} %`],
            ].map(([l, v]) => (
              <div key={l} className="bg-surface p-3">
                <dt className="text-[11px] text-muted">{l}</dt>
                <dd className="num mt-0.5 text-[15px] text-fg">{v}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </div>
  )
}

function AssetDetail({ symbol, watchlists, onClose }: { symbol: string; watchlists: Watchlist[]; onClose: () => void }) {
  const qc = useQueryClient()
  const [range, setRange] = useState<(typeof RANGES)[number]['value']>('6mo')
  const [ma, setMa] = useState(true)
  const [tab, setTab] = useState<'indicators' | 'news' | 'fundamentals'>('indicators')
  const policy = useDisplayPolicy()
  // Public lab: no price level on screen, only return in % and relative indicators (display policy).
  const hidden = policy != null && !policy.show_raw_prices
  const chart = useQuery({
    queryKey: ['chart', symbol, range],
    queryFn: ({ signal }) => api<ChartRes>(`/assets/${symbol}/chart?range=${range}`, { signal }),
    enabled: policy != null && !hidden,
  })
  const rel = useQuery({
    queryKey: ['relative', symbol, range],
    queryFn: ({ signal }) => api<RelativeRes>(`/assets/${symbol}/relative?range=${range}`, { signal }),
    enabled: hidden,
  })
  const news = useQuery({
    queryKey: ['news', symbol],
    queryFn: ({ signal }) => api<{ items?: { title: string; link: string; published?: string; time?: string; source?: string; tags?: string[] }[]; note: string | null }>(`/assets/${symbol}/news`, { signal }),
    enabled: tab === 'news',
    staleTime: 300_000,
  })
  const funda = useQuery({
    queryKey: ['fundamentals', symbol],
    queryFn: ({ signal }) => api<Record<string, unknown>>(`/assets/${symbol}/fundamentals`, { signal }),
    enabled: tab === 'fundamentals',
    retry: false,
  })
  const add = useMutation({
    mutationFn: (wid: string) => api(`/watchlists/${wid}/assets`, { body: { symbol } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlists'] }),
  })
  const [wid, setWid] = useState('')
  useEffect(() => setWid(watchlists[0]?.id ?? ''), [watchlists])

  const c = chart.data
  const overlays = useMemo(
    () =>
      c && ma
        ? [
            { id: 'sma20', color: '#ff6a36', values: c.indicators.sma20 },
            { id: 'sma50', color: '#7fb6d1', values: c.indicators.sma50 },
          ]
        : [],
    [c, ma],
  )
  const hi = c ? Math.max(...c.bars.map((b) => b.high)) : null
  const lo = c ? Math.min(...c.bars.map((b) => b.low)) : null
  const last = <T,>(xs: (T | null)[] | undefined) => (xs ? ([...xs].reverse().find((x) => x != null) ?? null) : null)
  const inList = watchlists.find((w) => w.id === wid)?.assets.some((a) => a.symbol === symbol)

  return (
    <section className="panel p-4 sm:p-5" aria-label={`Detalhes de ${symbol}`}>
      {/* Stock card header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="num text-2xl text-fg">{symbol}</h2>
            <DataBadge kind="delayed" />
          </div>
          <p className="truncate text-sm text-muted">{(hidden ? rel.data?.name : c?.name) ?? (chart.isLoading || rel.isLoading ? 'Carregando…' : '')}</p>
        </div>
        <div className="text-right">
          {!hidden && <p className="num text-2xl text-fg">{fmt.num(c?.quote.last)}</p>}
          {(() => {
            const chg = hidden ? rel.data?.quote.change_pct : c?.quote.change_pct
            return <p className={cn('num text-sm', (chg ?? 0) >= 0 ? 'text-up' : 'text-down')}>{fmt.signedPct(chg)} vs. fechamento anterior</p>
          })()}
        </div>
        <button onClick={onClose} className="rounded-[8px] p-1.5 text-muted hover:bg-raised hover:text-fg sm:hidden" aria-label="Fechar detalhes">
          <X className="size-4" />
        </button>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <SegmentedControl label="Período do gráfico" size="sm" value={range} onChange={setRange} options={RANGES.map((r) => ({ value: r.value, label: r.label }))} />
        {!hidden && (
          <label className="inline-flex items-center gap-2 text-xs text-muted">
            <input type="checkbox" checked={ma} onChange={(e) => setMa(e.target.checked)} className="accent-[#ff4103]" />
            Médias móveis 20 e 50
          </label>
        )}
      </div>

      {hidden && <RelativeDetail q={rel} />}
      {!hidden && <div className="mt-3">
        {chart.isLoading ? (
          <Skeleton className="h-[360px]" />
        ) : chart.isError ? (
          <ErrorState error={chart.error} retry={() => void chart.refetch()} />
        ) : c && c.bars.length ? (
          <CandlestickChart bars={c.bars} intraday={c.interval === '5m'} overlays={overlays} height={360} ariaLabel={`Gráfico de candles de ${symbol}, ${c.bars.length} períodos`} />
        ) : (
          <EmptyState title="Sem candles para este período" />
        )}
      </div>}
      {c && (
        <p className="mt-2 text-[11px] leading-relaxed text-faint">
          {c.provenance.source_label} · {c.provenance.exchange} · último candle {c.interval === '5m' ? nyDateTime(c.provenance.last_bar_time) : shortDate(c.provenance.last_bar_time)} · coletado {localDateTime(c.provenance.fetched_at)}
          {c.provenance.from_cache ? ' (cache)' : ''}. {c.provenance.note}
          {ma && <span className="ml-1">MM20 laranja, MM50 azul.</span>}
        </p>
      )}
      {c?.warnings.map((w) => (
        <Notice key={w} tone="caution" className="mt-2">
          {w}
        </Notice>
      ))}

      {c && (
        <dl className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius-md)] border border-line bg-line sm:grid-cols-4">
          {[
            ['Máxima do período', fmt.num(hi)],
            ['Mínima do período', fmt.num(lo)],
            ['Volume (última sessão)', fmt.compact(c.quote.volume)],
            ['ATR 14', fmt.num(last(c.indicators.atr14))],
          ].map(([l, v]) => (
            <div key={l} className="bg-surface p-3">
              <dt className="text-[11px] text-muted">{l}</dt>
              <dd className="num mt-0.5 text-[15px] text-fg">{v}</dd>
            </div>
          ))}
        </dl>
      )}

      <div className="mt-5 flex flex-wrap gap-2">
        <Button asChild variant="primary" size="sm">
          <Link to={`/app/strategies/new?symbol=${symbol}`}>
            <FlaskConical /> Enviar ao Strategy Lab
          </Link>
        </Button>
        <Button asChild size="sm">
          <Link to={`/app/time-machine?symbol=${symbol}`}>
            <Rewind /> Abrir no Time Machine
          </Link>
        </Button>
        {watchlists.length > 0 && (
          <div className="flex items-center gap-1.5">
            <Select aria-label="Watchlist" value={wid} onChange={(e) => setWid(e.target.value)} className="h-8 w-40 text-xs">
              {watchlists.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </Select>
            <Button size="sm" variant="ghost" disabled={inList || add.isPending || !wid} onClick={() => add.mutate(wid)}>
              <Plus /> {inList ? 'Na watchlist' : 'Adicionar'}
            </Button>
          </div>
        )}
      </div>
      {add.isError && <ErrorState error={add.error} className="mt-2" />}

      <div className="mt-6 border-t border-line pt-4">
        <SegmentedControl
          label="Detalhes do ativo"
          size="sm"
          value={tab}
          onChange={setTab}
          options={[
            { value: 'indicators', label: 'Indicadores' },
            { value: 'news', label: 'Notícias' },
            { value: 'fundamentals', label: 'Resultados (SEC)' },
          ]}
        />
        <div className="mt-4">
          {tab === 'indicators' && c && (
            <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              {[
                ['RSI 14 (Wilder)', fmt.num(last(c.indicators.rsi14), 1)],
                ['MACD (12, 26)', fmt.num(last(c.indicators.macd), 3)],
                ['Sinal MACD (9)', fmt.num(last(c.indicators.macd_signal), 3)],
                ['MM20 / MM50', `${fmt.num(last(c.indicators.sma20))} / ${fmt.num(last(c.indicators.sma50))}`],
              ].map(([l, v]) => (
                <div key={l}>
                  <dt className="text-[11px] text-muted">{l}</dt>
                  <dd className="num text-fg">{v}</dd>
                </div>
              ))}
              <p className="col-span-full text-[11px] text-faint">Calculados no backend sobre os candles exibidos ({c.interval}), sem informação futura.</p>
            </dl>
          )}
          {tab === 'news' &&
            (news.isLoading ? (
              <Spinner />
            ) : news.isError ? (
              <ErrorState error={news.error} retry={() => void news.refetch()} />
            ) : (
              <>
                {news.data?.note && <Notice className="mb-3">{news.data.note}</Notice>}
                {(news.data?.items ?? []).length === 0 ? (
                  <p className="text-sm text-faint">Nenhuma manchete nos últimos 7 dias pelas fontes configuradas.</p>
                ) : (
                  <ul className="divide-y divide-line">
                    {news.data!.items!.slice(0, 12).map((n) => (
                      <li key={n.link} className="py-2.5">
                        <a href={n.link} target="_blank" rel="noopener noreferrer" className="text-sm text-fg hover:text-ember">
                          {n.title}
                        </a>
                        <p className="mt-0.5 text-[11px] text-faint">
                          {n.source ?? ''} {n.time ?? n.published ?? ''} {n.tags?.length ? `· ${n.tags.join(', ')}` : ''}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="mt-2 text-[11px] text-faint">trader-news · Yahoo Finance RSS{news.data?.note ? '' : ' e SEC EDGAR 8-K'}</p>
              </>
            ))}
          {tab === 'fundamentals' &&
            (funda.isLoading ? (
              <Spinner />
            ) : funda.error instanceof ApiError && funda.error.code === 'sec_user_agent_missing' ? (
              <Notice tone="caution">{funda.error.message} Os dados do trader-analyst vêm da SEC EDGAR e exigem essa identificação.</Notice>
            ) : funda.isError ? (
              <ErrorState error={funda.error} />
            ) : (
              <pre className="num max-h-80 overflow-auto rounded-[var(--radius-md)] bg-abyss p-3 text-[11px] text-muted">{JSON.stringify(funda.data, null, 1).slice(0, 6000)}</pre>
            ))}
        </div>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------- scans

function ScanPanel({ watchlists, onPick, picked }: { watchlists: Watchlist[]; onPick: (s: string) => void; picked: string | null }) {
  const qc = useQueryClient()
  const [mode, setMode] = useState<'daily' | 'orb'>('daily')
  const [orMinutes, setOrMinutes] = useState(15)
  const [orbDay, setOrbDay] = useState('')
  const [orbAt, setOrbAt] = useState('')
  const [source, setSource] = useState<'watchlist' | 'symbols' | 'universe'>('watchlist')
  const [symbols, setSymbols] = useState('AAPL, MSFT, NVDA, TSLA, AMD, KO, JPM, XOM, BAC, F, HD, GE, CCL, RIVN, PLUG')
  const [wid, setWid] = useState('')
  const [limit, setLimit] = useState(200)
  const [minVol, setMinVol] = useState(1_000_000)
  const [price, setPrice] = useState<[number, number]>([5, 1000])
  const [rsi, setRsi] = useState<[number, number]>([0, 100])
  const [setup, setSetup] = useState('all')
  const [filter, setFilter] = useState('')
  const [scanId, setScanId] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  useEffect(() => setWid((w) => w || watchlists[0]?.id || ''), [watchlists])

  const history = useQuery({ queryKey: ['scans'], queryFn: ({ signal }) => api<ScanRow[]>('/scans?limit=10', { signal }) })
  useEffect(() => {
    if (!scanId && history.data?.length) {
      const done = history.data.find((s) => s.status === 'succeeded')
      if (done) setScanId(done.id)
    }
  }, [history.data, scanId])
  const scan = useQuery({ queryKey: ['scan', scanId], queryFn: ({ signal }) => api<ScanRow>(`/scans/${scanId}`, { signal }), enabled: !!scanId })

  const run = useMutation({
    mutationFn: () =>
      api<{ job: Job; scan_id: string }>('/scans', {
        body: {
          mode,
          ...(mode === 'orb' ? { or_minutes: orMinutes, day: orbDay || null, at: orbAt || null } : {}),
          source,
          symbols: source === 'symbols' ? symbols.split(/[\s,;]+/).filter(Boolean) : [],
          watchlist_id: source === 'watchlist' ? wid : null,
          limit,
          min_price: price[0],
          min_volume: minVol,
        },
      }),
    onSuccess: (r) => {
      setJobId(r.job.id)
      setScanId(r.scan_id)
    },
  })

  const res = scan.data?.result
  const hits = useMemo(() => {
    const q = filter.trim().toUpperCase()
    return (res?.hits ?? []).filter(
      (h) =>
        (h.price == null || (h.price >= price[0] && h.price <= price[1])) &&
        (h.rsi == null || h.rsi === undefined || (h.rsi >= rsi[0] && h.rsi <= rsi[1])) &&
        (setup === 'all' || h.setups.includes(setup)) &&
        (!q || h.symbol.includes(q)),
    )
  }, [res, price, rsi, setup, filter])

  const hitSymbols = hits.slice(0, 30).map((h) => h.symbol)
  const vols = useQuery({
    queryKey: ['quotes', hitSymbols.join(',')],
    queryFn: ({ signal }) => api<{ quotes: Quote[] }>(`/quotes?symbols=${hitSymbols.join(',')}`, { signal }),
    enabled: hitSymbols.length > 0,
    staleTime: 300_000,
  })
  const volBy = Object.fromEntries((vols.data?.quotes ?? []).map((q) => [q.symbol, q]))

  const orbRes = res?.mode === 'orb'
  const orbCols: Column<Hit>[] = [
    {
      key: 'symbol',
      header: 'Ativo',
      width: 96,
      sort: (h) => h.symbol,
      cell: (h) => (
        <button onClick={() => onPick(h.symbol)} className="num text-fg hover:text-ember focus-visible:text-ember">
          {h.symbol}
        </button>
      ),
    },
    { key: 'at', header: 'Gatilho (NY)', sort: (h) => h.at ?? '', cell: (h) => <span className="num">{h.at}</span> },
    { key: 'pct', header: 'Acima da faixa', align: 'right', sort: (h) => h.pct_over ?? 0, cell: (h) => <span className="num text-up">{fmt.signedPct(h.pct_over)}</span> },
    { key: 'price', header: 'Fechamento do gatilho', align: 'right', sort: (h) => h.price ?? -1, cell: (h) => <span className="num">{fmt.num(h.price)}</span> },
    {
      key: 'range',
      header: 'Faixa',
      align: 'right',
      cell: (h) => <span className="num text-muted">{h.or_low != null && h.or_high != null ? `${fmt.num(h.or_low)} a ${fmt.num(h.or_high)}` : '—'}</span>,
    },
  ]
  const cols: Column<Hit>[] = [
    {
      key: 'symbol',
      header: 'Ativo',
      width: 96,
      sort: (h) => h.symbol,
      cell: (h) => (
        <button onClick={() => onPick(h.symbol)} className="num text-fg hover:text-ember focus-visible:text-ember">
          {h.symbol}
        </button>
      ),
    },
    {
      key: 'setups',
      header: 'Padrões',
      width: 220,
      cell: (h) => (
        <span className="flex flex-wrap gap-1">
          {h.setups.map((s) => (
            <Badge key={s} tone={s.startsWith('oversold') ? 'caution' : 'ember'} title={res?.criteria[s]}>
              {SETUP_LABEL[s] ?? s}
            </Badge>
          ))}
        </span>
      ),
    },
    { key: 'price', header: 'Preço', align: 'right', sort: (h) => h.price ?? -1, cell: (h) => <span className="num">{fmt.num(h.price)}</span> },
    { key: 'rsi', header: 'RSI 14', align: 'right', sort: (h) => h.rsi ?? null, cell: (h) => <span className="num">{fmt.num(h.rsi, 1)}</span> },
    { key: 'volume', header: 'Volume', align: 'right', sort: (h) => h.volume ?? -1, cell: (h) => <span className="num">{fmt.compact(h.volume)}</span> },
    {
      key: 'vol',
      header: 'Volatil. diária',
      align: 'right',
      sort: (h) => volBy[h.symbol]?.volatility_pct ?? null,
      cell: (h) => <span className="num text-muted">{volBy[h.symbol]?.volatility_pct != null ? `${fmt.num(volBy[h.symbol].volatility_pct, 2)} %` : '—'}</span>,
    },
    { key: 'spark', header: '1 mês', cell: (h) => <Sparkline values={volBy[h.symbol]?.spark ?? []} /> },
    { key: 'date', header: 'Fechamento', sort: (h) => h.close_date ?? '', cell: (h) => <span className="num text-muted">{h.close_date ? shortDate(h.close_date) : '—'}</span> },
  ]

  return (
    <section className="panel p-4 sm:p-5" aria-labelledby="scan-h">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="scan-h" className="text-base font-medium text-fg">
            Varredura de padrões
          </h2>
          <p className="text-xs text-muted">trader-scanner · fechamentos diários ou candles de 5 min da fonte configurada no servidor · encontrar um padrão não é recomendação de compra</p>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_1fr]">
        <div className="space-y-3">
          <SegmentedControl
            label="Tipo de varredura"
            size="sm"
            value={mode}
            onChange={setMode}
            options={[
              { value: 'daily', label: 'Diária (pré-abertura)' },
              { value: 'orb', label: 'ORB (5 min)' },
            ]}
          />
          {mode === 'orb' && (
            <div className="grid grid-cols-3 gap-2">
              <Field label="Faixa">
                {(p) => (
                  <Select {...p} value={orMinutes} onChange={(e) => setOrMinutes(Number(e.target.value))}>
                    {[5, 10, 15, 30, 60].map((n) => (
                      <option key={n} value={n}>
                        {n} min
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label="Pregão" hint="Vazio = hoje.">
                {(p) => <Input {...p} type="date" value={orbDay} onChange={(e) => setOrbDay(e.target.value)} />}
              </Field>
              <Field label="Corte (NY)" hint="Vazio = agora.">
                {(p) => <Input {...p} type="time" step={300} min="09:35" max="15:30" value={orbAt} onChange={(e) => setOrbAt(e.target.value)} />}
              </Field>
            </div>
          )}
          <SegmentedControl
            label="Origem dos ativos"
            size="sm"
            value={source}
            onChange={setSource}
            options={[
              { value: 'watchlist', label: 'Watchlist' },
              { value: 'symbols', label: 'Lista manual' },
              { value: 'universe', label: 'Universo EUA' },
            ]}
          />
          {source === 'watchlist' && (
            <Field label="Watchlist">
              {(p) => (
                <Select {...p} value={wid} onChange={(e) => setWid(e.target.value)}>
                  {watchlists.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name} ({w.assets.length})
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          )}
          {source === 'symbols' && (
            <Field label="Tickers" hint="Separados por vírgula ou espaço, até 300.">
              {(p) => <Input {...p} value={symbols} onChange={(e) => setSymbols(e.target.value)} />}
            </Field>
          )}
          {source === 'universe' && (
            <Field label="Quantidade de ações" hint="As primeiras N do universo. Alpaca: 200 ações por lote; Yahoo: 20 por requisição (5.942 levam 2 a 3 minutos).">
              {(p) => <Input {...p} type="number" min={1} max={6000} value={limit} onChange={(e) => setLimit(Number(e.target.value))} />}
            </Field>
          )}
          <Field label={mode === 'orb' ? 'Volume mínimo no dia até o corte' : 'Volume mínimo na última sessão'}>
            {(p) => (
              <Select {...p} value={minVol} onChange={(e) => setMinVol(Number(e.target.value))}>
                <option value={0}>Sem mínimo</option>
                <option value={250000}>250 mil</option>
                <option value={1000000}>1 milhão (padrão do scanner)</option>
                <option value={5000000}>5 milhões</option>
              </Select>
            )}
          </Field>
          <Button variant="primary" onClick={() => run.mutate()} disabled={run.isPending || !!jobId}>
            {jobId ? 'Varredura em andamento…' : 'Executar varredura'}
          </Button>
          {run.isError && <ErrorState error={run.error} />}
          {jobId && (
            <JobProgress
              jobId={jobId}
              label={mode === 'orb' ? 'Varredura ORB' : 'Varredura diária'}
              onDone={() => {
                setJobId(null)
                void qc.invalidateQueries({ queryKey: ['scan', scanId] })
                void qc.invalidateQueries({ queryKey: ['scans'] })
                void qc.invalidateQueries({ queryKey: ['dashboard'] })
              }}
            />
          )}
        </div>
        <div className="space-y-4 rounded-[var(--radius-md)] border border-line bg-abyss/30 p-4">
          <p className="eyebrow text-[10px]">Filtros do resultado</p>
          <RangeSlider label="Preço (US$)" min={0} max={1000} step={5} value={price} onChange={setPrice} format={(v) => (v >= 1000 ? '1.000+' : String(v))} />
          <RangeSlider label="RSI 14" min={0} max={100} value={rsi} onChange={setRsi} />
          <div className="grid grid-cols-2 gap-3">
            <Field label="Padrão">
              {(p) => (
                <Select {...p} value={setup} onChange={(e) => setSetup(e.target.value)}>
                  <option value="all">Todos</option>
                  {Object.entries(SETUP_LABEL).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Buscar no resultado">{(p) => <Input {...p} value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Ticker" />}</Field>
          </div>
          <p className="text-[11px] text-faint">O preço mínimo também é enviado ao scanner. Os demais filtros atuam sobre o resultado já obtido.</p>
        </div>
      </div>

      <div className="mt-6">
        {scan.isLoading ? (
          <Skeleton className="h-40" />
        ) : !scan.data ? (
          <EmptyState title="Nenhuma varredura ainda">Escolha a origem dos ativos e execute. O resultado fica salvo no workspace.</EmptyState>
        ) : scan.data.status === 'failed' || scan.data.status === 'cancelled' ? (
          <ErrorState error={new Error(scan.data.error ?? 'A varredura não terminou.')} />
        ) : !res ? (
          <Spinner label="Aguardando resultado" />
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
              <span>
                Dados até <span className="text-fg">{res.as_of}</span>
              </span>
              <span>
                {fmt.int(res.scanned)} de {fmt.int(res.universe)} ativos analisados{res.failed ? `, ${res.failed} sem dados` : ''}
              </span>
              <span>
                {hits.length} de {res.hits.length} com padrão
              </span>
              <span>{relative(scan.data.created_at)}</span>
              {res.partial && <Badge tone="caution">Resultado parcial</Badge>}
              {res.prices_hidden && <Badge tone="caution">Preço e volume ocultos pela política de exibição</Badge>}
            </div>
            <DataTable
              rows={hits}
              columns={orbRes ? orbCols : cols}
              rowKey={(h) => h.symbol}
              caption="Ativos que se encaixaram em uma regra do scanner"
              selectedKey={picked}
              initialSort={orbRes ? { key: 'at', dir: 'asc' } : { key: 'volume', dir: 'desc' }}
              minWidth={860}
              empty={<EmptyState title="Nenhum ativo com padrão nesses filtros">Amplie as faixas de preço e RSI ou escolha outro padrão.</EmptyState>}
            />
            <details className="mt-4 text-xs text-muted">
              <summary className="cursor-pointer text-fg/80">Critérios usados</summary>
              <ul className="mt-2 space-y-1">
                {Object.entries(res.criteria).map(([k, v]) => (
                  <li key={k}>
                    <span className="text-fg">{SETUP_LABEL[k]}</span>: {v}
                  </li>
                ))}
              </ul>
              <p className="mt-2">{res.source}. Filtros enviados: preço ≥ US$ {res.filters.min_price}, volume ≥ {fmt.int(res.filters.min_volume)}.</p>
            </details>
          </>
        )}
      </div>

      {history.data && history.data.length > 1 && (
        <div className="mt-6 border-t border-line pt-4">
          <p className="eyebrow mb-2 text-[10px]">Varreduras anteriores</p>
          <ul className="flex flex-wrap gap-2">
            {history.data.map((h) => (
              <li key={h.id}>
                <button
                  onClick={() => setScanId(h.id)}
                  className={cn('flex items-center gap-2 rounded-full border px-3 py-1 text-xs', h.id === scanId ? 'border-ember/50 text-fg' : 'border-line-strong text-muted hover:text-fg')}
                >
                  <StatusBadge status={h.status} /> {relative(h.created_at)}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------------- watchlists

function Watchlists({ data, onPick }: { data: Watchlist[]; onPick: (s: string) => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const inv = () => qc.invalidateQueries({ queryKey: ['watchlists'] })
  const create = useMutation({ mutationFn: () => api('/watchlists', { body: { name } }), onSuccess: () => (setName(''), inv()) })
  const remove = useMutation({ mutationFn: ({ w, s }: { w: string; s: string }) => api(`/watchlists/${w}/assets/${s}`, { method: 'DELETE' }), onSuccess: inv })
  const drop = useMutation({ mutationFn: (w: string) => api(`/watchlists/${w}`, { method: 'DELETE' }), onSuccess: inv })
  return (
    <section className="panel p-4" aria-labelledby="wl-h">
      <h2 id="wl-h" className="text-base font-medium text-fg">
        Watchlists compartilhadas
      </h2>
      <div className="mt-3 space-y-4">
        {data.map((w) => (
          <div key={w.id}>
            <div className="flex items-center justify-between">
              <p className="text-sm text-fg">{w.name}</p>
              <button onClick={() => drop.mutate(w.id)} className="rounded p-1 text-faint hover:text-down" aria-label={`Excluir watchlist ${w.name}`}>
                <Trash2 className="size-3.5" />
              </button>
            </div>
            {w.assets.length === 0 ? (
              <p className="mt-1 text-xs text-faint">Vazia. Abra um ativo e adicione.</p>
            ) : (
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {w.assets.map((a) => (
                  <li key={a.id} className="flex items-center rounded-full border border-line-strong">
                    <button onClick={() => onPick(a.symbol)} className="num py-1 pr-1 pl-3 text-xs text-fg hover:text-ember">
                      {a.symbol}
                    </button>
                    <button onClick={() => remove.mutate({ w: w.id, s: a.symbol })} className="rounded-full p-1.5 text-faint hover:text-down" aria-label={`Remover ${a.symbol}`}>
                      <X className="size-3" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (name.trim()) create.mutate()
          }}
          className="flex gap-2"
        >
          <label htmlFor="wl-new" className="sr-only">
            Nome da nova watchlist
          </label>
          <Input id="wl-new" value={name} onChange={(e) => setName(e.target.value)} placeholder="Nova watchlist" className="h-9" />
          <Button size="sm" type="submit" disabled={!name.trim() || create.isPending}>
            Criar
          </Button>
        </form>
        {(create.isError || remove.isError || drop.isError) && <ErrorState error={create.error ?? remove.error ?? drop.error} />}
      </div>
    </section>
  )
}

export default function Scanner() {
  const [params, setParams] = useSearchParams()
  const picked = params.get('symbol')
  const wl = useQuery({ queryKey: ['watchlists'], queryFn: ({ signal }) => api<Watchlist[]>('/watchlists', { signal }) })
  const pick = (s: string) => {
    setParams({ symbol: s })
    requestAnimationFrame(() => document.getElementById('asset-detail')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader
        eyebrow="Pesquisa"
        title="Market Scanner"
        description="Pesquise ações dos EUA, veja candles e indicadores e procure padrões técnicos. Cotações gratuitas, com atraso."
      />
      <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
        <div className="space-y-4">
          <AssetSearch onPick={pick} />
          {wl.isLoading ? <Skeleton className="h-40" /> : wl.isError ? <ErrorState error={wl.error} /> : <Watchlists data={wl.data ?? []} onPick={pick} />}
        </div>
        <div id="asset-detail" className="min-w-0 scroll-mt-20 space-y-4">
          {picked ? (
            <AssetDetail key={picked} symbol={picked} watchlists={wl.data ?? []} onClose={() => setParams({})} />
          ) : (
            <EmptyState title="Selecione um ativo">Pesquise pelo ticker ou clique em um resultado da varredura para ver o gráfico, os indicadores e as notícias.</EmptyState>
          )}
          <ScanPanel watchlists={wl.data ?? []} onPick={pick} picked={picked} />
        </div>
      </div>
    </div>
  )
}
