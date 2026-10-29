const nf = (min: number, max: number) =>
  new Intl.NumberFormat('pt-BR', { minimumFractionDigits: min, maximumFractionDigits: max })

const n0 = nf(0, 0)
const n2 = nf(2, 2)
const n3 = nf(0, 3)

export const fmt = {
  int: (v: number | null | undefined) => (v == null ? '—' : n0.format(v)),
  price: (v: number | null | undefined) => (v == null ? '—' : `US$ ${n2.format(v)}`),
  num: (v: number | null | undefined, digits = 2) => (v == null ? '—' : nf(digits, digits).format(v)),
  pct: (v: number | null | undefined, digits = 1) => (v == null ? '—' : `${nf(digits, digits).format(v * 100)} %`),
  signedPct: (v: number | null | undefined, digits = 2) =>
    v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${nf(digits, digits).format(Math.abs(v))} %`,
  r: (v: number | null | undefined, digits = 3) =>
    v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${nf(digits, digits).format(Math.abs(v))} R`,
  compact: (v: number | null | undefined) =>
    v == null ? '—' : new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 }).format(v),
  plain: (v: number | null | undefined) => (v == null ? '—' : n3.format(v)),
}

const NY = 'America/New_York'

export function nyDateTime(iso: string | number | null | undefined) {
  if (iso == null) return '—'
  const d = typeof iso === 'number' ? new Date(iso * 1000) : new Date(iso)
  return `${d.toLocaleString('pt-BR', { timeZone: NY, day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })} ET`
}

export function localDateTime(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function shortDate(iso: string | null | undefined) {
  if (!iso) return '—'
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${d}/${m}/${y}`
}

export function relative(iso: string | null | undefined) {
  if (!iso) return '—'
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  const rtf = new Intl.RelativeTimeFormat('pt-BR', { numeric: 'auto' })
  if (Math.abs(diff) < 60) return 'agora'
  if (Math.abs(diff) < 3600) return rtf.format(-Math.round(diff / 60), 'minute')
  if (Math.abs(diff) < 86400) return rtf.format(-Math.round(diff / 3600), 'hour')
  return rtf.format(-Math.round(diff / 86400), 'day')
}

export function todayNY() {
  const p = new Intl.DateTimeFormat('en-CA', { timeZone: NY, year: 'numeric', month: '2-digit', day: '2-digit' })
  return p.format(new Date())
}
