/**
 * Recharts-based views. Area with glowing dots (after sean0205 c-chart-16),
 * radar score (after c-chart-24), Monte Carlo fan and histograms. The 21st.dev
 * sources need a login; these are in-house builds with real axes, units and
 * tooltips.
 */
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fmt, shortDate } from '@/lib/format'

const AXIS = { stroke: '#12394a', tick: { fill: '#8799a3', fontSize: 11, fontFamily: 'IBM Plex Mono' }, tickLine: false }
const GRID = <CartesianGrid stroke="#12394a" strokeOpacity={0.6} vertical={false} />

type TipProps = { active?: boolean; payload?: readonly { payload?: unknown }[]; label?: unknown }

function Tip({ active, payload, label, render }: TipProps & { render: (p: Record<string, unknown>, label: unknown) => React.ReactNode }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-[var(--radius-md)] border border-line-strong bg-ink/95 px-3 py-2 text-xs shadow-xl shadow-black/40">
      {render(payload[0].payload as Record<string, unknown>, label)}
    </div>
  )
}

/** Cumulative R curve with soft glowing markers on each trade. */
export function EquityChart({ data, height = 240 }: { data: { date: string; cum_r: number }[]; height?: number }) {
  const showDots = data.length <= 60
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data.map((d, i) => ({ ...d, i: i + 1 }))} margin={{ top: 12, right: 12, bottom: 4, left: -8 }}>
        <defs>
          <linearGradient id="eq-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#ff4103" stopOpacity={0.28} />
            <stop offset="1" stopColor="#ff4103" stopOpacity={0} />
          </linearGradient>
          <filter id="eq-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2.2" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        {GRID}
        <XAxis dataKey="i" {...AXIS} label={{ value: 'operação nº', position: 'insideBottomRight', offset: -2, fill: '#607884', fontSize: 10 }} />
        <YAxis {...AXIS} width={52} tickFormatter={(v: number) => `${v}R`} />
        <ReferenceLine y={0} stroke="#1f4a5c" />
        <Tooltip
          cursor={{ stroke: '#1f4a5c' }}
          content={(p: TipProps) => (
            <Tip
              {...p}
              render={(d) => (
                <>
                  <p className="text-muted">Operação {String(d.i)} · {shortDate(String(d.date))}</p>
                  <p className="num text-fg">Acumulado {fmt.r(Number(d.cum_r), 2)}</p>
                </>
              )}
            />
          )}
        />
        <Area
          type="monotone"
          dataKey="cum_r"
          stroke="#ff4103"
          strokeWidth={1.75}
          fill="url(#eq-fill)"
          isAnimationActive={false}
          dot={showDots ? { r: 2.4, fill: '#ff6a36', stroke: 'none', filter: 'url(#eq-glow)' } : false}
          activeDot={{ r: 4, fill: '#ff4103', stroke: '#001621', strokeWidth: 2 }}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

/** Distribution of trade results in R. */
export function RHistogram({ data, height = 200 }: { data: { from: number; to: number; count: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data.map((d) => ({ ...d, label: `${d.from}` }))} margin={{ top: 8, right: 8, bottom: 4, left: -16 }}>
        {GRID}
        <XAxis dataKey="label" {...AXIS} interval={1} tickFormatter={(v: string) => `${v}R`} />
        <YAxis {...AXIS} allowDecimals={false} width={40} />
        <Tooltip
          cursor={{ fill: 'rgba(255,255,255,0.03)' }}
          content={(p: TipProps) => (
            <Tip {...p} render={(d) => <p className="num text-fg">{`${d.from}R a ${d.to}R: ${d.count} operações`}</p>} />
          )}
        />
        <Bar dataKey="count" radius={[3, 3, 0, 0]} isAnimationActive={false}>
          {data.map((d) => (
            <Cell key={d.from} fill={d.from < 0 ? '#f2545b' : d.from === 0 ? '#8799a3' : '#3ecf8e'} fillOpacity={0.75} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Values in dollars, or in R (public lab: 0R at the entry, -1R at the stop). */
export type ValueUnit = 'price' | 'R'

function unitFmt(unit: ValueUnit) {
  return {
    tick: (v: number) => (unit === 'R' ? `${v.toFixed(1)}R` : v.toFixed(0)),
    exact: (v: number) => (unit === 'R' ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}R` : v.toFixed(2)),
    value: (v: number) => (unit === 'R' ? fmt.r(v, 2) : fmt.price(v)),
  }
}

/** Monte Carlo fan: 5–95 % and 25–75 % bands of the replay paths, median, stop and target. */
export function FanChart({
  bands,
  times,
  entry,
  stop,
  target,
  height = 300,
  paths,
  unit = 'price',
}: {
  bands: number[][]
  times: string[]
  entry: number
  stop: number
  target: number
  height?: number
  paths?: number[][]
  unit?: ValueUnit
}) {
  const u = unitFmt(unit)
  const data = bands.map((b, i) => ({
    t: times[i],
    outer: [b[0], b[4]],
    inner: [b[1], b[3]],
    median: b[2],
    ...(paths ? Object.fromEntries(paths.slice(0, 24).map((p, k) => [`p${k}`, p[i]])) : {}),
  }))
  const lo = Math.min(stop, ...bands.map((b) => b[0]))
  const hi = Math.max(target, ...bands.map((b) => b[4]))
  const pad = (hi - lo) * 0.06
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 10, right: 78, bottom: 4, left: -4 }}>
        {GRID}
        <XAxis dataKey="t" {...AXIS} minTickGap={36} />
        <YAxis {...AXIS} width={60} domain={[lo - pad, hi + pad]} tickFormatter={u.tick} />
        <Tooltip
          cursor={{ stroke: '#1f4a5c' }}
          content={(p: TipProps) => (
            <Tip
              {...p}
              render={(d) => {
                const o = d.outer as number[]
                const n = d.inner as number[]
                return (
                  <div className="num space-y-0.5">
                    <p className="text-muted">{String(d.t)} ET</p>
                    <p className="text-fg">Mediana {u.value(Number(d.median))}</p>
                    <p className="text-muted">50 % entre {o && n ? `${u.exact(n[0])} e ${u.exact(n[1])}` : '—'}</p>
                    <p className="text-muted">90 % entre {o ? `${u.exact(o[0])} e ${u.exact(o[1])}` : '—'}</p>
                  </div>
                )
              }}
            />
          )}
        />
        <Area dataKey="outer" stroke="none" fill="#7fb6d1" fillOpacity={0.12} isAnimationActive={false} />
        <Area dataKey="inner" stroke="none" fill="#7fb6d1" fillOpacity={0.22} isAnimationActive={false} />
        {paths?.slice(0, 24).map((_, k) => (
          <Line key={k} dataKey={`p${k}`} stroke="#8799a3" strokeOpacity={0.18} strokeWidth={1} dot={false} activeDot={false} isAnimationActive={false} />
        ))}
        <Line dataKey="median" stroke="#e6e8ea" strokeWidth={1.5} dot={false} activeDot={{ r: 3, fill: '#e6e8ea', stroke: '#001621' }} isAnimationActive={false} />
        <ReferenceLine y={target} stroke="#3ecf8e" strokeDasharray="4 4" label={{ value: `alvo ${u.exact(target)}`, position: 'right', fill: '#3ecf8e', fontSize: 10 }} />
        <ReferenceLine y={entry} stroke="#ff4103" strokeOpacity={0.7} label={{ value: `entrada`, position: 'right', fill: '#ff6a36', fontSize: 10 }} />
        <ReferenceLine y={stop} stroke="#f2545b" strokeDasharray="4 4" label={{ value: `stop ${u.exact(stop)}`, position: 'right', fill: '#f2545b', fontSize: 10 }} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

/** Histogram of the simulated price at the end of the session. */
export function CloseHistogram({
  hist,
  entry,
  height = 200,
  unit = 'price',
}: {
  hist: { lo: number; hi: number; bins: number[] }
  entry: number
  height?: number
  unit?: ValueUnit
}) {
  const u = unitFmt(unit)
  const w = (hist.hi - hist.lo) / hist.bins.length
  const total = hist.bins.reduce((a, b) => a + b, 0)
  const data = hist.bins.map((c, i) => ({ x: hist.lo + w * (i + 0.5), from: hist.lo + w * i, to: hist.lo + w * (i + 1), c, share: c / total }))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: -16 }} barCategoryGap={1}>
        {GRID}
        <XAxis dataKey="x" {...AXIS} tickFormatter={u.tick} minTickGap={24} />
        <YAxis {...AXIS} width={40} tickFormatter={(v: number) => fmt.compact(v)} />
        <Tooltip
          cursor={{ fill: 'rgba(255,255,255,0.03)' }}
          content={(p: TipProps) => (
            <Tip
              {...p}
              render={(d) => (
                <p className="num text-fg">
                  {u.exact(Number(d.from))} a {u.exact(Number(d.to))}: {fmt.int(Number(d.c))} replays ({fmt.pct(Number(d.share))})
                </p>
              )}
            />
          )}
        />
        <Bar dataKey="c" isAnimationActive={false}>
          {data.map((d) => (
            <Cell key={d.x} fill={d.to <= entry ? '#f2545b' : d.from >= entry ? '#3ecf8e' : '#8799a3'} fillOpacity={0.6} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export type RadarSeries = { name: string; color: string; values: Record<string, number> }

/** Multi-metric comparison on a 0–100 scale (scale explained by the caller). */
export function RadarScore({ axes, series, height = 300 }: { axes: { key: string; label: string }[]; series: RadarSeries[]; height?: number }) {
  const data = axes.map((a) => ({ axis: a.label, ...Object.fromEntries(series.map((s) => [s.name, s.values[a.key] ?? 0])) }))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <RadarChart data={data} outerRadius="72%">
        <PolarGrid stroke="#12394a" />
        <PolarAngleAxis dataKey="axis" tick={{ fill: '#8799a3', fontSize: 11 }} />
        <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
        <Tooltip
          content={(p) =>
            p.active && p.payload?.length ? (
              <div className="rounded-[var(--radius-md)] border border-line-strong bg-ink/95 px-3 py-2 text-xs">
                <p className="mb-1 text-muted">{String(p.label)}</p>
                {p.payload.map((x) => (
                  <p key={String(x.name)} className="num" style={{ color: x.color }}>
                    {String(x.name)}: {Math.round(Number(x.value))}/100
                  </p>
                ))}
              </div>
            ) : null
          }
        />
        {series.map((s) => (
          <Radar key={s.name} name={s.name} dataKey={s.name} stroke={s.color} fill={s.color} fillOpacity={0.12} strokeWidth={1.75} isAnimationActive={false} />
        ))}
      </RadarChart>
    </ResponsiveContainer>
  )
}

/** Two-series stacked area for period comparisons (after uiable chart-area). */
export function PeriodArea({ data, height = 220 }: { data: { month: string; sum_r: number; trades: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: -12 }}>
        <defs>
          <linearGradient id="pa-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#7fb6d1" stopOpacity={0.3} />
            <stop offset="1" stopColor="#7fb6d1" stopOpacity={0} />
          </linearGradient>
        </defs>
        {GRID}
        <XAxis dataKey="month" {...AXIS} />
        <YAxis yAxisId="r" {...AXIS} width={44} tickFormatter={(v: number) => `${v}R`} />
        <YAxis yAxisId="n" orientation="right" {...AXIS} width={30} allowDecimals={false} />
        <ReferenceLine yAxisId="r" y={0} stroke="#1f4a5c" />
        <Tooltip
          content={(p: TipProps) => (
            <Tip
              {...p}
              render={(d) => (
                <div className="num">
                  <p className="text-muted">{String(d.month)}</p>
                  <p className="text-fg">Soma {fmt.r(Number(d.sum_r), 2)}</p>
                  <p className="text-muted">{String(d.trades)} operações</p>
                </div>
              )}
            />
          )}
        />
        <Bar yAxisId="n" dataKey="trades" fill="#1f4a5c" radius={[2, 2, 0, 0]} isAnimationActive={false} />
        <Area yAxisId="r" dataKey="sum_r" type="monotone" stroke="#7fb6d1" fill="url(#pa-fill)" strokeWidth={1.5} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

/** Cumulative return in % of the first close: the public lab's chart, with no price level. */
export function ReturnChart({ time, values, intraday, height = 300 }: { time: number[]; values: (number | null)[]; intraday: boolean; height?: number }) {
  const data = time.map((t, i) => ({ t, v: values[i] }))
  const label = (t: number) =>
    new Date(t * 1000).toLocaleString('pt-BR', intraday ? { timeZone: 'America/New_York', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' } : { day: '2-digit', month: '2-digit', year: '2-digit' })
  const last = [...values].reverse().find((v) => v != null) ?? 0
  const color = last >= 0 ? '#3ecf8e' : '#f2545b'
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 10, right: 8, bottom: 4, left: -8 }}>
        {GRID}
        <XAxis dataKey="t" {...AXIS} tickFormatter={label} minTickGap={48} />
        <YAxis {...AXIS} width={52} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
        <ReferenceLine y={0} stroke="#8799a3" strokeOpacity={0.5} />
        <Tooltip
          cursor={{ stroke: '#1f4a5c' }}
          content={(p: TipProps) => <Tip {...p} render={(d) => <p className="num text-fg">{label(Number(d.t))} · {fmt.signedPct(Number(d.v))}</p>} />}
        />
        <Area dataKey="v" stroke={color} fill={color} fillOpacity={0.12} strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls />
      </AreaChart>
    </ResponsiveContainer>
  )
}
