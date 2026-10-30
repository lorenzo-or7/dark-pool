import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CircleCheck, ChevronDown, ChevronUp, X, CircleX } from 'lucide-react'
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import type { JobStatus, TrackedJob } from '@/lib/types'
import { cn } from '@/lib/utils'

/**
 * Global job tracker for the shared lab.
 *
 * The list comes from the server (GET /api/jobs), not from the page that started a job, so
 * closing a dialog, changing page, reloading or opening the lab in another browser never
 * loses a run. When a job ends, every view that can show its result is refreshed (Strategy
 * Lab, Analytics, Dashboard, Time Machine, Scanner) and a notice links to the right result.
 */

const ACTIVE: JobStatus[] = ['queued', 'running']
const FAST_MS = 1500
const IDLE_MS = 5_000
// Query keys whose data a finished job can change.
const AFFECTED = [
  ['strategies'],
  ['strategy'],
  ['experiments'],
  ['experiment'],
  ['analytics'],
  ['compare'],
  ['dashboard'],
  ['snapshots'],
  ['sessions'],
  ['scans'],
  ['scan'],
  ['universe'],
]

export type JobNotice = { job: TrackedJob; at: number }

type Ctx = {
  jobs: TrackedJob[]
  active: TrackedJob[]
  notices: JobNotice[]
  dismiss: (id: string) => void
  /** Poll right away (a job was just started here). */
  track: () => void
}

const TrackerContext = createContext<Ctx | null>(null)

// eslint-disable-next-line react-refresh/only-export-components
export function jobLabel(j: Pick<TrackedJob, 'type' | 'title' | 'symbol'>) {
  if (j.title) return j.title
  switch (j.type) {
    case 'backtest.run':
      return `Backtest${j.symbol ? ` · ${j.symbol}` : ''}`
    case 'timemachine.run':
      return `Time Machine${j.symbol ? ` · ${j.symbol}` : ''}`
    case 'scan.daily':
      return 'Varredura diária'
    case 'scan.universe':
      return 'Atualização do universo de ações'
    default:
      return 'Tarefa'
  }
}

// eslint-disable-next-line react-refresh/only-export-components
export function jobLink(j: Pick<TrackedJob, 'type' | 'experiment_id'>): { to: string; label: string } | null {
  if (j.type === 'backtest.run' && j.experiment_id) return { to: `/app/analytics?exp=${j.experiment_id}`, label: 'Ver em Analytics' }
  if (j.type === 'timemachine.run' && j.experiment_id) return { to: `/app/time-machine?exp=${j.experiment_id}`, label: 'Ver simulação' }
  if (j.type === 'scan.daily' || j.type === 'scan.universe') return { to: '/app/scanner', label: 'Abrir Scanner' }
  return null
}

export function JobTrackerProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['jobs', 'tracker'],
    queryFn: ({ signal }) => api<TrackedJob[]>('/jobs?since_minutes=30', { signal }),
    refetchInterval: (query) => (query.state.data?.some((j) => ACTIVE.includes(j.status)) ? FAST_MS : IDLE_MS),
    refetchOnWindowFocus: true,
    staleTime: 0,
    retry: false,
  })
  const seen = useRef<Map<string, JobStatus> | null>(null)
  const [notices, setNotices] = useState<JobNotice[]>([])

  useEffect(() => {
    const list = q.data
    if (!list) return
    const first = seen.current === null
    const prev = seen.current ?? new Map<string, JobStatus>()
    const ended: TrackedJob[] = []
    for (const j of list) {
      const before = prev.get(j.id)
      const done = !ACTIVE.includes(j.status)
      // Ended while we were watching, or started and ended between two polls.
      if (done && !first && (before === undefined || ACTIVE.includes(before))) ended.push(j)
    }
    seen.current = new Map(list.map((j) => [j.id, j.status]))
    if (!ended.length) return
    for (const key of AFFECTED) void qc.invalidateQueries({ queryKey: key })
    for (const j of ended) void qc.invalidateQueries({ queryKey: ['job', j.id] })
    const now = Date.now()
    setNotices((n) => [...ended.map((job) => ({ job, at: now })), ...n.filter((x) => !ended.some((e) => e.id === x.job.id))].slice(0, 4))
  }, [q.data, qc])

  const dismiss = useCallback((id: string) => setNotices((n) => n.filter((x) => x.job.id !== id)), [])
  const track = useCallback(() => void qc.invalidateQueries({ queryKey: ['jobs', 'tracker'] }), [qc])
  const value = useMemo<Ctx>(() => {
    const jobs = q.data ?? []
    return { jobs, active: jobs.filter((j) => ACTIVE.includes(j.status)), notices, dismiss, track }
  }, [q.data, notices, dismiss, track])
  return <TrackerContext.Provider value={value}>{children}</TrackerContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useJobTracker() {
  const ctx = useContext(TrackerContext)
  if (!ctx) throw new Error('useJobTracker outside JobTrackerProvider')
  return ctx
}

/** Optional variant for components that may render outside the lab shell. */
// eslint-disable-next-line react-refresh/only-export-components
export function useJobTrackerMaybe() {
  return useContext(TrackerContext)
}

function ActiveRow({ j }: { j: TrackedJob }) {
  const { track } = useJobTracker()
  const cancel = useMutation({ mutationFn: () => api(`/jobs/${j.id}/cancel`, { method: 'POST' }), onSettled: track })
  const link = jobLink(j)
  return (
    <li className="px-3.5 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-[13px] text-fg">{jobLabel(j)}</p>
          <p className="truncate text-[11px] text-muted">
            {j.status === 'queued' ? 'Na fila' : (j.stage ?? 'Em execução')}
            {j.cancel_requested && ' · cancelando…'}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {link && (
            <Link to={link.to} className="rounded-[7px] px-2 py-1 text-[11px] text-muted hover:bg-raised hover:text-fg">
              Abrir
            </Link>
          )}
          <Button size="sm" variant="ghost" onClick={() => cancel.mutate()} disabled={cancel.isPending || j.cancel_requested}>
            Cancelar
          </Button>
        </div>
      </div>
      <div className="mt-2 h-1 overflow-hidden rounded-full bg-line" role="progressbar" aria-valuenow={j.progress} aria-valuemin={0} aria-valuemax={100} aria-label={jobLabel(j)}>
        <div className="h-full rounded-full bg-ember transition-[width] duration-500" style={{ width: `${Math.max(4, j.progress)}%` }} />
      </div>
    </li>
  )
}

function NoticeCard({ n }: { n: JobNotice }) {
  const { dismiss } = useJobTracker()
  const j = n.job
  const ok = j.status === 'succeeded'
  const link = jobLink(j)
  useEffect(() => {
    if (!ok) return
    const t = setTimeout(() => dismiss(j.id), 20_000)
    return () => clearTimeout(t)
  }, [ok, j.id, dismiss])
  return (
    <div
      role={ok ? 'status' : 'alert'}
      className={cn('panel flex items-start gap-3 border p-3.5 shadow-lg', ok ? 'border-up/30' : 'border-down/40')}
    >
      {ok ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-up" /> : <CircleX className="mt-0.5 size-4 shrink-0 text-down" />}
      <div className="min-w-0 flex-1">
        <p className="text-[13px] text-fg">
          {ok ? 'Concluído' : j.status === 'cancelled' ? 'Cancelado' : 'Falhou'}: <span className="text-fg/85">{jobLabel(j)}</span>
        </p>
        {!ok && j.error && <p className="mt-1 line-clamp-3 text-xs text-muted">{j.error}</p>}
        {link && (
          <Link to={link.to} onClick={() => dismiss(j.id)} className="mt-1.5 inline-block text-xs text-ember hover:underline">
            {link.label}
          </Link>
        )}
      </div>
      <button onClick={() => dismiss(j.id)} className="rounded-[7px] p-1 text-muted hover:bg-raised hover:text-fg" aria-label="Fechar aviso">
        <X className="size-3.5" />
      </button>
    </div>
  )
}

/** Floating dock: running jobs of the whole lab, and notices when they end. */
export function JobDock() {
  const { active, notices } = useJobTracker()
  const [open, setOpen] = useState(true)
  if (!active.length && !notices.length) return null
  return (
    <div
      className="pointer-events-none fixed right-3 bottom-[calc(76px+env(safe-area-inset-bottom))] left-3 z-40 flex flex-col items-stretch gap-2 sm:left-auto sm:w-[360px] lg:right-5 lg:bottom-5"
      aria-live="polite"
    >
      {notices.map((n) => (
        <div key={n.job.id} className="pointer-events-auto">
          <NoticeCard n={n} />
        </div>
      ))}
      {active.length > 0 && (
        <section className="panel pointer-events-auto overflow-hidden border border-line-strong shadow-lg" aria-label="Tarefas em andamento">
          <button
            onClick={() => setOpen((o) => !o)}
            className="flex w-full items-center justify-between gap-2 px-3.5 py-2.5 text-left"
            aria-expanded={open}
          >
            <span className="flex items-center gap-2 text-[13px] text-fg">
              <span className="size-2 animate-pulse rounded-full bg-ember" aria-hidden />
              {active.length === 1 ? '1 tarefa em andamento' : `${active.length} tarefas em andamento`}
            </span>
            {open ? <ChevronDown className="size-4 text-muted" /> : <ChevronUp className="size-4 text-muted" />}
          </button>
          {open && (
            <ul className="max-h-[40vh] divide-y divide-line overflow-y-auto border-t border-line">
              {active.map((j) => (
                <ActiveRow key={j.id} j={j} />
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  )
}
