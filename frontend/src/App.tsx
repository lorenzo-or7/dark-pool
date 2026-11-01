import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/app/AppShell'
import { Spinner } from '@/components/ui/states'
import Landing from '@/pages/Landing'

const Dashboard = lazy(() => import('@/pages/app/Dashboard'))
const Scanner = lazy(() => import('@/pages/app/Scanner'))
const Strategies = lazy(() => import('@/pages/app/Strategies'))
const StrategyDetail = lazy(() => import('@/pages/app/StrategyDetail'))
const StrategyWizard = lazy(() => import('@/pages/app/StrategyWizard'))
const TimeMachine = lazy(() => import('@/pages/app/TimeMachine'))
const Analytics = lazy(() => import('@/pages/app/Analytics'))
const Journal = lazy(() => import('@/pages/app/Journal'))
const Congress = lazy(() => import('@/pages/app/Congress'))
const Settings = lazy(() => import('@/pages/app/Settings'))
const NotFound = lazy(() => import('@/pages/NotFound'))

const fallback = (
  <div className="flex min-h-[40vh] items-center justify-center">
    <Spinner />
  </div>
)

/** Public shared lab: every page opens directly, without login. The old account pages
 * (/login, /reset-password) now lead to the lab. */
export default function App() {
  return (
    <Suspense fallback={fallback}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Navigate to="/app" replace />} />
        <Route path="/reset-password" element={<Navigate to="/app" replace />} />
        <Route path="/app" element={<AppShell />}>
          <Route index element={<Suspense fallback={fallback}><Dashboard /></Suspense>} />
          <Route path="scanner" element={<Suspense fallback={fallback}><Scanner /></Suspense>} />
          <Route path="strategies" element={<Suspense fallback={fallback}><Strategies /></Suspense>} />
          <Route path="strategies/new" element={<Suspense fallback={fallback}><StrategyWizard /></Suspense>} />
          <Route path="strategies/:id" element={<Suspense fallback={fallback}><StrategyDetail /></Suspense>} />
          <Route path="strategies/:id/edit" element={<Suspense fallback={fallback}><StrategyWizard /></Suspense>} />
          <Route path="time-machine" element={<Suspense fallback={fallback}><TimeMachine /></Suspense>} />
          <Route path="analytics" element={<Suspense fallback={fallback}><Analytics /></Suspense>} />
          <Route path="journal" element={<Suspense fallback={fallback}><Journal /></Suspense>} />
          <Route path="congress" element={<Suspense fallback={fallback}><Congress /></Suspense>} />
          <Route path="settings" element={<Suspense fallback={fallback}><Settings /></Suspense>} />
          <Route path="*" element={<Suspense fallback={fallback}><NotFound /></Suspense>} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  )
}
