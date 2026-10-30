import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { StatusBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useJobTrackerMaybe } from '@/lab/JobTracker'
import { api } from '@/lib/api'
import type { Job } from '@/lib/types'

const TERMINAL = ['succeeded', 'failed', 'cancelled']

/** Follows a background job until it ends. Calls onDone once with the final state. */
export function useJob(jobId: string | null, onDone?: (j: Job) => void) {
  const done = useRef<string | null>(null)
  const q = useQuery({
    queryKey: ['job', jobId],
    queryFn: ({ signal }) => api<Job>(`/jobs/${jobId}`, { signal }),
    enabled: !!jobId,
    refetchInterval: (query) => (query.state.data && TERMINAL.includes(query.state.data.status) ? false : 800),
  })
  useEffect(() => {
    const j = q.data
    if (j && TERMINAL.includes(j.status) && done.current !== j.id) {
      done.current = j.id
      onDone?.(j)
    }
  }, [q.data, onDone])
  return q
}

/** Progress of one job inside the page or dialog that started it. The global tracker
 * (lab/JobTracker) follows the same job independently, so closing this view loses nothing. */
export function JobProgress({ jobId, onDone, label }: { jobId: string; onDone?: (j: Job) => void; label: string }) {
  const qc = useQueryClient()
  const tracker = useJobTrackerMaybe()
  const track = tracker?.track
  useEffect(() => track?.(), [jobId, track])
  const q = useJob(jobId, onDone)
  const cancel = useMutation({
    mutationFn: () => api(`/jobs/${jobId}/cancel`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['job', jobId] }),
  })
  const j = q.data
  if (!j) return null
  const active = !TERMINAL.includes(j.status)
  return (
    <div className="rounded-[var(--radius-md)] border border-line-strong bg-raised/50 p-3.5" aria-live="polite">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <StatusBadge status={j.status} />
          <p className="truncate text-sm text-fg">{label}</p>
        </div>
        {active && (
          <Button size="sm" variant="ghost" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
            Cancelar
          </Button>
        )}
      </div>
      <div className="mt-3 h-1 overflow-hidden rounded-full bg-line" role="progressbar" aria-valuenow={j.progress} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
        <div className="h-full rounded-full bg-ember transition-[width] duration-500" style={{ width: `${active ? Math.max(4, j.progress) : 100}%`, opacity: active ? 1 : 0.4 }} />
      </div>
      <p className="mt-2 text-xs text-muted">{j.error ?? j.stage}</p>
    </div>
  )
}
