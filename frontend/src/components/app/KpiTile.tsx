/**
 * KPI tile (after konsstepnov "KPI Tile", rebuilt: the 21st.dev source needs a
 * login). The value rolls with React Bits Counter, the change arrow turns with
 * its sign, the sparkline draws in and can be inspected with the pointer or
 * the arrow keys. Loading and empty states. Values are never invented: pass
 * null and the tile says why there is no number.
 */
import { ArrowUp } from 'lucide-react'
import { useId, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import Counter from '@/components/reactbits/Counter'
import { DataBadge, type DataKind } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/states'
import { cn } from '@/lib/utils'

type Props = {
  label: string
  value: number | null
  format?: Intl.NumberFormatOptions
  decimals?: number
  suffix?: ReactNode
  prefix?: ReactNode
  change?: number | null
  changeLabel?: string
  spark?: { label: string; value: number }[]
  kind?: DataKind
  empty?: string
  loading?: boolean
  footnote?: ReactNode
  className?: string
}

export function KpiTile({ label, value, decimals = 0, suffix, prefix, change, changeLabel, spark, kind, empty = 'Sem dados ainda', loading, footnote, className }: Props) {
  const [idx, setIdx] = useState<number | null>(null)
  const id = useId()
  const pts = spark ?? []
  const W = 160
  const H = 36
  const vals = pts.map((p) => p.value)
  const lo = Math.min(...vals)
  const hi = Math.max(...vals)
  const x = (i: number) => (pts.length <= 1 ? 0 : (i / (pts.length - 1)) * W)
  const y = (v: number) => (hi === lo ? H / 2 : H - 3 - ((v - lo) / (hi - lo)) * (H - 6))
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join('')

  function onPointer(e: PointerEvent<SVGSVGElement>) {
    const r = e.currentTarget.getBoundingClientRect()
    const i = Math.round(((e.clientX - r.left) / r.width) * (pts.length - 1))
    setIdx(Math.max(0, Math.min(pts.length - 1, i)))
  }
  function onKey(e: KeyboardEvent) {
    if (!pts.length) return
    if (e.key === 'ArrowLeft') setIdx((i) => Math.max(0, (i ?? pts.length) - 1))
    else if (e.key === 'ArrowRight') setIdx((i) => Math.min(pts.length - 1, (i ?? -1) + 1))
    else if (e.key === 'Escape') setIdx(null)
    else return
    e.preventDefault()
  }

  return (
    <div className={cn('panel flex min-h-[132px] flex-col justify-between gap-3 p-4', className)}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-[13px] text-muted">{label}</p>
        {kind && <DataBadge kind={kind} />}
      </div>
      {loading ? (
        <Skeleton className="h-8 w-28" />
      ) : value == null ? (
        <p className="text-sm text-faint">{empty}</p>
      ) : (
        <div className="flex items-end justify-between gap-3">
          <div className="flex items-baseline gap-1 font-display text-[28px] leading-none font-medium text-fg">
            {prefix}
            <span className="sr-only">{value.toLocaleString('pt-BR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}</span>
            <span aria-hidden>
              <Counter value={value} decimals={decimals} locale="pt-BR" fontSize={28} fontWeight={500} textColor="currentColor" tabular intro={false} />
            </span>
            {suffix && <span className="text-base text-muted">{suffix}</span>}
          </div>
          {change != null && (
            <span className={cn('num inline-flex items-center gap-1 text-xs', change > 0 ? 'text-up' : change < 0 ? 'text-down' : 'text-muted')}>
              <ArrowUp className="size-3.5 transition-transform duration-300" style={{ transform: `rotate(${change > 0 ? 0 : change < 0 ? 180 : 90}deg)` }} aria-hidden />
              {changeLabel}
            </span>
          )}
        </div>
      )}
      {pts.length > 1 && !loading && value != null && (
        <div className="relative">
          <svg
            viewBox={`0 0 ${W} ${H}`}
            preserveAspectRatio="none"
            className="h-9 w-full cursor-crosshair overflow-visible focus-visible:outline-offset-4"
            onPointerMove={onPointer}
            onPointerLeave={() => setIdx(null)}
            tabIndex={0}
            onKeyDown={onKey}
            role="img"
            aria-label={`${label}: série de ${pts.length} pontos. Use as setas para inspecionar.`}
            aria-describedby={`${id}-v`}
          >
            <path d={d} fill="none" stroke="#ff4103" strokeWidth="1.5" vectorEffect="non-scaling-stroke" pathLength={1} className="kpi-draw" />
            {idx != null && <circle cx={x(idx)} cy={y(pts[idx].value)} r="2.5" fill="#ff6a36" vectorEffect="non-scaling-stroke" />}
          </svg>
          <p id={`${id}-v`} className="num mt-1 h-4 text-[11px] text-muted" aria-live="polite">
            {idx != null ? `${pts[idx].label}: ${pts[idx].value.toLocaleString('pt-BR', { maximumFractionDigits: 3 })}` : ''}
          </p>
        </div>
      )}
      {footnote && <div className="text-[11px] leading-snug text-faint">{footnote}</div>}
    </div>
  )
}

export function Sparkline({ values, className, up }: { values: number[]; className?: string; up?: boolean }) {
  if (values.length < 2) return <span className="text-xs text-faint">—</span>
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const d = values.map((v, i) => `${i ? 'L' : 'M'}${((i / (values.length - 1)) * 100).toFixed(1)},${(hi === lo ? 12 : 22 - ((v - lo) / (hi - lo)) * 20).toFixed(1)}`).join('')
  const rising = up ?? values[values.length - 1] >= values[0]
  return (
    <svg viewBox="0 0 100 24" preserveAspectRatio="none" className={cn('h-6 w-20', className)} aria-hidden>
      <path d={d} fill="none" stroke={rising ? '#3ecf8e' : '#f2545b'} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
