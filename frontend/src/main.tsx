import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'

// VITE_PUBLIC_ONLY is replaced at build time, so the public build drops the lab code entirely.
const PUBLIC_ONLY = import.meta.env.VITE_PUBLIC_ONLY === 'true'
const Root = PUBLIC_ONLY ? lazy(() => import('./PublicSite')) : lazy(() => import('./FullApp'))
const basename = import.meta.env.BASE_URL.replace(/\/$/, '') || '/'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter basename={basename}>
      <Suspense fallback={<div className="min-h-[100svh] bg-ink" />}>
        <Root />
      </Suspense>
    </BrowserRouter>
  </StrictMode>,
)
