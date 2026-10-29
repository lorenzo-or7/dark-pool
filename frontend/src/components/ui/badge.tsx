import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

type Tone = 'neutral' | 'ember' | 'up' | 'down' | 'caution' | 'sim'

const tones: Record<Tone, string> = {
  neutral: 'border-line-strong text-muted',
  ember: 'border-ember/40 text-ember bg-ember/8',
  up: 'border-up/35 text-up bg-up/8',
  down: 'border-down/35 text-down bg-down/8',
  caution: 'border-caution/40 text-caution bg-caution/8',
  sim: 'border-sim/35 text-sim bg-sim/8',
}

export function Badge({ tone = 'neutral', children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex h-5 shrink-0 items-center gap-1 rounded-full border px-2 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em]',
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

/** Where a number comes from. Every result in DARK POOL carries one. */
export type DataKind = 'historical' | 'simulated' | 'demo' | 'delayed' | 'backtest' | 'fixture'

const kinds: Record<DataKind, { tone: Tone; label: string; title: string }> = {
  historical: { tone: 'neutral', label: 'Histórico', title: 'Calculado sobre dados históricos registrados.' },
  backtest: { tone: 'neutral', label: 'Backtest', title: 'Regra reexecutada sobre dados históricos, sem custos.' },
  simulated: { tone: 'sim', label: 'Simulado', title: 'Resultado de simulação Monte Carlo. Não é previsão.' },
  demo: { tone: 'caution', label: 'Demonstração', title: 'Dado demonstrativo, não vem de uma execução real.' },
  delayed: { tone: 'neutral', label: 'Atrasado', title: 'Cotação gratuita com atraso, não é tempo real.' },
  fixture: { tone: 'caution', label: 'Dados de referência', title: 'Arquivo fixo do pacote Day Trader Skill, usado para reprodutibilidade.' },
}

export function DataBadge({ kind, className }: { kind: DataKind; className?: string }) {
  const k = kinds[kind]
  return (
    <Badge tone={k.tone} className={className} title={k.title}>
      {k.label}
    </Badge>
  )
}

const statusMap: Record<string, { tone: Tone; label: string }> = {
  queued: { tone: 'neutral', label: 'Na fila' },
  running: { tone: 'ember', label: 'Executando' },
  succeeded: { tone: 'up', label: 'Concluído' },
  failed: { tone: 'down', label: 'Falhou' },
  cancelled: { tone: 'caution', label: 'Cancelado' },
}

export function StatusBadge({ status }: { status: string }) {
  const s = statusMap[status] ?? { tone: 'neutral' as Tone, label: status }
  return (
    <Badge tone={s.tone}>
      {status === 'running' && <span className="size-1.5 animate-pulse rounded-full bg-current" aria-hidden />}
      {s.label}
    </Badge>
  )
}
