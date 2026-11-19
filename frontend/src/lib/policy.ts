import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

/** GET /api/workspace -> display_policy: what the server lets this lab show (decided in the API). */
export type DisplayPolicy = {
  shared: boolean
  show_raw_prices: boolean
  show_trigger_prices: boolean
  pelosi_public: boolean
  /** What /api/congress answers: always in the local demo, in the public lab only with DP_PELOSI_PUBLIC=true. */
  pelosi_shown?: boolean
  allow_unofficial_sources: boolean
  mode: string
  note: string | null
}

export function useDisplayPolicy(): DisplayPolicy | null {
  const ws = useQuery({
    queryKey: ['workspace'],
    queryFn: ({ signal }) => api<{ display_policy?: DisplayPolicy }>('/workspace', { signal }),
    staleTime: 60_000,
  })
  return ws.data?.display_policy ?? null
}
