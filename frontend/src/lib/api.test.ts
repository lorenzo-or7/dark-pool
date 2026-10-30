import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, apiUrl } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('api', () => {
  it('uses the same origin when VITE_API_URL is not set', () => {
    expect(apiUrl('/health')).toBe('/api/health')
  })

  it('never sends credentials or an Authorization header', async () => {
    const f = vi.fn(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', f)
    await api('/me')
    await api('/journal', { body: { title: 'x' } })
    for (const call of f.mock.calls as unknown as [string, RequestInit][]) {
      const h = call[1].headers as Record<string, string>
      expect(h.Authorization).toBeUndefined()
      expect(call[1].credentials).toBeUndefined()
    }
  })

  it('turns 429 and 503 into readable errors', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: { code: 'queue_full', message: 'A fila está cheia.' } }), { status: 429 })))
    await expect(api('/backtests', { body: {} })).rejects.toMatchObject({ status: 429, code: 'queue_full', message: 'A fila está cheia.' })
  })
})
