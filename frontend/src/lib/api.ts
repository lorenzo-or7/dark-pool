/** Typed fetch wrapper for the DARK POOL API. The bearer token comes from the
 * auth layer (a Supabase session, or the local demo session). */

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

let tokenProvider: () => Promise<string | null> = async () => null
let onUnauthorized: () => void = () => {}

export function configureApi(opts: { token: () => Promise<string | null>; unauthorized: () => void }) {
  tokenProvider = opts.token
  onUnauthorized = opts.unauthorized
}

type Opts = { method?: string; body?: unknown; signal?: AbortSignal; form?: FormData; raw?: boolean }

export async function api<T = unknown>(path: string, opts: Opts = {}): Promise<T> {
  const token = await tokenProvider()
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      method: opts.method ?? (opts.body !== undefined || opts.form ? 'POST' : 'GET'),
      headers,
      body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
      signal: opts.signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(0, 'network', 'Não foi possível falar com o backend. Ele está em execução?')
  }
  if (res.status === 401) onUnauthorized()
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
