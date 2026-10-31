import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, NotebookPen, Pause, Play, RotateCcw, SkipBack, SkipForward, Wand2 } from 'lucide-react'
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/app/AppShell'
import { DataTable, type Column } from '@/components/app/DataTable'
import { DataQualityPanel } from '@/components/app/DataQuality'
import { JobProgress } from '@/components/app/JobProgress'
import { CandlestickChart } from '@/components/charts/CandlestickChart'
import { Badge, DataBadge, StatusBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field, Input, Select } from '@/components/ui/field'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { EmptyState, ErrorState, Notice, Skeleton, Spinner } from '@/components/ui/states'
import { api, download } from '@/lib/api'
import { intradayLabel, useIntradayProvider } from '@/lib/intraday'
import { fmt, localDateTime, relative, shortDate } from '@/lib/format'
import type { Bar, DataQuality, Experiment, Job, MonteCarlo, Snapshot, Summary, Trade } from '@/lib/types'
import { boundLabel } from '@/lib/strategy'
import { cn } from '@/lib/utils'

const FanChart = lazy(() => import('@/components/charts/charts').then((m) => ({ default: m.FanChart })))
const CloseHistogram = lazy(() => import('@/components/charts/charts').then((m) => ({ default: m.CloseHistogram })))

type Form = {
  symbol: string
  date: string
  entry_time: string
  entry: string
  stop: string
  target: string
  replays: number
  seed: number
  window: number
  until: string
  or_minutes: number
  snapshot_id: string
  history_sessions: number
}

type TMResults = {
  plan: { symbol: string; date: string; entry: number; stop: number; target: number; entry_time: string; risk_per_share: number; target_r: number; stop_rule: string }
  mc: MonteCarlo & { sample_paths?: number[][] }
  history: { sessions: number; triggered: number; target: number; stop: number; close: number; green: number; avg_R: number | null; rule?: { or_minutes: number; stop_rule: string; target_r: number } }
  verdict: string
  verdict_notes: string[]
  warnings: string[]
  note: string
  data: { last_bar: string; short_sessions_left_out: { date: string; bars: number }[] }
  history_summary: Summary
  snapshot: { id: string; sha256: string; source: string; fetched_at: string; is_fixture: boolean }
  data_quality?: DataQuality | null
  algorithm_version: string
  limitations: string[]
}

const REF = { symbol: 'TSLA', date: '2026-10-19', entry_time: '10:15', entry: '364.18', stop: '358.32', target: '370.04', replays: 10000, seed: 19, window: 2, until: '', or_minutes: 15 }

function wilson(k: number, n: number): [number, number] | null {
  if (!n) return null
  const z = 1.96
  const p = k / n
  const d = 1 + (z * z) / n
  const c = (p + (z * z) / (2 * n)) / d
  const h = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d
  return [Math.max(0, c - h), Math.min(1, c + h)]
}

// ---------------------------------------------------------------- results

function Results({ exp }: { exp: Experiment }) {
  const r = exp.results as unknown as TMResults
  const qc = useQueryClient()
  const [rerun, setRerun] = useState<{ job: string; exp: string } | null>(null)
  const again = useMutation({
    mutationFn: () => api<{ job: Job; experiment_id: string }>('/timemachine', { body: { ...exp.params, snapshot_id: r.snapshot.id } }),
    onSuccess: (x) => setRerun({ job: x.job.id, exp: x.experiment_id }),
  })
  const sizing = useQuery({
    queryKey: ['risk', 'tm', exp.id],
    queryFn: ({ signal }) =>
      api<{ sizing: { qty: number; max_loss: number; bound_by: string } | null; refusal?: string; note: string }>('/risk/check', {
        body: { symbol: r.plan.symbol, date: r.plan.date, entry: r.plan.entry, stop: r.plan.stop, target: r.plan.target, entry_time: String(exp.params.entry_time ?? '10:15') },
        signal,
      }),
  })
  const m = r.mc
  const h = r.history
  const decidedSim = m.p_target + m.p_stop
  const simShare = decidedSim ? m.p_target / decidedSim : null
  const histDecided = h.target + h.stop
  const histShare = histDecided ? h.target / histDecided : null
  const ci = wilson(h.target, histDecided)
  const breakEven = 1 / (1 + (m.r_at_target ?? 1))
  const trades = exp.trades ?? []

  const cols: Column<Trade>[] = [
    { key: 'd', header: 'Sessão', sort: (t) => t.entry_date, cell: (t) => <span className="num">{shortDate(t.entry_date)}</span>, width: 110 },
    { key: 't', header: 'Entrada', cell: (t) => <span className="num text-muted">{t.entry_time}</span>, width: 100 },
    { key: 'e', header: 'Preço', align: 'right', sort: (t) => t.entry, cell: (t) => <span className="num">{fmt.num(t.entry)}</span> },
    { key: 's', header: 'Stop', align: 'right', cell: (t) => <span className="num text-muted">{fmt.num(t.stop)}</span> },
    { key: 'g', header: 'Alvo', align: 'right', cell: (t) => <span className="num text-muted">{fmt.num(t.target)}</span> },
    {
      key: 'o',
      header: 'Resultado',
      sort: (t) => t.outcome,
      cell: (t) => <Badge tone={t.outcome === 'target' ? 'up' : t.outcome === 'stop' ? 'down' : 'neutral'}>{t.outcome === 'target' ? 'Alvo' : t.outcome === 'stop' ? 'Stop' : 'Fechamento'}</Badge>,
    },
    { key: 'r', header: 'R', align: 'right', sort: (t) => t.r_multiple, cell: (t) => <span className={cn('num', t.r_multiple > 0 ? 'text-up' : t.r_multiple < 0 ? 'text-down' : '')}>{fmt.r(t.r_multiple, 2)}</span> },
  ]

  const odds = [
    { l: 'Alvo primeiro', v: m.p_target, c: 'bg-up' },
    { l: 'Stop primeiro', v: m.p_stop, c: 'bg-down' },
    { l: `Nenhum até ${m.until}`, v: m.p_neither, c: 'bg-muted' },
    { l: 'Positivo no fim', v: m.p_green, c: 'bg-sim', hint: `alvo primeiro, ou acima da entrada às ${m.until}` },
  ]

  return (
    <div className="space-y-4">
      <section className="panel p-4 sm:p-5" aria-labelledby="res-h">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="res-h" className="text-lg font-medium text-fg">
            {r.plan.symbol} · {shortDate(r.plan.date)} · entrada {String(exp.params.entry_time)} ET
          </h2>
          <DataBadge kind="simulated" />
          {r.snapshot.is_fixture && <DataBadge kind="fixture" />}
        </div>
        <p className="num mt-1 text-xs text-muted">
          entrada {fmt.num(r.plan.entry)} · stop {fmt.num(r.plan.stop)} · alvo {fmt.num(r.plan.target)} ({r.plan.target_r}R, risco {fmt.num(r.plan.risk_per_share)} por ação) · {fmt.int(m.replays)} replays · seed {m.seed}
        </p>

        <div className="mt-5 grid grid-cols-2 gap-2 lg:grid-cols-4">
          {odds.map((o) => (
            <div key={o.l} className="rounded-[var(--radius-md)] border border-line bg-abyss/40 p-3" title={o.hint}>
              <p className="text-xs text-muted">{o.l}</p>
              <p className="num mt-1 text-2xl text-fg">{fmt.pct(o.v)}</p>
              <div className="mt-2 h-1 rounded-full bg-line">
                <div className={cn('h-1 rounded-full', o.c)} style={{ width: `${o.v * 100}%` }} />
              </div>
            </div>
          ))}
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <div>
            <p className="text-xs text-muted">Preço às {m.until}, mediana</p>
            <p className="num text-lg text-fg">{fmt.price(m.median_close)}</p>
          </div>
          <div>
            <p className="text-xs text-muted">90 % dos replays entre</p>
            <p className="num text-lg text-fg">
              {fmt.num(m.p5_close)} e {fmt.num(m.p95_close)}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted">Resultado médio simulado</p>
            <p className="num text-lg text-fg">{fmt.r(m.avg_R)}</p>
          </div>
        </div>

        <div className="mt-5 border-l-2 border-ember pl-4">
          <p className="eyebrow mb-1 text-[10px]">Veredito da ferramenta (texto original do trader-timemachine)</p>
          <p className="num text-sm text-fg">{r.verdict}</p>
          {r.verdict_notes.map((n) => (
            <p key={n} className="num mt-1 text-sm text-muted">
              {n}
            </p>
          ))}
          {r.warnings.map((w) => (
            <p key={w} className="mt-1 text-sm text-caution">
              {w}
            </p>
          ))}
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
        <section className="panel p-4 sm:p-5" aria-labelledby="fan-h">
          <h3 id="fan-h" className="text-base font-medium text-fg">
            Leque de caminhos simulados
          </h3>
          <p className="mb-3 text-xs text-muted">
            Faixas de 50 % e 90 % de {fmt.int(m.band_paths)} caminhos, mediana em branco e {Math.min(24, m.sample_paths?.length ?? 0)} caminhos de exemplo. Horário de Nova York.
          </p>
          <Suspense fallback={<Skeleton className="h-[320px]" />}>
            <FanChart bands={m.bands} times={m.band_times} entry={r.plan.entry} stop={r.plan.stop} target={r.plan.target} paths={m.sample_paths} height={320} />
          </Suspense>
        </section>
        <section className="panel p-4 sm:p-5" aria-labelledby="hist-h">
          <h3 id="hist-h" className="text-base font-medium text-fg">
            Distribuição do preço às {m.until}
          </h3>
          <p className="mb-3 text-xs text-muted">Replays por faixa de preço. Verde acima da entrada, vermelho abaixo.</p>
          <Suspense fallback={<Skeleton className="h-[220px]" />}>
            <CloseHistogram hist={m.hist} entry={r.plan.entry} height={220} />
          </Suspense>
        </section>
      </div>

      <section className="panel p-4 sm:p-5" aria-labelledby="cmp-h">
        <h3 id="cmp-h" className="text-base font-medium text-fg">
          Simulação × histórico
        </h3>
        <p className="mt-1 text-sm text-muted">
          A mesma regra (faixa de {h.rule?.or_minutes ?? String(exp.params.or_minutes)} min, stop {h.rule?.stop_rule === 'or_mid' ? 'no meio da faixa' : h.rule?.stop_rule}, alvo {h.rule?.target_r ?? r.plan.target_r}R) reexecutada em cada uma
          das {h.sessions} sessões reais do período: disparou {h.triggered} vezes, {h.target} alvo, {h.stop} stop, {h.close} nenhum. Resultado médio {fmt.r(h.avg_R)}.
        </p>
        <dl className="mt-4 grid gap-px overflow-hidden rounded-[var(--radius-md)] border border-line bg-line sm:grid-cols-3">
          <div className="bg-surface p-3">
            <dt className="text-xs text-muted">Alvo antes do stop · simulação</dt>
            <dd className="num text-lg text-fg">{fmt.pct(simShare)}</dd>
            <dd className="text-[11px] text-faint">entre os {fmt.pct(decidedSim)} dos replays que tocaram um lado</dd>
          </div>
          <div className="bg-surface p-3">
            <dt className="text-xs text-muted">Alvo antes do stop · histórico</dt>
            <dd className="num text-lg text-fg">{fmt.pct(histShare)}</dd>
            <dd className="text-[11px] text-faint">{ci ? `IC 95 %: ${fmt.pct(ci[0])} a ${fmt.pct(ci[1])} (n = ${histDecided})` : 'sem operações decididas'}</dd>
          </div>
          <div className="bg-surface p-3">
            <dt className="text-xs text-muted">Ponto de equilíbrio a {m.r_at_target}R</dt>
            <dd className="num text-lg text-fg">{fmt.pct(breakEven)}</dd>
            <dd className="text-[11px] text-faint">fração de alvos necessária para empatar</dd>
          </div>
        </dl>
        {ci && ci[0] < breakEven && ci[1] > breakEven && (
          <Notice tone="caution" className="mt-3">
            Com {histDecided} operações decididas, o intervalo de confiança do histórico inclui o ponto de equilíbrio: a amostra não distingue esta regra de um resultado neutro.
          </Notice>
        )}
        <div className="mt-4">
          <DataTable rows={trades} columns={cols} rowKey={(t) => t.id} caption="Ocorrências históricas da regra" initialSort={{ key: 'd', dir: 'desc' }} empty={<p className="text-sm text-faint">A regra não disparou no período.</p>} />
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="panel p-4 sm:p-5" aria-labelledby="rep-h">
          <h3 id="rep-h" className="mb-3 text-base font-medium text-fg">
            Reprodutibilidade
          </h3>
          <dl className="space-y-1.5 text-sm">
            {[
              ['Algoritmo', r.algorithm_version],
              ['Seed · replays · janela', `${m.seed} · ${fmt.int(m.replays)} · ±${m.window} candles`],
              ['Sessões no pool', `${m.pool_sessions} (${shortDate(m.pool_from)} a ${shortDate(m.pool_to)})`],
              ['Fonte dos dados', r.snapshot.source],
              ['Coleta', localDateTime(r.snapshot.fetched_at)],
              ['SHA-256 do snapshot', r.snapshot.sha256],
              ['Último candle no arquivo', r.data.last_bar],
              ['Executado em', localDateTime(exp.updated_at)],
            ].map(([k, v]) => (
              <div key={k} className="grid grid-cols-[140px_1fr] gap-3">
                <dt className="text-muted">{k}</dt>
                <dd className="num break-all text-fg/90">{v}</dd>
              </div>
            ))}
          </dl>
          {r.data_quality && <DataQualityPanel q={r.data_quality} />}
          {r.data.short_sessions_left_out.length > 0 && (
            <p className="mt-2 text-xs text-muted">Sessões curtas excluídas: {r.data.short_sessions_left_out.map((s) => shortDate(s.date)).join(', ')}.</p>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => again.mutate()} disabled={again.isPending || !!rerun}>
              <RotateCcw /> Repetir com os mesmos dados
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void download(`/experiments/${exp.id}/export?format=json`, `darkpool-tm-${exp.id.slice(0, 8)}.json`)}>
              <Download /> JSON
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void download(`/experiments/${exp.id}/export?format=csv`, `darkpool-tm-${exp.id.slice(0, 8)}.csv`)}>
              <Download /> CSV
            </Button>
            <Button asChild size="sm" variant="ghost">
              <Link to={`/app/journal?new=1&experiment=${exp.id}&symbol=${r.plan.symbol}`}>
                <NotebookPen /> Registrar no Journal
              </Link>
            </Button>
          </div>
          {rerun && (
            <div className="mt-3 space-y-2">
              <JobProgress jobId={rerun.job} label="Repetição" onDone={() => void qc.invalidateQueries({ queryKey: ['experiments', 'monte_carlo'] })} />
              <Link to={`/app/time-machine?exp=${rerun.exp}`} className="text-sm text-ember hover:underline">
                Abrir a repetição e comparar
              </Link>
            </div>
          )}
          {again.isError && <ErrorState error={again.error} className="mt-2" />}
        </section>
        <section className="panel p-4 sm:p-5" aria-labelledby="lim-h">
          <h3 id="lim-h" className="mb-3 text-base font-medium text-fg">
            Limitações desta simulação
          </h3>
          <ul className="list-disc space-y-1.5 pl-4 text-sm text-muted">
            {r.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
            <li>Amostra do histórico: {r.history_summary.sample_note}</li>
          </ul>
          <div className="mt-4 rounded-[var(--radius-md)] border border-line bg-abyss/40 p-3">
            <div className="mb-1 flex items-center gap-2">
              <p className="text-sm text-fg">Tamanho simulado da posição</p>
              <DataBadge kind="simulated" />
            </div>
            {sizing.isLoading ? (
              <Spinner />
            ) : sizing.data?.sizing ? (
              <p className="num text-sm text-fg/90">
                {sizing.data.sizing.qty} ações · perda no stop {fmt.price(sizing.data.sizing.max_loss)} · limitado por: {boundLabel(sizing.data.sizing.bound_by)}
              </p>
            ) : (
              <p className="text-sm text-caution">{sizing.data?.refusal ?? 'Sem dimensionamento.'}</p>
            )}
            <p className="mt-1 text-[11px] text-faint">trader-budget com regras padrão (capital US$ 10.000, perda máxima US$ 100). Nenhuma ordem é criada.</p>
          </div>
        </section>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- simulation form

function Simulation({ initialExp }: { initialExp: string | null }) {
  const [sp, setSp] = useSearchParams()
  const qc = useQueryClient()
  const [f, setF] = useState<Form>(() => ({
    symbol: (sp.get('symbol') ?? 'TSLA').toUpperCase(),
    date: '',
    entry_time: '10:15',
    entry: '',
    stop: '',
    target: '',
    replays: 10000,
    seed: 19,
    window: 2,
    until: sp.get('until') ?? '',
    or_minutes: Number(sp.get('or') ?? 15),
    snapshot_id: '',
    history_sessions: 60,
  }))
  const intraday = useIntradayProvider()
  const [stopRule, setStopRule] = useState<'or_mid' | 'or_low' | 'pct' | 'atr'>('or_mid')
  const [atrK, setAtrK] = useState(1.5)
  const [targetR, setTargetR] = useState(1)
  const [job, setJob] = useState<{ id: string; exp: string } | null>(null)
  const expId = initialExp
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }))

  const snaps = useQuery({
    queryKey: ['snapshots', f.symbol, '5m'],
    queryFn: ({ signal }) => api<Snapshot[]>(`/snapshots?symbol=${f.symbol}&interval=5m`, { signal }),
    enabled: /^[A-Z]{1,5}(\.[A-Z])?$/.test(f.symbol),
  })
  const sessions = useQuery({
    queryKey: ['sessions', f.snapshot_id],
    queryFn: ({ signal }) => api<{ sessions: { date: string; bars: number; full: boolean }[] }>(`/snapshots/${f.snapshot_id}/sessions`, { signal }),
    enabled: !!f.snapshot_id,
  })
  const exp = useQuery({
    queryKey: ['experiment', expId],
    queryFn: ({ signal }) => api<Experiment>(`/experiments/${expId}`, { signal }),
    enabled: !!expId,
  })
  const registerFixture = useMutation({
    mutationFn: () => api<Snapshot>('/snapshots/fixture', { method: 'POST' }),
    onSuccess: (s) => {
      void qc.invalidateQueries({ queryKey: ['snapshots'] })
      setF((x) => ({ ...x, ...REF, snapshot_id: s.id }))
    },
  })
  const planOrb = useMutation({
    mutationFn: () =>
      api<{
        triggered: boolean
        reason?: string
        refusal?: string
        opening_range: { high: number; low: number } | null
        plan?: { entry: number; stop: number; target: number; entry_time: string; stop_label: string; atr?: number; atr_bars?: number }
        data?: { note: string; source: string; new_snapshot: boolean }
      }>('/plan/orb', {
        // Without a snapshot the server downloads only that day's 5-minute bars and freezes them.
        body: {
          snapshot_id: f.snapshot_id || null,
          symbol: f.snapshot_id ? null : f.symbol,
          date: f.date,
          or_minutes: f.or_minutes,
          stop_rule: stopRule,
          atr_k: atrK,
          target_r: targetR,
        },
      }),
    onSuccess: (r) => {
      if (r.plan) setF((x) => ({ ...x, entry: String(r.plan!.entry), stop: String(r.plan!.stop), target: String(r.plan!.target), entry_time: r.plan!.entry_time }))
    },
  })
  const run = useMutation({
    mutationFn: () =>
      api<{ job: Job; experiment_id: string }>('/timemachine', {
        body: {
          symbol: f.symbol,
          date: f.date,
          entry: Number(f.entry),
          stop: Number(f.stop),
          target: Number(f.target),
          entry_time: f.entry_time,
          replays: f.replays,
          seed: f.seed,
          window: f.window,
          until: f.until || null,
          or_minutes: f.or_minutes,
          snapshot_id: f.snapshot_id || null,
          history_sessions: Math.min(250, Math.max(20, Math.round(f.history_sessions) || 60)),
          strategy_id: sp.get('strategy'),
        },
      }),
    onSuccess: (r) => setJob({ id: r.job.id, exp: r.experiment_id }),
  })

  function loadReference() {
    const fx = (snaps.data ?? []).find((s) => s.is_fixture) ?? null
    if (fx) setF((x) => ({ ...x, ...REF, snapshot_id: fx.id }))
    else registerFixture.mutate()
  }

  const e = Number(f.entry)
  const s = Number(f.stop)
  const t = Number(f.target)
  const planErr = f.entry && f.stop && f.target && !(s < e && e < t) ? 'Compra: o stop fica abaixo da entrada e o alvo acima.' : null
  const ready = /^[A-Z]{1,5}(\.[A-Z])?$/.test(f.symbol) && !!f.date && e > 0 && s > 0 && t > 0 && !planErr && /^\d\d:\d\d$/.test(f.entry_time)
  const shown = exp.data

  return (
    <div className="grid gap-4 xl:grid-cols-[380px_1fr]">
      <section className="panel h-fit p-4 sm:p-5" aria-labelledby="form-h">
        <div className="mb-4 flex items-center justify-between gap-2">
          <h2 id="form-h" className="text-base font-medium text-fg">
            Plano
          </h2>
          <Button size="sm" variant="ghost" onClick={loadReference} disabled={registerFixture.isPending}>
            Exemplo de referência
          </Button>
        </div>
        <form
          className="space-y-3"
          onSubmit={(ev) => {
            ev.preventDefault()
            if (ready) run.mutate()
          }}
          noValidate
        >
          <div className="grid grid-cols-2 gap-3">
            <Field label="Ativo">{(p) => <Input {...p} value={f.symbol} onChange={(ev) => set('symbol', ev.target.value.toUpperCase().trim())} className="num uppercase" />}</Field>
            <Field label="Data da sessão">
              {(p) =>
                sessions.data ? (
                  <Select {...p} value={f.date} onChange={(ev) => set('date', ev.target.value)}>
                    <option value="">Escolha</option>
                    {[...sessions.data.sessions].reverse().map((x) => (
                      <option key={x.date} value={x.date}>
                        {shortDate(x.date)} {x.full ? '' : `(${x.bars} candles)`}
                      </option>
                    ))}
                  </Select>
                ) : (
                  <Input {...p} type="date" value={f.date} onChange={(ev) => set('date', ev.target.value)} />
                )
              }
            </Field>
          </div>
          <Field label="Dados" hint="Snapshots congelados garantem que a execução possa ser repetida. Sem snapshot, os candles são baixados agora da fonte configurada no servidor.">
            {(p) => (
              <Select {...p} value={f.snapshot_id} onChange={(ev) => set('snapshot_id', ev.target.value)}>
                <option value="">{intradayLabel(intraday, f.history_sessions)}</option>
                {(snaps.data ?? []).map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.is_fixture ? 'Referência do pacote' : 'Snapshot'} · {localDateTime(x.fetched_at)} · {x.sha256.slice(0, 8)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          {!f.snapshot_id && intraday?.provider === 'alpaca' && (
            <Field label="Sessões de histórico" hint="Sessões da NYSE antes do dia do plano (20 a 250). Sessões com lacunas no IEX ficam de fora.">
              {(p) => (
                <Input
                  {...p}
                  type="number"
                  min={20}
                  max={250}
                  value={f.history_sessions}
                  onChange={(ev) => set('history_sessions', Number(ev.target.value))}
                />
              )}
            </Field>
          )}

          <fieldset className="rounded-[var(--radius-md)] border border-line p-3">
            <legend className="px-1 text-xs text-muted">Calcular pelo ORB (trader-entry + trader-exit)</legend>
            <div className="grid grid-cols-3 gap-2">
              <Field label="Faixa">
                {(p) => (
                  <Select {...p} value={f.or_minutes} onChange={(ev) => set('or_minutes', Number(ev.target.value))}>
                    {[5, 10, 15, 30, 60].map((n) => (
                      <option key={n} value={n}>
                        {n} min
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label="Stop">
                {(p) => (
                  <Select {...p} value={stopRule} onChange={(ev) => setStopRule(ev.target.value as typeof stopRule)}>
                    <option value="or_mid">Meio</option>
                    <option value="or_low">Mínima</option>
                    <option value="atr">ATR × K</option>
                  </Select>
                )}
              </Field>
              {stopRule === 'atr' && (
                <Field label="K (ATR)">
                  {(p) => (
                    <Select {...p} value={atrK} onChange={(ev) => setAtrK(Number(ev.target.value))}>
                      {[1, 1.5, 2, 3].map((n) => (
                        <option key={n} value={n}>
                          {n}×
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
              )}
              <Field label="Alvo">
                {(p) => (
                  <Select {...p} value={targetR} onChange={(ev) => setTargetR(Number(ev.target.value))}>
                    {[1, 1.5, 2, 3].map((n) => (
                      <option key={n} value={n}>
                        {n}R
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
            </div>
            <Button
              type="button"
              size="sm"
              className="mt-2 w-full"
              disabled={!f.date || (!f.snapshot_id && !f.symbol) || planOrb.isPending}
              onClick={() => planOrb.mutate()}
            >
              <Wand2 /> Preencher plano
            </Button>
            {!f.snapshot_id && (
              <p className="mt-1.5 text-[11px] text-faint">
                Sem snapshot, o servidor baixa só os candles de {f.symbol || 'ativo'} em {f.date || 'data'} e congela um snapshot desse dia. Cálculo único, sem monitoramento contínuo.
              </p>
            )}
            {stopRule === 'atr' && <p className="mt-1.5 text-[11px] text-faint">Stop do trader-exit: K × ATR de até 14 candles da sessão, até o candle de entrada.</p>}
            {planOrb.data && !planOrb.data.plan && <p className="mt-2 text-xs text-caution">{planOrb.data.refusal ?? planOrb.data.reason ?? 'A regra não disparou nesta sessão.'}</p>}
            {planOrb.data?.opening_range && planOrb.data.plan && (
              <p className="num mt-2 text-[11px] text-muted">
                faixa {planOrb.data.opening_range.low.toFixed(2)} a {planOrb.data.opening_range.high.toFixed(2)} · gatilho às {planOrb.data.plan.entry_time}
                {planOrb.data.plan.atr != null && ` · ATR(${planOrb.data.plan.atr_bars}) ${planOrb.data.plan.atr.toFixed(4)}`}
              </p>
            )}
            {planOrb.data?.data?.new_snapshot && <p className="mt-1 text-[11px] text-faint">{planOrb.data.data.note}</p>}
            {planOrb.isError && <ErrorState error={planOrb.error} className="mt-2" />}
          </fieldset>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Horário (NY)" hint="Fechamento do candle de entrada.">
              {(p) => <Input {...p} type="time" step={300} min="09:35" max="16:00" value={f.entry_time} onChange={(ev) => set('entry_time', ev.target.value)} />}
            </Field>
            <Field label="Entrada (US$)">{(p) => <Input {...p} type="number" step="0.01" inputMode="decimal" value={f.entry} onChange={(ev) => set('entry', ev.target.value)} />}</Field>
            <Field label="Stop (US$)">{(p) => <Input {...p} type="number" step="0.01" inputMode="decimal" value={f.stop} onChange={(ev) => set('stop', ev.target.value)} />}</Field>
            <Field label="Alvo (US$)">{(p) => <Input {...p} type="number" step="0.01" inputMode="decimal" value={f.target} onChange={(ev) => set('target', ev.target.value)} />}</Field>
            <Field label="Replays">{(p) => <Input {...p} type="number" min={100} max={50000} step={1000} value={f.replays} onChange={(ev) => set('replays', ev.target.valueAsNumber)} />}</Field>
            <Field label="Seed">{(p) => <Input {...p} type="number" min={0} value={f.seed} onChange={(ev) => set('seed', ev.target.valueAsNumber)} />}</Field>
          </div>
          <details className="text-sm">
            <summary className="cursor-pointer text-muted">Avançado</summary>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <Field label="Encerrar às (NY)" hint="Vazio = 16:00.">
                {(p) => <Input {...p} type="time" step={300} value={f.until} onChange={(ev) => set('until', ev.target.value)} />}
              </Field>
              <Field label="Janela (± candles)">{(p) => <Input {...p} type="number" min={0} max={10} value={f.window} onChange={(ev) => set('window', ev.target.valueAsNumber)} />}</Field>
            </div>
          </details>
          {planErr && <p role="alert" className="text-sm text-down">{planErr}</p>}
          {run.isError && <ErrorState error={run.error} />}
          <Button type="submit" variant="primary" className="w-full" disabled={!ready || run.isPending || !!job}>
            <Play /> Rodar {fmt.int(f.replays)} replays
          </Button>
          <p className="text-[11px] leading-relaxed text-faint">Simulação sobre os últimos 60 dias do próprio ativo. Não é previsão.</p>
        </form>
      </section>

      <div className="min-w-0 space-y-4">
        {job && (
          <JobProgress
            jobId={job.id}
            label={`Time Machine · ${f.symbol}`}
            onDone={(j) => {
              setJob(null)
              void qc.invalidateQueries({ queryKey: ['experiments'] })
              void qc.invalidateQueries({ queryKey: ['dashboard'] })
              if (j.status === 'succeeded') setSp({ exp: job.exp })
              else void qc.invalidateQueries({ queryKey: ['experiment', job.exp] })
            }}
          />
        )}
        {!expId ? (
          <EmptyState title="Nenhuma simulação aberta">
            Preencha o plano ou carregue o exemplo de referência (TSLA, 19/10/2026, entrada US$ 364,18 às 10:15, stop US$ 358,32, alvo US$ 370,04, seed 19).
          </EmptyState>
        ) : exp.isLoading ? (
          <Skeleton className="h-96" />
        ) : exp.isError ? (
          <ErrorState error={exp.error} />
        ) : shown && shown.kind !== 'monte_carlo' ? (
          <EmptyState title="Este experimento é um backtest">
            <Link to={`/app/analytics?exp=${shown.id}`} className="text-ember hover:underline">
              Abrir em Analytics
            </Link>
          </EmptyState>
        ) : shown?.status === 'succeeded' && shown.results ? (
          <Results key={shown.id} exp={shown} />
        ) : shown ? (
          <div className="panel p-5">
            <div className="flex items-center gap-2">
              <StatusBadge status={shown.status} />
              <p className="text-sm text-fg">{shown.title}</p>
            </div>
            {shown.error && <ErrorState error={new Error(shown.error)} className="mt-3" />}
            {shown.job_id && ['queued', 'running'].includes(shown.status) && (
              <div className="mt-3">
                <JobProgress jobId={shown.job_id} label="Simulação" onDone={() => void exp.refetch()} />
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- market replay

const SPEEDS = [1, 2, 4, 8]

function Replay() {
  const [symbol, setSymbol] = useState('TSLA')
  const [snap, setSnap] = useState('')
  const [date, setDate] = useState('')
  const [i, setI] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(2)
  const [orMin, setOrMin] = useState(15)
  const timer = useRef<number | null>(null)
  const snaps = useQuery({ queryKey: ['snapshots', symbol, '5m'], queryFn: ({ signal }) => api<Snapshot[]>(`/snapshots?symbol=${symbol}&interval=5m`, { signal }), enabled: /^[A-Z]{1,5}$/.test(symbol) })
  useEffect(() => {
    if (!snap && snaps.data?.length) setSnap(snaps.data[0].id)
  }, [snaps.data, snap])
  const sessions = useQuery({ queryKey: ['sessions', snap], queryFn: ({ signal }) => api<{ sessions: { date: string; bars: number }[] }>(`/snapshots/${snap}/sessions`, { signal }), enabled: !!snap })
  useEffect(() => {
    if (sessions.data?.sessions.length) setDate((d) => d || sessions.data!.sessions[sessions.data!.sessions.length - 1].date)
  }, [sessions.data])
  const bars = useQuery({ queryKey: ['bars', snap, date], queryFn: ({ signal }) => api<{ bars: Bar[]; snapshot: { sha256: string; source: string } }>(`/snapshots/${snap}/bars?date=${date}`, { signal }), enabled: !!snap && !!date })
  const all = bars.data?.bars ?? []
  useEffect(() => {
    setI(Math.min(3, all.length))
    setPlaying(false)
  }, [snap, date, all.length])
  useEffect(() => {
    if (!playing) return
    timer.current = window.setInterval(() => setI((x) => (x >= all.length ? x : x + 1)), 1000 / speed)
    return () => {
      if (timer.current) clearInterval(timer.current)
    }
  }, [playing, speed, all.length])
  useEffect(() => {
    if (i >= all.length) setPlaying(false)
  }, [i, all.length])

  const nOr = orMin / 5
  const revealed = all.slice(0, i)
  const orDone = revealed.length >= nOr
  const orHigh = orDone ? Math.max(...revealed.slice(0, nOr).map((b) => b.high)) : null
  const orLow = orDone ? Math.min(...revealed.slice(0, nOr).map((b) => b.low)) : null
  const trigger = orHigh != null ? revealed.slice(nOr).find((b) => b.close > orHigh) : undefined
  const priceLines = useMemo(
    () =>
      orHigh != null && orLow != null
        ? [
            { price: orHigh, color: '#ff4103', title: 'máx. faixa', dashed: true },
            { price: orLow, color: '#8799a3', title: 'mín. faixa', dashed: true },
          ]
        : [],
    [orHigh, orLow],
  )
  const cur = revealed[revealed.length - 1]

  return (
    <section className="panel p-4 sm:p-5" aria-labelledby="rp-h">
      <div className="flex flex-wrap items-end gap-3">
        <h2 id="rp-h" className="sr-only">
          Market Replay
        </h2>
        <Field label="Ativo" className="w-28">{(p) => <Input {...p} value={symbol} onChange={(e) => (setSymbol(e.target.value.toUpperCase()), setSnap(''), setDate(''))} className="num" />}</Field>
        <Field label="Snapshot" className="min-w-56 flex-1">
          {(p) => (
            <Select {...p} value={snap} onChange={(e) => (setSnap(e.target.value), setDate(''))}>
              {(snaps.data ?? []).length === 0 && <option value="">Nenhum snapshot de 5 min</option>}
              {(snaps.data ?? []).map((x) => (
                <option key={x.id} value={x.id}>
                  {x.is_fixture ? 'Referência do pacote' : 'Snapshot'} · {localDateTime(x.fetched_at)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Sessão" className="w-40">
          {(p) => (
            <Select {...p} value={date} onChange={(e) => setDate(e.target.value)}>
              {[...(sessions.data?.sessions ?? [])].reverse().map((s) => (
                <option key={s.date} value={s.date}>
                  {shortDate(s.date)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Faixa de abertura" className="w-36">
          {(p) => (
            <Select {...p} value={orMin} onChange={(e) => setOrMin(Number(e.target.value))}>
              {[5, 15, 30].map((n) => (
                <option key={n} value={n}>
                  {n} min
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      {snaps.data && snaps.data.length === 0 && (
        <Notice className="mt-4">
          O replay usa snapshots de candles de 5 minutos. Rode uma simulação para {symbol} (ela congela os dados) ou carregue o exemplo de referência na aba Simulação.
        </Notice>
      )}
      {bars.isLoading ? (
        <Skeleton className="mt-4 h-[380px]" />
      ) : bars.isError ? (
        <ErrorState error={bars.error} className="mt-4" />
      ) : all.length > 0 ? (
        <>
          <div className="mt-4">
            <CandlestickChart bars={all} intraday visibleCount={i} priceLines={priceLines} height={380} ariaLabel={`Replay de ${symbol} em ${date}: ${i} de ${all.length} candles`} />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button size="icon" variant="ghost" onClick={() => setI((x) => Math.max(1, x - 1))} aria-label="Retroceder um candle" disabled={i <= 1}>
              <SkipBack />
            </Button>
            <Button size="icon" variant="primary" onClick={() => (i >= all.length ? (setI(1), setPlaying(true)) : setPlaying((p) => !p))} aria-label={playing ? 'Pausar' : 'Reproduzir'}>
              {playing ? <Pause /> : <Play />}
            </Button>
            <Button size="icon" variant="ghost" onClick={() => setI((x) => Math.min(all.length, x + 1))} aria-label="Avançar um candle" disabled={i >= all.length}>
              <SkipForward />
            </Button>
            <SegmentedControl label="Velocidade" size="sm" value={String(speed)} onChange={(v) => setSpeed(Number(v))} options={SPEEDS.map((s) => ({ value: String(s), label: `${s}×` }))} />
            <span className="num ml-auto text-xs text-muted">
              {cur?.et ?? '—'} ET · candle {i} de {all.length}
            </span>
          </div>
          <label className="mt-3 block">
            <span className="sr-only">Linha do tempo</span>
            <input type="range" min={1} max={all.length} value={Math.max(1, i)} onChange={(e) => (setPlaying(false), setI(Number(e.target.value)))} className="w-full accent-[#ff4103]" />
          </label>
          <div className="mt-3 grid gap-2 text-sm sm:grid-cols-3">
            <p className="text-muted">
              Último candle revelado:{' '}
              <span className="num text-fg">
                {cur ? `A ${fmt.num(cur.open)} M ${fmt.num(cur.high)} m ${fmt.num(cur.low)} F ${fmt.num(cur.close)}` : '—'}
              </span>
            </p>
            <p className="text-muted">
              Faixa de abertura:{' '}
              <span className="num text-fg">{orDone ? `${fmt.num(orLow)} a ${fmt.num(orHigh)}` : `forma-se até ${nOr} candles`}</span>
            </p>
            <p className="text-muted">
              Rompimento: <span className="num text-fg">{trigger ? `fechou ${fmt.num(trigger.close)} no candle das ${trigger.et}` : orDone ? 'ainda não' : '—'}</span>
            </p>
          </div>
          <p className="mt-3 text-[11px] text-faint">
            Candles em ordem cronológica; os seguintes não são desenhados nem usados nos cálculos acima até serem revelados. Fonte: {bars.data?.snapshot.source} · {bars.data?.snapshot.sha256.slice(0, 12)}
          </p>
        </>
      ) : null}
    </section>
  )
}

// ---------------------------------------------------------------- runs list

function Runs({ onOpen }: { onOpen: () => void }) {
  const [, setSp] = useSearchParams()
  const q = useQuery({ queryKey: ['experiments', 'monte_carlo'], queryFn: ({ signal }) => api<Experiment[]>('/experiments?kind=monte_carlo&limit=100', { signal }) })
  if (q.isLoading) return <Skeleton className="h-60" />
  if (q.isError) return <ErrorState error={q.error} />
  if (!q.data?.length) return <EmptyState title="Nenhuma simulação ainda" />
  return (
    <section className="panel p-4 sm:p-5">
      <ul className="divide-y divide-line">
        {q.data.map((e) => (
          <li key={e.id} className="flex flex-wrap items-center gap-3 py-2.5">
            <StatusBadge status={e.status} />
            <button onClick={() => (setSp({ exp: e.id }), onOpen())} className="min-w-0 flex-1 truncate text-left text-sm text-fg hover:text-ember">
              {e.title}
            </button>
            <span className="num text-xs text-faint">seed {String(e.params.seed)}</span>
            <span className="text-xs text-faint">{relative(e.created_at)}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

export default function TimeMachine() {
  const [sp] = useSearchParams()
  const exp = sp.get('exp')
  const [mode, setMode] = useState<'sim' | 'replay' | 'runs'>('sim')
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader
        eyebrow="Simulação"
        title="Time Machine"
        description="10.000 replays do resto da sessão a partir dos candles de 5 minutos do próprio ativo, mais a mesma regra em cada sessão passada. Motor: trader-timemachine."
      >
        <SegmentedControl
          label="Modo"
          value={mode}
          onChange={(m) => {
            setMode(m)
          }}
          options={[
            { value: 'sim', label: 'Simulação' },
            { value: 'replay', label: 'Market Replay' },
            { value: 'runs', label: 'Execuções' },
          ]}
        />
      </PageHeader>
      {mode === 'sim' && <Simulation initialExp={exp} />}
      {mode === 'replay' && <Replay />}
      {mode === 'runs' && <Runs onOpen={() => setMode('sim')} />}
    </div>
  )
}
