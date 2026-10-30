import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { TrackedJob } from '@/lib/types'
import { JobDock, JobTrackerProvider, jobLabel, jobLink } from './JobTracker'

const base: TrackedJob = {
  id: 'j1', type: 'backtest.run', status: 'running', progress: 40, stage: 'Rodando', error: null,
  created_at: '2026-10-29T10:00:00Z', started_at: '2026-10-29T10:00:01Z', finished_at: null, cancel_requested: false,
  title: 'Backtest · ORB v2 · TSLA', experiment_id: 'e1', scan_id: null, strategy_id: 's1', symbol: 'TSLA', result: null,
}

function mount(responses: TrackedJob[][]) {
  let i = 0
  const fetchMock = vi.fn(async (url: string) => {
    expect(url).toContain('/api/jobs')
    const body = responses[Math.min(i++, responses.length - 1)]
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const spy = vi.spyOn(qc, 'invalidateQueries')
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <JobTrackerProvider>
          <JobDock />
        </JobTrackerProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { fetchMock, spy }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('JobTracker', () => {
  it('labels and links each kind of job to its result', () => {
    expect(jobLink(base)).toEqual({ to: '/app/analytics?exp=e1', label: 'Ver em Analytics' })
    expect(jobLink({ type: 'timemachine.run', experiment_id: 'e2' })?.to).toBe('/app/time-machine?exp=e2')
    expect(jobLink({ type: 'scan.daily', experiment_id: null })?.to).toBe('/app/scanner')
    expect(jobLabel({ type: 'scan.universe', title: null, symbol: null })).toBe('Atualização do universo de ações')
  })

  it('shows a job started elsewhere, then refreshes the lab and links the result when it ends', async () => {
    const { spy } = mount([[base], [{ ...base, status: 'succeeded', progress: 100, stage: 'Concluído', finished_at: '2026-10-29T10:01:00Z' }]])
    expect(await screen.findByText('1 tarefa em andamento')).toBeInTheDocument()
    const link = await screen.findByRole('link', { name: 'Ver em Analytics' }, { timeout: 5000 })
    expect(link).toHaveAttribute('href', '/app/analytics?exp=e1')
    expect(screen.getByRole('status')).toHaveTextContent('Concluído')
    const keys = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey))
    for (const k of ['["strategies"]', '["analytics"]', '["dashboard"]', '["experiment"]']) expect(keys).toContain(k)
  })

  it('shows the error of a failed job without a reload', async () => {
    mount([[base], [{ ...base, status: 'failed', error: 'O provedor não respondeu a tempo.', finished_at: '2026-10-29T10:01:00Z' }]])
    const alert = await screen.findByRole('alert', {}, { timeout: 5000 })
    expect(alert).toHaveTextContent('Falhou')
    expect(alert).toHaveTextContent('O provedor não respondeu a tempo.')
  })

  it('does not announce jobs that had already ended before the page opened', async () => {
    const { fetchMock } = mount([[{ ...base, status: 'succeeded', finished_at: '2026-10-29T09:00:00Z' }]])
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    await new Promise((r) => setTimeout(r, 200))
    expect(screen.queryByRole('status')).toBeNull()
  })
})
