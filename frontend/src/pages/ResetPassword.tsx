import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '@/auth/AuthProvider'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/field'
import { Notice } from '@/components/ui/states'
import { supabase } from '@/lib/supabase'
import { AuthFrame } from './Login'

export default function ResetPassword() {
  const { mode, requestReset, updatePassword } = useAuth()
  const nav = useNavigate()
  const [recovery, setRecovery] = useState(false)
  const [email, setEmail] = useState('')
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  // The e-mail link opens this page with a recovery session.
  useEffect(() => {
    if (!supabase) return
    if (window.location.hash.includes('type=recovery') || window.location.hash.includes('type=invite')) setRecovery(true)
    const { data } = supabase.auth.onAuthStateChange((event) => {
      if (event === 'PASSWORD_RECOVERY') setRecovery(true)
    })
    return () => data.subscription.unsubscribe()
  }, [])

  async function sendLink(e: FormEvent) {
    e.preventDefault()
    setErr(null)
    setBusy(true)
    try {
      await requestReset(email.trim())
      setMsg('Se este e-mail tiver acesso, você vai receber um link para definir uma nova senha.')
    } catch (e2) {
      setErr((e2 as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault()
    setErr(null)
    if (pw.length < 10) return setErr('Use pelo menos 10 caracteres.')
    if (pw !== pw2) return setErr('As senhas não coincidem.')
    setBusy(true)
    try {
      await updatePassword(pw)
      nav('/app', { replace: true })
    } catch (e2) {
      setErr((e2 as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (mode === 'demo' || mode === 'unconfigured')
    return (
      <AuthFrame title="Recuperar senha">
        <Notice tone="caution">A recuperação de senha usa o Supabase Auth, que não está configurado neste ambiente (modo demonstração).</Notice>
        <Link to="/login" className="mt-6 inline-block text-sm text-muted hover:text-ember">
          ← Voltar ao login
        </Link>
      </AuthFrame>
    )

  return (
    <AuthFrame title={recovery ? 'Definir nova senha' : 'Recuperar senha'} intro={recovery ? 'Escolha uma senha com pelo menos 10 caracteres.' : 'Enviaremos um link para o e-mail cadastrado.'}>
      {recovery ? (
        <form onSubmit={save} className="space-y-4" noValidate>
          <Field label="Nova senha">{(p) => <Input {...p} type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} />}</Field>
          <Field label="Repita a senha">{(p) => <Input {...p} type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} />}</Field>
          {err && <p role="alert" className="text-sm text-down">{err}</p>}
          <Button type="submit" variant="primary" size="lg" className="w-full" disabled={busy}>
            {busy ? 'Salvando…' : 'Salvar senha'}
          </Button>
        </form>
      ) : (
        <form onSubmit={sendLink} className="space-y-4" noValidate>
          <Field label="E-mail">{(p) => <Input {...p} type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
          {err && <p role="alert" className="text-sm text-down">{err}</p>}
          {msg && <Notice>{msg}</Notice>}
          <Button type="submit" variant="primary" size="lg" className="w-full" disabled={busy || !email.trim()}>
            {busy ? 'Enviando…' : 'Enviar link'}
          </Button>
          <Link to="/login" className="inline-block text-sm text-muted hover:text-ember">
            ← Voltar ao login
          </Link>
        </form>
      )}
    </AuthFrame>
  )
}
