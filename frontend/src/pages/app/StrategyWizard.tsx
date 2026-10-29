import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/app/AppShell'
import Stepper, { Step } from '@/components/reactbits/Stepper'
import { DataBadge } from '@/components/ui/badge'
import { Field, Input, Select, Textarea } from '@/components/ui/field'
import { ErrorState, Notice, Spinner } from '@/components/ui/states'
import { api } from '@/lib/api'
import { fmt } from '@/lib/format'
import { boundLabel, defaultConfig, describe, PARAMS, RULES, STOP_LABEL } from '@/lib/strategy'
import type { RuleType, Strategy, StrategyConfig } from '@/lib/types'
import { cn } from '@/lib/utils'

const stepperTheme = {
  '--stepper-frame': 'rgba(3,30,43,0.92)',
  '--stepper-frame-edge': '#12394a',
  '--stepper-frame-highlight': 'rgba(255,255,255,0.03)',
  '--stepper-tile': 'linear-gradient(180deg,#0b3242 0%,#072835 100%)',
  '--stepper-tile-edge': '#1f4a5c',
  '--stepper-well': 'rgba(0,12,19,0.55)',
  '--stepper-track': '#12394a',
  '--stepper-ink': '#e6e8ea',
  '--stepper-muted': '#8799a3',
  '--stepper-faint': '#1f4a5c',
  '--stepper-ring': 'rgba(255,65,3,0.45)',
} as React.CSSProperties

type Sizing = {
  sizing: { qty: number; risk_per_share: number; max_loss: number; bound_by: string; refusal: string | null } | null
  refusal?: string
  risk: { pass: number; block: number; results: { verdict?: string; reasons?: string[] }[] } | null
  note: string
}

function NumberField({ label, value, onChange, min, max, step, unit, hint }: { label: string; value: number; onChange: (n: number) => void; min: number; max: number; step: number; unit?: string; hint?: string }) {
  const bad = !(value >= min && value <= max)
  return (
    <Field label={`${label}${unit ? ` (${unit})` : ''}`} hint={hint ?? `Entre ${min} e ${max}.`} error={bad ? `Use um valor entre ${min} e ${max}.` : null}>
      {(p) => <Input {...p} type="number" inputMode="decimal" min={min} max={max} step={step} value={Number.isFinite(value) ? value : ''} onChange={(e) => onChange(e.target.valueAsNumber)} />}
    </Field>
  )
}

export default function StrategyWizard() {
  const { id } = useParams()
  const [sp] = useSearchParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const existing = useQuery({ queryKey: ['strategy', id], queryFn: ({ signal }) => api<Strategy>(`/strategies/${id}`, { signal }), enabled: !!id })
  const [cfg, setCfg] = useState<StrategyConfig>(() => defaultConfig((sp.get('symbol') ?? '').toUpperCase()))
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [note, setNote] = useState('')
  const [step, setStep] = useState(1)

  useEffect(() => {
    const s = existing.data
    if (!s) return
    const v = s.versions?.find((x) => x.version === s.current_version)
    if (v) setCfg(v.config)
    setName(s.name)
    setDesc(s.description ?? '')
  }, [existing.data])

  const set = <K extends keyof StrategyConfig>(k: K, v: StrategyConfig[K]) => setCfg((c) => ({ ...c, [k]: v }))
  const setRule = (type: RuleType) =>
    setCfg((c) => {
      const d = defaultConfig(c.symbol, type)
      const wasOrb = c.rule.type === 'orb'
      return { ...c, rule: d.rule, exit: type === 'orb' || wasOrb ? { ...c.exit, stop_type: d.exit.stop_type, stop_value: d.exit.stop_value } : c.exit }
    })

  const symOk = /^[A-Z]{1,5}(\.[A-Z])?$/.test(cfg.symbol)
  const paramsOk = PARAMS[cfg.rule.type].every((p) => cfg.rule.params[p.key] >= p.min && cfg.rule.params[p.key] <= p.max) &&
    (!['sma_cross', 'macd_cross'].includes(cfg.rule.type) || cfg.rule.params.fast < cfg.rule.params.slow)
  const exitOk = cfg.exit.target_r >= 0.25 && cfg.exit.target_r <= 10 && (cfg.exit.stop_type.startsWith('or') || (cfg.exit.stop_value > 0 && cfg.exit.stop_value <= 50)) && cfg.exit.max_hold_bars >= 1
  const riskOk = cfg.risk.account_size > 0 && cfg.risk.max_loss_per_trade > 0 && cfg.risk.max_position_pct > 0 && cfg.risk.max_position_pct <= 100
  const valid = [symOk, true, paramsOk, exitOk, riskOk, name.trim().length >= 2]

  // Simulated sizing preview from the last close (trader-budget + trader-risk).
  const price = useQuery({
    queryKey: ['chart', cfg.symbol, '1mo'],
    queryFn: ({ signal }) => api<{ bars: { close: number; time: number }[]; indicators: { atr14: (number | null)[] } }>(`/assets/${cfg.symbol}/chart?range=1mo`, { signal }),
    enabled: symOk && step >= 5,
  })
  const last = price.data?.bars.at(-1)?.close
  const atr = price.data?.indicators.atr14.filter((x) => x != null).at(-1) ?? null
  const preview = useMemo(() => {
    if (!last) return null
    const stop = cfg.exit.stop_type === 'pct' ? last * (1 - cfg.exit.stop_value / 100) : cfg.exit.stop_type === 'atr' && atr ? last - cfg.exit.stop_value * atr : null
    if (stop == null || stop <= 0) return null
    const s = Math.floor(stop * 100) / 100
    return { entry: Math.round(last * 100) / 100, stop: s, target: Math.round((last + cfg.exit.target_r * (last - s)) * 100) / 100 }
  }, [last, atr, cfg.exit])
  const sizing = useQuery({
    queryKey: ['risk', cfg.symbol, preview, cfg.risk],
    queryFn: ({ signal }) =>
      api<Sizing>('/risk/check', {
        body: { symbol: cfg.symbol, date: new Date().toISOString().slice(0, 10), entry: preview!.entry, stop: preview!.stop, target: preview!.target, entry_time: '10:15', risk: cfg.risk },
        signal,
      }),
    enabled: !!preview && step >= 5 && riskOk,
  })

  const save = useMutation({
    mutationFn: () =>
      id
        ? api<Strategy>(`/strategies/${id}`, { method: 'PATCH', body: { name, description: desc, config: cfg, note } })
        : api<Strategy>('/strategies', { body: { name, description: desc, config: cfg, note } }),
    onSuccess: (s) => {
      void qc.invalidateQueries({ queryKey: ['strategies'] })
      void qc.invalidateQueries({ queryKey: ['strategy', s.id] })
      void qc.invalidateQueries({ queryKey: ['dashboard'] })
      nav(`/app/strategies/${s.id}`)
    },
  })

  if (id && existing.isLoading) return <Spinner />
  if (id && existing.isError) return <ErrorState error={existing.error} />

  const ruleMeta = RULES.find((r) => r.type === cfg.rule.type)!
  const stopOptions = cfg.rule.type === 'orb' ? (['or_mid', 'or_low', 'pct'] as const) : (['pct', 'atr'] as const)

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        eyebrow="Strategy Lab"
        title={id ? `Editar ${existing.data?.name ?? ''}` : 'Nova estratégia'}
        description={id ? 'Salvar com mudanças na configuração cria uma nova versão; as anteriores ficam guardadas.' : 'Defina a regra em seis etapas. Tudo aqui é configuração de pesquisa; nenhuma ordem é criada.'}
      >
        <Link to={id ? `/app/strategies/${id}` : '/app/strategies'} className="text-sm text-muted hover:text-ember">
          Cancelar
        </Link>
      </PageHeader>

      <Stepper
        step={step}
        onStepChange={setStep}
        onFinalStepCompleted={() => save.mutate()}
        linear
        width="100%"
        radius={16}
        accentColor="#ff4103"
        style={stepperTheme}
        backButtonText="Voltar"
        nextButtonText="Continuar"
        completeButtonText={save.isPending ? 'Salvando…' : id ? 'Salvar nova versão' : 'Salvar estratégia'}
        nextButtonProps={{ disabled: !valid[step - 1] || save.isPending }}
        completedContent={
          save.isError ? (
            <div className="space-y-3 p-1">
              <ErrorState error={save.error} />
              <button className="text-sm text-ember hover:underline" onClick={() => setStep(6)}>
                Voltar à revisão
              </button>
            </div>
          ) : (
            <Spinner label="Salvando" />
          )
        }
      >
        <Step title="Ativo">
          <div className="space-y-3 pt-2">
            <Field label="Ticker" hint="Ação dos EUA. Ex.: TSLA, AAPL, BRK.B." error={cfg.symbol && !symOk ? 'Ticker inválido.' : null}>
              {(p) => <Input {...p} value={cfg.symbol} onChange={(e) => set('symbol', e.target.value.toUpperCase().trim())} autoFocus placeholder="TSLA" className="num uppercase" />}
            </Field>
            <p className="text-xs text-muted">
              Não sabe o ticker? Pesquise no{' '}
              <Link to="/app/scanner" className="text-ember hover:underline">
                Market Scanner
              </Link>{' '}
              e use “Enviar ao Strategy Lab”.
            </p>
          </div>
        </Step>
        <Step title="Estratégia">
          <fieldset className="grid gap-2 pt-2 sm:grid-cols-2">
            <legend className="sr-only">Regra da estratégia</legend>
            {RULES.map((r) => (
              <label key={r.type} className={cn('flex cursor-pointer flex-col gap-1 rounded-[var(--radius-md)] border p-3 transition-colors', cfg.rule.type === r.type ? 'border-ember/60 bg-ember/5' : 'border-line-strong hover:border-muted/40')}>
                <span className="flex items-center gap-2">
                  <input type="radio" name="rule" value={r.type} checked={cfg.rule.type === r.type} onChange={() => setRule(r.type)} className="accent-[#ff4103]" />
                  <span className="text-sm text-fg">{r.label}</span>
                </span>
                <span className="pl-5 text-xs text-muted">{r.summary}</span>
                <span className="num pl-5 text-[10.5px] text-faint">candles de {r.interval === '5m' ? '5 minutos' : '1 dia'}</span>
              </label>
            ))}
          </fieldset>
        </Step>
        <Step title="Entrada">
          <div className="space-y-4 pt-2">
            <p className="text-sm text-muted">{ruleMeta.summary}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              {PARAMS[cfg.rule.type].map((p) => (
                <NumberField
                  key={p.key}
                  label={p.label}
                  unit={p.unit}
                  min={p.min}
                  max={p.max}
                  step={p.step}
                  value={cfg.rule.params[p.key]}
                  onChange={(n) => setCfg((c) => ({ ...c, rule: { ...c.rule, params: { ...c.rule.params, [p.key]: n } } }))}
                />
              ))}
            </div>
            {['sma_cross', 'macd_cross'].includes(cfg.rule.type) && cfg.rule.params.fast >= cfg.rule.params.slow && <Notice tone="caution">A média rápida precisa ser menor que a lenta.</Notice>}
            {cfg.rule.type !== 'orb' && (
              <div className="grid gap-3 sm:grid-cols-2">
                <NumberField label="Preço mínimo" unit="US$" min={0} max={100000} step={1} value={cfg.filters.min_price} onChange={(n) => set('filters', { ...cfg.filters, min_price: n })} />
                <NumberField label="Volume médio mínimo (20 dias)" min={0} max={1e10} step={100000} value={cfg.filters.min_avg_volume} onChange={(n) => set('filters', { ...cfg.filters, min_avg_volume: n })} hint="0 desativa o filtro." />
              </div>
            )}
            <p className="text-xs text-faint">O sinal usa apenas dados até o fechamento do candle; a entrada simulada acontece no candle seguinte.</p>
          </div>
        </Step>
        <Step title="Saída">
          <div className="space-y-4 pt-2">
            <Field label="Tipo de stop">
              {(p) => (
                <Select {...p} value={cfg.exit.stop_type} onChange={(e) => set('exit', { ...cfg.exit, stop_type: e.target.value as StrategyConfig['exit']['stop_type'], stop_value: e.target.value.startsWith('or') ? 0 : cfg.exit.stop_value || 2 })}>
                  {stopOptions.map((o) => (
                    <option key={o} value={o}>
                      {STOP_LABEL[o]}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              {!cfg.exit.stop_type.startsWith('or') && (
                <NumberField label={cfg.exit.stop_type === 'atr' ? 'Múltiplo do ATR' : 'Distância do stop'} unit={cfg.exit.stop_type === 'pct' ? '%' : '×'} min={0.1} max={50} step={0.1} value={cfg.exit.stop_value} onChange={(n) => set('exit', { ...cfg.exit, stop_value: n })} />
              )}
              <NumberField label="Alvo" unit="R" min={0.25} max={10} step={0.25} value={cfg.exit.target_r} onChange={(n) => set('exit', { ...cfg.exit, target_r: n })} hint="1R = a distância entre entrada e stop." />
              {cfg.rule.type === 'orb' ? (
                <Field label="Encerrar até (Nova York)" hint="Operações abertas são fechadas neste horário.">
                  {(p) => <Input {...p} type="time" min="09:45" max="16:00" step={300} value={cfg.exit.flat_by} onChange={(e) => set('exit', { ...cfg.exit, flat_by: e.target.value })} />}
                </Field>
              ) : (
                <NumberField label="Duração máxima" unit="sessões" min={1} max={120} step={1} value={cfg.exit.max_hold_bars} onChange={(n) => set('exit', { ...cfg.exit, max_hold_bars: n })} />
              )}
            </div>
          </div>
        </Step>
        <Step title="Risco">
          <div className="space-y-4 pt-2">
            <div className="grid gap-3 sm:grid-cols-2">
              <NumberField label="Capital simulado" unit="US$" min={1} max={1e9} step={500} value={cfg.risk.account_size} onChange={(n) => set('risk', { ...cfg.risk, account_size: n })} />
              <NumberField label="Perda máxima por operação" unit="US$" min={1} max={1e7} step={10} value={cfg.risk.max_loss_per_trade} onChange={(n) => set('risk', { ...cfg.risk, max_loss_per_trade: n })} />
              <NumberField label="Posição máxima" unit="% do capital" min={1} max={100} step={1} value={cfg.risk.max_position_pct} onChange={(n) => set('risk', { ...cfg.risk, max_position_pct: n })} />
              <NumberField label="Limite de perda diária" unit="US$" min={1} max={1e7} step={10} value={cfg.risk.daily_loss_limit} onChange={(n) => set('risk', { ...cfg.risk, daily_loss_limit: n })} />
              <NumberField label="Operações por dia" min={1} max={50} step={1} value={cfg.risk.max_trades_per_day} onChange={(n) => set('risk', { ...cfg.risk, max_trades_per_day: n })} />
              <NumberField label="Retorno/risco mínimo" unit="R" min={0} max={10} step={0.25} value={cfg.risk.min_reward_risk} onChange={(n) => set('risk', { ...cfg.risk, min_reward_risk: n })} />
            </div>
            <div className="rounded-[var(--radius-md)] border border-line bg-abyss/40 p-3.5">
              <div className="mb-2 flex items-center gap-2">
                <p className="text-sm text-fg">Dimensionamento de exemplo</p>
                <DataBadge kind="simulated" />
              </div>
              {cfg.exit.stop_type.startsWith('or') ? (
                <p className="text-xs text-muted">No ORB o stop depende da faixa de abertura do dia; o tamanho aparece no Time Machine, com o plano do dia.</p>
              ) : price.isLoading || sizing.isLoading ? (
                <Spinner label="Calculando com trader-budget e trader-risk" />
              ) : price.isError ? (
                <ErrorState error={price.error} />
              ) : sizing.data?.sizing ? (
                <div className="text-sm">
                  <p className="num text-fg">
                    {sizing.data.sizing.qty} ações · perda no stop {fmt.price(sizing.data.sizing.max_loss)} · limite que decidiu: {boundLabel(sizing.data.sizing.bound_by)}
                  </p>
                  <p className="num mt-1 text-xs text-muted">
                    Exemplo com o último fechamento: entrada {fmt.num(preview?.entry)}, stop {fmt.num(preview?.stop)}, alvo {fmt.num(preview?.target)}.
                    {sizing.data.risk && ` Verificação de risco: ${sizing.data.risk.pass ? 'passa' : 'bloqueada'}.`}
                  </p>
                  {sizing.data.risk?.results[0]?.reasons?.length ? <p className="mt-1 text-xs text-caution">{sizing.data.risk.results[0].reasons.join(' · ')}</p> : null}
                  <p className="mt-2 text-[11px] text-faint">{sizing.data.note}</p>
                </div>
              ) : sizing.data?.refusal ? (
                <p className="text-sm text-caution">{sizing.data.refusal}</p>
              ) : (
                <p className="text-xs text-muted">Sem preço para o exemplo.</p>
              )}
            </div>
          </div>
        </Step>
        <Step title="Revisar">
          <div className="space-y-4 pt-2">
            <Field label="Nome da estratégia" error={name && name.trim().length < 2 ? 'Use pelo menos 2 caracteres.' : null}>
              {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex.: ORB TSLA 15 min, alvo 1R" maxLength={120} />}
            </Field>
            <Field label="Hipótese ou descrição">{(p) => <Textarea {...p} value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="O que você espera observar e por quê." maxLength={4000} />}</Field>
            {id && <Field label="Nota da versão">{(p) => <Input {...p} value={note} onChange={(e) => setNote(e.target.value)} placeholder="O que mudou" maxLength={280} />}</Field>}
            <div className="rounded-[var(--radius-md)] border border-line bg-abyss/40 p-3.5 text-sm text-fg/90">{describe(cfg)}</div>
            <details className="text-xs text-muted">
              <summary className="cursor-pointer">Configuração completa (JSON)</summary>
              <pre className="num mt-2 overflow-x-auto rounded-[var(--radius-md)] bg-abyss p-3 text-[11px]">{JSON.stringify(cfg, null, 2)}</pre>
            </details>
          </div>
        </Step>
      </Stepper>
    </div>
  )
}
