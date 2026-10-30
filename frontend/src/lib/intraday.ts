import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { IntradayProvider } from '@/lib/types'

/** Who supplies new 5-minute bars, as configured on the server (DP_INTRADAY_PROVIDER). */
export function useIntradayProvider(): IntradayProvider | null {
  const ws = useQuery({
    queryKey: ['workspace'],
    queryFn: ({ signal }) => api<{ intraday_provider?: IntradayProvider }>('/workspace', { signal }),
    staleTime: 60_000,
  })
  return ws.data?.intraday_provider ?? null
}

export function intradayLabel(p: IntradayProvider | null, sessions: number): string {
  if (!p) return 'Baixar agora'
  return p.provider === 'alpaca'
    ? `Baixar agora da Alpaca (feed IEX, ${sessions} sessões, 5 min)`
    : 'Baixar agora do Yahoo (60 dias, 5 min)'
}
