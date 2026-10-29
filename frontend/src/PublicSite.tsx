import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import Landing from '@/pages/Landing'

const NotFound = lazy(() => import('@/pages/NotFound'))

/** The static public site (GitHub Pages): the landing page only. No auth, no lab, no API. */
export default function PublicSite() {
  return (
    <Routes>
      <Route path="/" element={<Landing publicOnly />} />
      <Route
        path="*"
        element={
          <Suspense fallback={null}>
            <NotFound />
          </Suspense>
        }
      />
    </Routes>
  )
}
