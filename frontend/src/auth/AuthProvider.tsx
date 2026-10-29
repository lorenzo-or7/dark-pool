import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, ApiError, configureApi } from '@/lib/api'
import { supabase } from '@/lib/supabase'
import type { Me } from '@/lib/types'

const DEMO_KEY = 'dp.demo-session'
const DEMO_TOKEN = 'demo-local'

type Mode = 'demo' | 'supabase' | 'unconfigured'
type Status = 'loading' | 'signed-out' | 'signed-in'

type Ctx = {
  mode: Mode | null
  status: Status
  me: Me | null
  error: string | null
  signIn: (email: string, password: string) => Promise<void>
  enterDemo: () => Promise<void>
  signOut: () => Promise<void>
  requestReset: (email: string) => Promise<void>
  updatePassword: (password: string) => Promise<void>
  refreshMe: () => Promise<void>
}

const AuthContext = createContext<Ctx | null>(null)

function readDemo() {
  try {
    return localStorage.getItem(DEMO_KEY) === '1'
  } catch {
    return false
  }
}

function writeDemo(on: boolean) {
  try {
    if (on) localStorage.setItem(DEMO_KEY, '1')
    else localStorage.removeItem(DEMO_KEY)
  } catch {
    /* storage unavailable: the session lasts for this tab only */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [mode, setMode] = useState<Mode | null>(null)
  const [status, setStatus] = useState<Status>('loading')
  const [me, setMe] = useState<Me | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [demoOn, setDemoOn] = useState(readDemo)

  const token = useCallback(async () => {
    if (mode === 'demo') return demoOn ? DEMO_TOKEN : null
    if (!supabase) return null
    const { data } = await supabase.auth.getSession()
    return data.session?.access_token ?? null
  }, [mode, demoOn])

  const loadMe = useCallback(async () => {
    try {
      const m = await api<Me>('/me')
      setMe(m)
      setStatus('signed-in')
      setError(null)
    } catch (e) {
      setMe(null)
      setStatus('signed-out')
      if (e instanceof ApiError && e.status === 403) setError(e.message)
      else if (e instanceof ApiError && e.code === 'network') setError(e.message)
    }
  }, [])

  useEffect(() => {
    configureApi({
      token,
      unauthorized: () => {
        setMe(null)
        setStatus('signed-out')
      },
    })
  }, [token])

  // Which auth mode is the backend running in?
  useEffect(() => {
    let alive = true
    fetch('/api/config')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((c: { auth_mode: 'demo' | 'supabase' }) => {
        if (!alive) return
        if (c.auth_mode === 'supabase' && !supabase) setMode('unconfigured')
        else setMode(c.auth_mode)
      })
      .catch(() => {
        if (!alive) return
        setError('Não foi possível falar com o backend. Ele está em execução?')
        setStatus('signed-out')
      })
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    if (mode === null) return
    if (mode === 'unconfigured') {
      setStatus('signed-out')
      return
    }
    if (mode === 'demo') {
      if (demoOn) void loadMe()
      else setStatus('signed-out')
      return
    }
    if (!supabase) return
    let active = true
    supabase.auth.getSession().then(({ data }) => {
      if (!active) return
      if (data.session) void loadMe()
      else setStatus('signed-out')
    })
    const { data: sub } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === 'SIGNED_OUT' || !session) {
        setMe(null)
        setStatus('signed-out')
        qc.clear()
      } else if (event === 'SIGNED_IN' || event === 'USER_UPDATED') {
        void loadMe()
      }
    })
    return () => {
      active = false
      sub.subscription.unsubscribe()
    }
  }, [mode, demoOn, loadMe, qc])

  const signIn = useCallback(async (email: string, password: string) => {
    if (!supabase) throw new Error('Supabase não configurado.')
    const { error: err } = await supabase.auth.signInWithPassword({ email, password })
    if (err) throw new Error(err.message === 'Invalid login credentials' ? 'E-mail ou senha incorretos.' : err.message)
  }, [])

  const enterDemo = useCallback(async () => {
    writeDemo(true)
    setDemoOn(true)
  }, [])

  const signOut = useCallback(async () => {
    if (mode === 'demo') {
      writeDemo(false)
      setDemoOn(false)
    } else if (supabase) {
      await supabase.auth.signOut()
    }
    setMe(null)
    setStatus('signed-out')
    qc.clear()
  }, [mode, qc])

  const requestReset = useCallback(async (email: string) => {
    if (!supabase) throw new Error('A recuperação de senha precisa do Supabase configurado.')
    const { error: err } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: `${window.location.origin}/reset-password` })
    if (err) throw new Error(err.message)
  }, [])

  const updatePassword = useCallback(async (password: string) => {
    if (!supabase) throw new Error('A alteração de senha precisa do Supabase configurado.')
    const { error: err } = await supabase.auth.updateUser({ password })
    if (err) throw new Error(err.message)
  }, [])

  const value = useMemo<Ctx>(
    () => ({ mode, status, me, error, signIn, enterDemo, signOut, requestReset, updatePassword, refreshMe: loadMe }),
    [mode, status, me, error, signIn, enterDemo, signOut, requestReset, updatePassword, loadMe],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth outside AuthProvider')
  return ctx
}
