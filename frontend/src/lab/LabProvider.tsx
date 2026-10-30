import { useQuery } from '@tanstack/react-query'
import { createContext, useContext, type ReactNode } from 'react'
import { api, ApiError } from '@/lib/api'
import type { LabInfo } from '@/lib/types'

type Ctx = {
  lab: LabInfo | null
  loading: boolean
  /** The lab cannot be used: backend unreachable, or the public workspace not configured. */
  error: ApiError | null
  retry: () => void
}

const LabContext = createContext<Ctx | null>(null)

/** The shared lab's context (workspace name, mode). There is no login: everyone with the
 * link uses the same workspace, chosen by the backend. */
export function LabProvider({ children }: { children: ReactNode }) {
  const q = useQuery({
    queryKey: ['lab'],
    queryFn: ({ signal }) => api<LabInfo>('/me', { signal }),
    staleTime: 5 * 60_000,
    retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500 && e.status !== 429) && n < 2,
  })
  const error = q.error instanceof ApiError ? q.error : q.error ? new ApiError(0, 'unknown', String(q.error)) : null
  return (
    <LabContext.Provider value={{ lab: q.data ?? null, loading: q.isLoading, error, retry: () => void q.refetch() }}>
      {children}
    </LabContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useLab() {
  const ctx = useContext(LabContext)
  if (!ctx) throw new Error('useLab outside LabProvider')
  return ctx
}
