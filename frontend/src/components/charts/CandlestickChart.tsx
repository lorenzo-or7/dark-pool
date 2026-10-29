/**
 * OHLC + volume on TradingView Lightweight Charts (the approved Candlestick
 * Chart reference, bklitai, needs a 21st.dev login; market data needs a
 * library that handles OHLC precisely). Times are shown in New York time.
 */
import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useEffect, useRef } from 'react'
import type { Bar } from '@/lib/types'

const NY = 'America/New_York'
const offsetCache = new Map<number, number>()

/** Shift a UTC timestamp so the chart's UTC axis reads New York wall-clock time. */
function nyShift(ts: number) {
  const hourKey = Math.floor(ts / 3600)
  let off = offsetCache.get(hourKey)
  if (off === undefined) {
    const d = new Date(ts * 1000)
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: NY, hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
    }).formatToParts(d)
    const g = (t: string) => Number(parts.find((p) => p.type === t)?.value)
    const asUtc = Date.UTC(g('year'), g('month') - 1, g('day'), g('hour') % 24, g('minute'), g('second'))
    off = Math.round((asUtc - d.getTime()) / 1000)
    offsetCache.set(hourKey, off)
  }
  return (ts + off) as UTCTimestamp
}

export type Overlay = { id: string; color: string; values: (number | null)[]; width?: number }
export type PriceLine = { price: number; color: string; title: string; dashed?: boolean }

type Props = {
  bars: Bar[]
  intraday: boolean
  overlays?: Overlay[]
  priceLines?: PriceLine[]
  height?: number
  ariaLabel: string
  /** Show only the first N bars (market replay). Later bars are never drawn. */
  visibleCount?: number
}

export function CandlestickChart({ bars, intraday, overlays = [], priceLines = [], height = 380, ariaLabel, visibleCount }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const chart = useRef<IChartApi | null>(null)
  const candles = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volume = useRef<ISeriesApi<'Histogram'> | null>(null)
  const lines = useRef<Map<string, ISeriesApi<'Line'>>>(new Map())
  const priceLineRefs = useRef<ReturnType<ISeriesApi<'Candlestick'>['createPriceLine']>[]>([])

  useEffect(() => {
    if (!box.current) return
    const c = createChart(box.current, {
      autoSize: true,
      height,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#8799a3',
        fontFamily: 'IBM Plex Mono, monospace',
        fontSize: 11,
        attributionLogo: false,
      },
      grid: { vertLines: { color: 'rgba(18,57,74,0.55)' }, horzLines: { color: 'rgba(18,57,74,0.55)' } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: '#1f4a5c', labelBackgroundColor: '#0b3242' }, horzLine: { color: '#1f4a5c', labelBackgroundColor: '#0b3242' } },
      rightPriceScale: { borderColor: '#12394a' },
      timeScale: { borderColor: '#12394a', timeVisible: intraday, secondsVisible: false, rightOffset: 4 },
      localization: { locale: 'pt-BR', priceFormatter: (p: number) => p.toFixed(2) },
    })
    candles.current = c.addSeries(CandlestickSeries, {
      upColor: '#3ecf8e', downColor: '#f2545b', borderUpColor: '#3ecf8e', borderDownColor: '#f2545b',
      wickUpColor: '#3ecf8e', wickDownColor: '#f2545b', priceLineColor: '#ff4103',
    })
    volume.current = c.addSeries(HistogramSeries, { priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false })
    c.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
    chart.current = c
    const lineMap = lines.current
    return () => {
      lineMap.clear()
      priceLineRefs.current = []
      c.remove()
      chart.current = null
    }
  }, [height, intraday])

  useEffect(() => {
    const c = chart.current
    if (!c || !candles.current || !volume.current) return
    const n = visibleCount == null ? bars.length : Math.max(0, Math.min(bars.length, visibleCount))
    const shown = bars.slice(0, n)
    const t = (b: Bar) => (intraday ? nyShift(b.time) : (nyShift(b.time) - (nyShift(b.time) % 86400)) as UTCTimestamp)
    candles.current.setData(shown.map((b) => ({ time: t(b), open: b.open, high: b.high, low: b.low, close: b.close })))
    volume.current.setData(
      shown.map((b) => ({ time: t(b), value: b.volume, color: b.close >= b.open ? 'rgba(62,207,142,0.35)' : 'rgba(242,84,91,0.35)' })),
    )
    const seen = new Set<string>()
    for (const o of overlays) {
      seen.add(o.id)
      let s = lines.current.get(o.id)
      if (!s) {
        s = c.addSeries(LineSeries, { color: o.color, lineWidth: (o.width ?? 1.5) as 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
        lines.current.set(o.id, s)
      }
      s.setData(shown.flatMap((b, i) => (o.values[i] == null ? [] : [{ time: t(b), value: o.values[i] as number }])))
    }
    for (const [id, s] of lines.current) {
      if (!seen.has(id)) {
        c.removeSeries(s)
        lines.current.delete(id)
      }
    }
    for (const pl of priceLineRefs.current) candles.current.removePriceLine(pl)
    priceLineRefs.current = priceLines.map((p) =>
      candles.current!.createPriceLine({ price: p.price, color: p.color, title: p.title, lineWidth: 1, lineStyle: p.dashed ? 2 : 0, axisLabelVisible: true }),
    )
    if (n > 0) c.timeScale().fitContent()
  }, [bars, overlays, priceLines, visibleCount, intraday])

  return <div ref={box} role="img" aria-label={ariaLabel} className="w-full" style={{ height }} />
}
