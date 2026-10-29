import { AlertTriangle, Loader2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { ApiError } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Button } from './button'

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-[var(--radius-md)] bg-raised/80', className)} aria-hidden />
}

export function Spinner({ label = 'Carregando', className }: { label?: string; className?: string }) {
  return (
    <span role="status" className={cn('inline-flex items-center gap-2 text-sm text-muted', className)}>
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {label}
    </span>
  )
}

export function EmptyState({ title, children, action, className }: { title: string; children?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-col items-start gap-3 rounded-[var(--radius-lg)] border border-dashed border-line-strong px-6 py-8', className)}>
      <p className="font-display text-base text-fg">{title}</p>
      {children && <div className="max-w-prose text-sm text-muted">{children}</div>}
      {action}
    </div>
  )
}

export function ErrorState({ error, retry, className }: { error: unknown; retry?: () => void; className?: string }) {
  const msg = error instanceof ApiError || error instanceof Error ? error.message : 'Algo deu errado.'
  return (
    <div role="alert" className={cn('flex items-start gap-3 rounded-[var(--radius-lg)] border border-down/30 bg-down/5 px-4 py-3', className)}>
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-down" aria-hidden />
      <div className="flex-1 text-sm">
        <p className="text-fg">{msg}</p>
        {error instanceof ApiError && error.errors && error.errors.length > 1 && (
          <ul className="mt-1 list-disc pl-4 text-muted">
            {error.errors.map((e) => (
              <li key={e.field + e.message}>
                <span className="num text-xs">{e.field}</span>: {e.message}
              </li>
            ))}
          </ul>
        )}
      </div>
      {retry && (
        <Button size="sm" variant="ghost" onClick={retry}>
          Tentar de novo
        </Button>
      )}
    </div>
  )
}

export function Notice({ children, tone = 'neutral', className }: { children: ReactNode; tone?: 'neutral' | 'caution' | 'sim'; className?: string }) {
  return (
    <div
      className={cn(
        'rounded-[var(--radius-md)] border px-3.5 py-2.5 text-[13px] leading-relaxed',
        tone === 'caution' && 'border-caution/30 bg-caution/5 text-fg/90',
        tone === 'sim' && 'border-sim/30 bg-sim/5 text-fg/90',
        tone === 'neutral' && 'border-line-strong bg-raised/40 text-muted',
        className,
      )}
    >
      {children}
    </div>
  )
}
