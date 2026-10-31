import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AlertsPanel } from './AlertsPanel'

const CHECK = {
  rings: [{ id: 'x', symbol: 'TSLA', message: 'TSLA is [preço oculto]: at or above your alert level $366.' }],
  state: { rung: { x: '2026-10-19T19:56:00Z' }, last_check: '2026-10-19T19:56:00Z' },
  market: { now_new_york: '2026-10-19 15:56', open: true, reason: 'regular session' },
  quotes: {},
  errors: [],
  source: { provider: 'alpaca', feed: 'delayed_sip', delayed: true, provenance: { provider_name: 'Alpaca Market Data (Basic)' } },
  prices_hidden: true,
  note: 'Verificação sob demanda.',
}

function mount() {
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    void init
    return new Response(JSON.stringify(CHECK), { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <AlertsPanel />
    </QueryClientProvider>,
  )
  return fetchMock
}

beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('AlertsPanel', () => {
  it('keeps rules in this browser and checks only when asked', async () => {
    const fetchMock = mount()
    expect(fetchMock).not.toHaveBeenCalled()                       // nothing runs on its own
    fireEvent.change(screen.getByLabelText('Ticker do alerta'), { target: { value: 'tsla' } })
    fireEvent.change(screen.getByLabelText('Preço'), { target: { value: '366' } })
    fireEvent.click(screen.getByRole('button', { name: /Adicionar/ }))
    const saved = JSON.parse(localStorage.getItem('dp.alerts.v1') ?? '{}')
    expect(saved.rules).toHaveLength(1)
    expect(saved.rules[0]).toMatchObject({ type: 'above', symbol: 'TSLA', price: 366 })
    fireEvent.click(screen.getByRole('button', { name: /Verificar agora/ }))
    await waitFor(() => expect(screen.getByText(/preço oculto/)).toBeTruthy())
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/alerts/check')
    expect(JSON.parse(String(init?.body)).rules[0].symbol).toBe('TSLA')
    expect(JSON.parse(localStorage.getItem('dp.alerts.v1') ?? '{}').state.rung.x).toBeTruthy()
  })
})
