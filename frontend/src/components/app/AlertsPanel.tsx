import { useMutation } from '@tanstack/react-query'
import { BellRing, Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input, Select } from '@/components/ui/field'
import { ErrorState } from '@/components/ui/states'
import { api } from '@/lib/api'
import { fmt } from '@/lib/format'

/** One trader-alerts rule, in the engine's own format. */
type AlertRule = { id: string; type: 'above' | 'below' | 'pct_move' | 'opening_bell'; symbol?: string; price?: number; pct?: number }
type AlertState = { rung: Record<string, string>; last_check?: string | null }
type CheckRes = {
  rings: { id: string; symbol: string; message: string }[]
  state: AlertState
  market: { now_new_york: string; open: boolean; reason: string; next_open?: string }
  quotes: Record<string, { price?: number; change_pct: number | null; time?: string; prices_hidden?: boolean }>
  errors: { symbol: string; message: string }[]
  source: { provider: string; feed: string | null; delayed?: boolean; provenance: { provider_name: string } }
  prices_hidden: boolean
  note: string
}

const KEY = 'dp.alerts.v1'
const TYPES: { value: AlertRule['type']; label: string }[] = [
  { value: 'above', label: 'Preço acima de' },
  { value: 'below', label: 'Preço abaixo de' },
  { value: 'pct_move', label: 'Variação do dia ≥ %' },
]

// Rules and what already rang belong to this browser (localStorage): the lab keeps no alerts on the server.
function load(): { rules: AlertRule[]; state: AlertState } {
  try {
    const raw = localStorage.getItem(KEY)
    const v = raw ? (JSON.parse(raw) as { rules?: AlertRule[]; state?: AlertState }) : {}
    return { rules: Array.isArray(v.rules) ? v.rules.slice(0, 50) : [], state: v.state ?? { rung: {} } }
  } catch {
    return { rules: [], state: { rung: {} } }
  }
}

function save(v: { rules: AlertRule[]; state: AlertState }) {
  try {
    localStorage.setItem(KEY, JSON.stringify(v))
  } catch {
    /* private mode or full storage: alerts last for this page only */
  }
}

function describe(r: AlertRule): string {
  if (r.type === 'opening_bell') return 'Abertura da NYSE'
  if (r.type === 'pct_move') return `${r.symbol} variar ${fmt.num(r.pct ?? 0, 1)} % ou mais no dia`
  return `${r.symbol} ${r.type === 'above' ? 'acima de' : 'abaixo de'} ${fmt.num(r.price ?? 0)}`
}

/** trader-alerts on demand: the visitor's rules are checked when they press the button, never on a timer. */
export function AlertsPanel() {
  const [data, setData] = useState(load)
  const [symbol, setSymbol] = useState('')
  const [type, setType] = useState<AlertRule['type']>('above')
  const [value, setValue] = useState('')
  const update = (v: { rules: AlertRule[]; state: AlertState }) => {
    setData(v)
    save(v)
  }
  const check = useMutation({
    mutationFn: () => api<CheckRes>('/alerts/check', { body: { rules: data.rules, state: data.state } }),
    onSuccess: (r) => update({ rules: data.rules, state: r.state }),
  })

  const sym = symbol.trim().toUpperCase()
  const num = Number(value)
  const valid = /^[A-Z]{1,5}(\.[A-Z])?$/.test(sym) && num > 0 && (type !== 'pct_move' || num <= 100)

  function add(e: FormEvent) {
    e.preventDefault()
    if (!valid || data.rules.length >= 50) return
    const id = `${sym.toLowerCase()}-${type}-${Date.now().toString(36)}`
    const rule: AlertRule = type === 'pct_move' ? { id, type, symbol: sym, pct: num } : { id, type, symbol: sym, price: num }
    update({ ...data, rules: [...data.rules, rule] })
    setValue('')
  }

  function addBell() {
    if (data.rules.some((r) => r.type === 'opening_bell')) return
    update({ ...data, rules: [...data.rules, { id: 'opening-bell', type: 'opening_bell' }] })
  }

  function remove(id: string) {
    const rung = { ...data.state.rung }
    delete rung[id]
    update({ rules: data.rules.filter((r) => r.id !== id), state: { ...data.state, rung } })
  }

  const r = check.data
  return (
    <section className="panel mt-4 p-4 sm:p-5" aria-labelledby="al-h">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id="al-h" className="text-base font-medium text-fg">
          Alertas
        </h2>
        <span className="text-[11px] text-faint">trader-alerts · regras guardadas neste navegador</span>
      </div>
      <form onSubmit={add} className="grid grid-cols-2 gap-2 sm:grid-cols-[110px_1fr_120px_auto]">
        <Input aria-label="Ticker do alerta" placeholder="Ticker" value={symbol} onChange={(e) => setSymbol(e.target.value)} />
        <Select aria-label="Tipo de alerta" value={type} onChange={(e) => setType(e.target.value as AlertRule['type'])}>
          {TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </Select>
        <Input aria-label={type === 'pct_move' ? 'Variação em %' : 'Preço'} type="number" step="0.01" inputMode="decimal" placeholder={type === 'pct_move' ? '%' : 'US$'} value={value} onChange={(e) => setValue(e.target.value)} />
        <Button type="submit" size="sm" disabled={!valid || data.rules.length >= 50}>
          <Plus /> Adicionar
        </Button>
      </form>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button size="sm" variant="primary" disabled={!data.rules.length || check.isPending} onClick={() => check.mutate()}>
          <BellRing /> {check.isPending ? 'Verificando…' : 'Verificar agora'}
        </Button>
        <Button size="sm" variant="ghost" onClick={addBell} disabled={data.rules.some((x) => x.type === 'opening_bell')}>
          Sino de abertura
        </Button>
      </div>
      {data.rules.length > 0 ? (
        <ul className="mt-3 divide-y divide-line text-sm">
          {data.rules.map((x) => (
            <li key={x.id} className="flex items-center justify-between gap-2 py-1.5">
              <span className="text-fg/90">{describe(x)}</span>
              <span className="flex items-center gap-2">
                {data.state.rung[x.id] && <Badge tone="caution">disparou</Badge>}
                <button type="button" onClick={() => remove(x.id)} className="rounded p-1 text-muted hover:text-down" aria-label={`Remover alerta: ${describe(x)}`}>
                  <Trash2 className="size-3.5" />
                </button>
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-faint">Nenhum alerta. Os alertas são verificados quando você clica em “Verificar agora”.</p>
      )}
      {check.isError && <ErrorState error={check.error} className="mt-3" />}
      {r && (
        <div className="mt-3 rounded-[var(--radius-md)] border border-line bg-abyss/40 p-3 text-sm" aria-live="polite">
          {r.rings.length ? (
            <ul className="space-y-1">
              {r.rings.map((x) => (
                <li key={x.id} className="text-fg">
                  {x.message}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-muted">Nada disparou nesta verificação.</p>
          )}
          {r.errors.map((e) => (
            <p key={e.symbol} className="mt-1 text-xs text-caution">
              {e.message}
            </p>
          ))}
          <p className="mt-2 text-[11px] text-faint">
            NYSE {r.market.open ? 'aberta' : 'fechada'} ({r.market.now_new_york} em Nova York) · cotações: {r.source.provenance.provider_name}
            {r.source.feed ? ` · feed ${r.source.feed}` : ''}
            {r.source.delayed ? ' · com atraso' : ''}. {r.note}
          </p>
        </div>
      )}
    </section>
  )
}
