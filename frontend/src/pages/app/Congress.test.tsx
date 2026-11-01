import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Congress from './Congress'

/* Answers written by hand in the shape of the API (values from the skill's saved PTR 20035143). */
const SENATE = { covered: false, url: 'https://efdsearch.senate.gov/search/', note: 'Senado não coberto: termo aceito por cada pessoa no eFD.' }
const POLICY = (shown: boolean, mode = 'public') => ({
  display_policy: { shared: true, show_raw_prices: false, show_trigger_prices: false, pelosi_public: shown && mode === 'public', pelosi_shown: shown, allow_unofficial_sources: false, mode, note: null },
})
const INDEX = {
  year: 2026,
  total: 1,
  collected_at: '2026-11-01T22:00:00+00:00',
  from_cache: false,
  source: 'House Clerk (índice <ANO>FD.zip)',
  source_url: 'https://disclosures-clerk.house.gov/public_disc/financial-pdfs/2026FD.zip',
  senate: SENATE,
  disclaimer: 'Divulgação pública obrigatória (STOCK Act).',
  filings: [
    {
      doc_id: '20035143', type: 'P', type_name: 'Periodic Transaction Report', last: 'Pelosi', first: 'Nancy', name: 'Hon. Nancy Pelosi',
      district: 'CA11', year: 2026, filed: '2026-08-21', url: 'https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20035143.pdf', collected_at: '2026-11-01T22:00:00+00:00',
    },
  ],
}
const REPORT = {
  doc_id: '20035143', year: 2026, pdf_url: INDEX.filings[0].url, collected_at: '2026-11-01T22:00:00+00:00', from_cache: false, readable: true,
  name: 'Hon. Nancy Pelosi', status: 'Member', district: 'CA11', filed: '2026-08-21', note: null, source: 'House Clerk (PTR em PDF)', senate: SENATE, disclaimer: 'x',
  rows: [
    {
      owner: 'SP', owner_name: 'spouse', asset: 'Bloom Energy Corporation Class A Common Stock', ticker: 'BE', asset_type: 'OP', type: 'P', type_name: 'purchase',
      date: '2026-07-24', notified: '2026-07-24', amount: '$1,000,001 - $5,000,000', amount_low: 1000001, amount_high: 5000000, status: null, account: null,
      description: 'Purchased 100 call options', option: { contracts: 100, kind: 'call', strike: 100, expires: '2027-06-17', exercised: false }, days_to_disclose: 28, late: false,
    },
    {
      owner: 'JT', owner_name: 'joint', asset: 'Applied Materials, Inc.', ticker: 'AMAT', asset_type: 'ST', type: 'S', type_name: 'sale',
      date: '2026-06-01', notified: '2026-06-01', amount: '$15,001 - $50,000', amount_low: 15001, amount_high: 50000, status: null, account: null,
      description: null, days_to_disclose: 81, late: true,
    },
  ],
}

function mount(policy: object) {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      calls.push(url)
      const body = url.endsWith('/api/workspace') ? policy : url.includes('/api/congress/ptrs/20035143') ? REPORT : url.includes('/api/congress/ptrs?') ? INDEX : null
      return new Response(JSON.stringify(body ?? { detail: { code: 'x', message: 'não esperado' } }), { status: body ? 200 : 404, headers: { 'Content-Type': 'application/json' } })
    }),
  )
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <Congress />
    </QueryClientProvider>,
  )
  return calls
}

afterEach(() => vi.unstubAllGlobals())

describe('Congress page', () => {
  it('follows the server policy: off in the public lab, nothing requested', async () => {
    const calls = mount(POLICY(false))
    expect(await screen.findByText(/5 U\.S\.C\. §13107\(c\)/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Abrir o eFD do Senado' })).toHaveAttribute('href', 'https://efdsearch.senate.gov/search/')
    expect(calls.some((u) => u.includes('/congress/'))).toBe(false)
  })

  it('lists PTRs and opens the trades of one, with dates, ranges and the late flag', async () => {
    const calls = mount(POLICY(true, 'demo'))
    expect(await screen.findByText('Hon. Nancy Pelosi')).toBeInTheDocument()
    expect(calls.find((u) => u.includes('/congress/ptrs?'))).toContain('member=pelosi')
    expect(screen.getByText('21/08/2026')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /abrir/ })).toHaveAttribute('href', INDEX.filings[0].url)
    expect(screen.getByText(/Senado não coberto/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Ver as operações do PTR 20035143' }))
    expect(await screen.findByText('$1,000,001 - $5,000,000')).toBeInTheDocument()
    await waitFor(() => expect(calls.some((u) => u.includes('/congress/ptrs/20035143?year=2026&filed=2026-08-21'))).toBe(true))
    expect(screen.getByText('24/07/2026')).toBeInTheDocument()
    expect(screen.getByText('Compra')).toBeInTheDocument()
    expect(screen.getByText('Venda')).toBeInTheDocument()
    expect(screen.getByText('Cônjuge')).toBeInTheDocument()
    expect(screen.getByText(/100 calls, strike US\$ 100,00/)).toBeInTheDocument()
    expect(screen.getByText('28')).toBeInTheDocument()
    expect(screen.getAllByText('atrasado')).toHaveLength(1)
    expect(screen.getByRole('link', { name: /PDF na House Clerk/ })).toHaveAttribute('href', INDEX.filings[0].url)
  })
})
