import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { EclipseMark } from '@/brand/EclipseMark'
import { Tagline, Wordmark } from '@/brand/Wordmark'
import { useAuth } from '@/auth/AuthProvider'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/field'
import { Notice, Spinner } from '@/components/ui/states'

export function AuthFrame({ children, title, intro }: { children: React.ReactNode; title: string; intro?: React.ReactNode }) {
  return (
    <div className="relative grid min-h-[100svh] bg-ink lg:grid-cols-[1.05fr_1fr]">
      <div className="relative hidden overflow-hidden border-r border-line lg:block">
        <div className="hairline-grid absolute inset-0 opacity-30" aria-hidden />
        <EclipseMark className="absolute top-1/2 left-1/2 size-[640px] -translate-x-1/2 -translate-y-1/2 opacity-80" title="" weight={0.45} />
        <div className="absolute inset-x-12 bottom-12">
          <Wordmark className="h-7 w-auto text-fg" horizon />
          <Tagline className="mt-5 block text-[11px] text-muted" />
        </div>
        <Link to="/" className="eyebrow absolute top-10 left-12 hover:text-fg">
          ← Voltar ao site
        </Link>
      </div>
      <main className="flex items-center justify-center px-4 py-16 sm:px-8">
        <div className="w-full max-w-sm">
          <Link to="/" className="mb-10 flex items-center gap-3 lg:hidden" aria-label="DARK POOL, início">
            <EclipseMark className="size-9" title="" />
            <Wordmark className="h-3.5 w-auto text-fg" />
          </Link>
          <h1 className="text-2xl font-medium text-fg">{title}</h1>
          {intro && <div className="mt-2 text-sm text-muted">{intro}</div>}
          <div className="mt-8">{children}</div>
        </div>
      </main>
    </div>
  )
}

export default function Login() {
  const { mode, status, signIn, enterDemo, error } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const from = (loc.state as { from?: string } | null)?.from ?? '/app'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  if (status === 'signed-in') return <Navigate to={from} replace />

  async function submit(e: FormEvent) {
    e.preventDefault()
    setErr(null)
    if (!email.trim() || !password) {
      setErr('Informe e-mail e senha.')
      return
    }
    setBusy(true)
    try {
      await signIn(email.trim(), password)
      nav(from, { replace: true })
    } catch (e2) {
      setErr((e2 as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthFrame title="Entrar no laboratório" intro="Acesso restrito aos membros convidados do workspace.">
      {mode === null || status === 'loading' ? (
        <Spinner />
      ) : mode === 'demo' ? (
        <div className="space-y-5">
          <Notice tone="caution">
            O backend está em <strong>modo demonstração local</strong>: não há Supabase configurado, então não existe login real. A sessão de
            demonstração só funciona neste computador e usa um banco local separado.
          </Notice>
          {error && <Notice tone="caution">{error}</Notice>}
          <Button variant="primary" size="lg" className="w-full" onClick={() => void enterDemo().then(() => nav(from, { replace: true }))}>
            Entrar no modo demonstração
          </Button>
          <p className="text-xs leading-relaxed text-muted">
            Para o acesso real, configure as variáveis do Supabase no backend e no frontend (veja o README).
          </p>
        </div>
      ) : mode === 'unconfigured' ? (
        <Notice tone="caution">
          O backend espera Supabase, mas o frontend não tem <code className="num">VITE_SUPABASE_URL</code> e{' '}
          <code className="num">VITE_SUPABASE_ANON_KEY</code>. Configure o arquivo <code className="num">frontend/.env.local</code>.
        </Notice>
      ) : (
        <form onSubmit={submit} className="space-y-4" noValidate>
          <Field label="E-mail">
            {(p) => <Input {...p} type="email" autoComplete="email" inputMode="email" value={email} onChange={(e) => setEmail(e.target.value)} required />}
          </Field>
          <Field label="Senha">
            {(p) => <Input {...p} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />}
          </Field>
          {(err || error) && (
            <p role="alert" className="text-sm text-down">
              {err ?? error}
            </p>
          )}
          <Button type="submit" variant="primary" size="lg" className="w-full" disabled={busy}>
            {busy ? 'Entrando…' : 'Entrar'}
          </Button>
          <div className="flex justify-between pt-1 text-sm">
            <Link to="/reset-password" className="text-muted hover:text-ember">
              Esqueci minha senha
            </Link>
            <span className="text-faint">Sem cadastro público</span>
          </div>
        </form>
      )}
    </AuthFrame>
  )
}
