import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from '@/auth/AuthProvider'
import { AppShell } from '@/components/app/AppShell'
import { Spinner } from '@/components/ui/states'
import Landing from '@/pages/Landing'

const Login = lazy(() => import('@/pages/Login'))
const ResetPassword = lazy(() => import('@/pages/ResetPassword'))
const Dashboard = lazy(() => import('@/pages/app/Dashboard'))
const Scanner = lazy(() => import('@/pages/app/Scanner'))
const Strategies = lazy(() => import('@/pages/app/Strategies'))
const StrategyDetail = lazy(() => import('@/pages/app/StrategyDetail'))
const StrategyWizard = lazy(() => import('@/pages/app/StrategyWizard'))
const TimeMachine = lazy(() => import('@/pages/app/TimeMachine'))
const Analytics = lazy(() => import('@/pages/app/Analytics'))
const Journal = lazy(() => import('@/pages/app/Journal'))
const Settings = lazy(() => import('@/pages/app/Settings'))
const NotFound = lazy(() => import('@/pages/NotFound'))

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status } = useAuth()
  const loc = useLocation()
  if (status === 'loading')
    return (
      <div className="flex min-h-[100dvh] items-center justify-center bg-ink">
        <Spinner label="Verificando sessão" />
      </div>
    )
  if (status !== 'signed-in') return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />
  return <>{children}</>
}

const fallback = (
  <div className="flex min-h-[40vh] items-center justify-center">
    <Spinner />
  </div>
)

export default function App() {
  return (
    <Suspense fallback={fallback}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route
          path="/app"
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route index element={<Suspense fallback={fallback}><Dashboard /></Suspense>} />
          <Route path="scanner" element={<Suspense fallback={fallback}><Scanner /></Suspense>} />
          <Route path="strategies" element={<Suspense fallback={fallback}><Strategies /></Suspense>} />
          <Route path="strategies/new" element={<Suspense fallback={fallback}><StrategyWizard /></Suspense>} />
          <Route path="strategies/:id" element={<Suspense fallback={fallback}><StrategyDetail /></Suspense>} />
          <Route path="strategies/:id/edit" element={<Suspense fallback={fallback}><StrategyWizard /></Suspense>} />
          <Route path="time-machine" element={<Suspense fallback={fallback}><TimeMachine /></Suspense>} />
          <Route path="analytics" element={<Suspense fallback={fallback}><Analytics /></Suspense>} />
          <Route path="journal" element={<Suspense fallback={fallback}><Journal /></Suspense>} />
          <Route path="settings" element={<Suspense fallback={fallback}><Settings /></Suspense>} />
          <Route path="*" element={<Suspense fallback={fallback}><NotFound /></Suspense>} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  )
}
