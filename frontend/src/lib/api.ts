/** Typed fetch wrapper for the DARK POOL API.
 *
 * The lab is public and shared: the browser holds no session, token or key. The backend
 * decides the workspace on the server.
 *
 * Address: same origin by default (`/api`, proxied by Vite in development). A production
 * build for a separate API host sets VITE_API_URL, e.g. https://darkpool-api.onrender.com */

const API_BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? '').trim().replace(/\/+$/, '')

/** Full URL of an API path, e.g. apiUrl('/health') -> https://host/api/health */
export function apiUrl(path: string) {
  return `${API_BASE}/api${path}`
}

export class ApiError extends Error {
  status: number
  code: string
  errors?: { field: string; message: string }[]
  constructor(status: number, code: string, message: string, errors?: { field: string; message: string }[]) {
    super(message)
    this.status = status
    this.code = code
    this.errors = errors
  }
}

type Opts = { method?: string; body?: unknown; signal?: AbortSignal; form?: FormData; raw?: boolean }

export async function api<T = unknown>(path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  let res: Response
  try {
    res = await fetch(apiUrl(path), {
      method: opts.method ?? (opts.body !== undefined || opts.form ? 'POST' : 'GET'),
      headers,
      body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
      signal: opts.signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(0, 'network', 'Não foi possível falar com o servidor do laboratório. Se ele estava em repouso, aguarde cerca de um minuto e tente de novo.')
  }
  if (!res.ok) {
    let detail: { code?: string; message?: string; errors?: { field: string; message: string }[] } = {}
    try {
      const j = await res.json()
      detail = typeof j.detail === 'string' ? { message: j.detail } : (j.detail ?? {})
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail.code ?? `http_${res.status}`, detail.message ?? `Erro HTTP ${res.status}`, detail.errors)
  }
  if (opts.raw) return res as unknown as T
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export async function download(path: string, filename: string) {
  const res = await api<Response>(path, { raw: true })
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}
