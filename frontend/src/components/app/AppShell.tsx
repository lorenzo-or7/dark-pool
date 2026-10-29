/**
 * Lab layout. Desktop: a collapsible sidebar that combines the two approved
 * references (Animated Sidebar by unlumen: spring hover highlight, animated
 * active bar, dash accents, drag-to-resize; Sidebar by Andrew Luo: a compact
 * Supabase-style icon rail). Both sources need a 21st.dev login, so this is an
 * in-house build. Mobile: its own bottom tab bar and a "Mais" sheet.
 */
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import {
  BookOpenText,
  ChevronsLeft,
  ChevronsRight,
  FlaskConical,
  LayoutDashboard,
  LineChart,
  LogOut,
  MoreHorizontal,
  Radar,
  Rewind,
  Settings,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type PointerEvent as RPointerEvent, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { EclipseMark } from '@/brand/EclipseMark'
import { Wordmark } from '@/brand/Wordmark'
import { useAuth } from '@/auth/AuthProvider'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

type Item = { to: string; label: string; icon: ReactNode; end?: boolean }

const groups: { title: string; items: Item[] }[] = [
  {
    title: 'Pesquisa',
    items: [
      { to: '/app', label: 'Dashboard', icon: <LayoutDashboard />, end: true },
      { to: '/app/scanner', label: 'Market Scanner', icon: <Radar /> },
      { to: '/app/strategies', label: 'Strategy Lab', icon: <FlaskConical /> },
      { to: '/app/time-machine', label: 'Time Machine', icon: <Rewind /> },
    ],
  },
  {
    title: 'Resultados',
    items: [
      { to: '/app/analytics', label: 'Analytics', icon: <LineChart /> },
      { to: '/app/journal', label: 'Trading Journal', icon: <BookOpenText /> },
    ],
  },
]

const KEY_COLLAPSED = 'dp.sidebar.collapsed'
const KEY_WIDTH = 'dp.sidebar.width'

function load<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key)
    return v == null ? fallback : (JSON.parse(v) as T)
  } catch {
    return fallback
  }
}

function save(key: string, v: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(v))
  } catch {
    /* preference only */
  }
}

function SideLink({ item, collapsed, hovered, setHovered }: { item: Item; collapsed: boolean; hovered: string | null; setHovered: (s: string | null) => void }) {
  const reduce = useReducedMotion()
  return (
    <NavLink
      to={item.to}
      end={item.end}
      onMouseEnter={() => setHovered(item.to)}
      onFocus={() => setHovered(item.to)}
      title={collapsed ? item.label : undefined}
      className={({ isActive }) =>
        cn(
          'group relative flex h-10 items-center gap-3 rounded-[9px] px-3 text-[13.5px] transition-colors [&_svg]:size-[18px] [&_svg]:shrink-0',
          isActive ? 'text-fg' : 'text-muted hover:text-fg',
          collapsed && 'justify-center px-0',
        )
      }
    >
      {({ isActive }) => (
        <>
          {hovered === item.to && (
            <motion.span
              layoutId="side-hover"
              className="absolute inset-0 -z-10 rounded-[9px] bg-raised"
              transition={reduce ? { duration: 0 } : { type: 'spring', stiffness: 500, damping: 38 }}
            />
          )}
          {isActive && (
            <motion.span
              layoutId="side-active"
              className="absolute top-2 bottom-2 left-0 w-[3px] rounded-full bg-ember"
              transition={reduce ? { duration: 0 } : { type: 'spring', stiffness: 420, damping: 34 }}
            />
          )}
          <span className={cn(isActive && 'text-ember')}>{item.icon}</span>
          {!collapsed && (
            <>
              <span className="truncate">{item.label}</span>
              <span className={cn('ml-auto h-px w-0 bg-ember/70 transition-all duration-300 group-hover:w-3', isActive && 'w-3')} aria-hidden />
            </>
          )}
        </>
      )}
    </NavLink>
  )
}

function Sidebar() {
  const { me, signOut } = useAuth()
  const [collapsed, setCollapsed] = useState(() => load(KEY_COLLAPSED, false))
  const [width, setWidth] = useState(() => load(KEY_WIDTH, 248))
  const [hovered, setHovered] = useState<string | null>(null)
  const dragging = useRef(false)

  useEffect(() => save(KEY_COLLAPSED, collapsed), [collapsed])
  useEffect(() => save(KEY_WIDTH, width), [width])

  const onDrag = useCallback((e: PointerEvent) => {
    if (dragging.current) setWidth(Math.min(320, Math.max(208, e.clientX)))
  }, [])
  const stopDrag = useCallback(() => {
    dragging.current = false
    document.body.style.cursor = ''
    window.removeEventListener('pointermove', onDrag)
    window.removeEventListener('pointerup', stopDrag)
  }, [onDrag])
  function startDrag(e: RPointerEvent) {
    e.preventDefault()
    dragging.current = true
    document.body.style.cursor = 'col-resize'
    window.addEventListener('pointermove', onDrag)
    window.addEventListener('pointerup', stopDrag)
  }
  useEffect(() => stopDrag, [stopDrag])

  return (
    <aside
      className="sticky top-0 hidden h-[100dvh] shrink-0 flex-col border-r border-line bg-abyss/60 transition-[width] duration-200 ease-[var(--ease-out-quart)] lg:flex"
      style={{ width: collapsed ? 68 : width }}
      aria-label="Navegação do laboratório"
    >
      <div className={cn('flex h-16 items-center gap-2.5 px-4', collapsed && 'justify-center px-0')}>
        <Link to="/app" className="flex items-center gap-2.5" aria-label="Dashboard">
          <EclipseMark className="size-7" title="" />
          {!collapsed && <Wordmark className="h-[11px] w-auto text-fg" />}
        </Link>
      </div>
      <nav className="flex-1 overflow-y-auto px-3 pt-2" onMouseLeave={() => setHovered(null)}>
        {groups.map((g) => (
          <div key={g.title} className="mb-5">
            {!collapsed ? <p className="eyebrow mb-2 px-3 text-[9.5px]">{g.title}</p> : <div className="mx-auto mb-2 h-px w-6 bg-line" />}
            <div className="flex flex-col gap-0.5">
              {g.items.map((it) => (
                <SideLink key={it.to} item={it} collapsed={collapsed} hovered={hovered} setHovered={setHovered} />
              ))}
            </div>
          </div>
        ))}
      </nav>
      <div className="border-t border-line p-3" onMouseLeave={() => setHovered(null)}>
        <SideLink item={{ to: '/app/settings', label: 'Configurações', icon: <Settings /> }} collapsed={collapsed} hovered={hovered} setHovered={setHovered} />
        <div className={cn('mt-2 flex items-center gap-2 rounded-[9px] px-2 py-2', collapsed && 'flex-col')}>
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-raised font-display text-xs text-fg" aria-hidden>
            {(me?.display_name ?? '?').slice(0, 1).toUpperCase()}
          </span>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] text-fg">{me?.display_name}</p>
              <p className="truncate text-[11px] text-faint">{me?.role === 'owner' ? 'Proprietário' : 'Membro'}</p>
            </div>
          )}
          <button onClick={() => void signOut()} className="rounded-[7px] p-1.5 text-muted hover:bg-raised hover:text-fg" aria-label="Sair" title="Sair">
            <LogOut className="size-4" />
          </button>
        </div>
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="mt-1 flex h-8 w-full items-center justify-center gap-2 rounded-[8px] text-xs text-faint hover:bg-raised hover:text-fg"
          aria-label={collapsed ? 'Expandir menu' : 'Recolher menu'}
          aria-expanded={!collapsed}
        >
          {collapsed ? <ChevronsRight className="size-4" /> : <ChevronsLeft className="size-4" />}
          {!collapsed && 'Recolher'}
        </button>
      </div>
      {!collapsed && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Redimensionar menu"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'ArrowLeft') setWidth((w) => Math.max(208, w - 16))
            if (e.key === 'ArrowRight') setWidth((w) => Math.min(320, w + 16))
          }}
          onPointerDown={startDrag}
          className="absolute top-0 right-[-3px] h-full w-1.5 cursor-col-resize hover:bg-ember/30 focus-visible:bg-ember/40"
        />
      )}
    </aside>
  )
}

const mobileMain: Item[] = [
  { to: '/app', label: 'Início', icon: <LayoutDashboard />, end: true },
  { to: '/app/scanner', label: 'Scanner', icon: <Radar /> },
  { to: '/app/strategies', label: 'Estratégias', icon: <FlaskConical /> },
  { to: '/app/time-machine', label: 'Time Machine', icon: <Rewind /> },
]
const mobileMore: Item[] = [
  { to: '/app/analytics', label: 'Analytics', icon: <LineChart /> },
  { to: '/app/journal', label: 'Trading Journal', icon: <BookOpenText /> },
  { to: '/app/settings', label: 'Configurações', icon: <Settings /> },
]

function MobileNav() {
  const [more, setMore] = useState(false)
  const loc = useLocation()
  const { signOut } = useAuth()
  const reduce = useReducedMotion()
  useEffect(() => setMore(false), [loc.pathname])
  const moreActive = mobileMore.some((m) => loc.pathname.startsWith(m.to))
  return (
    <>
      <nav aria-label="Navegação do laboratório" className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-ink/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md lg:hidden">
        <ul className="grid grid-cols-5">
          {mobileMain.map((it) => (
            <li key={it.to}>
              <NavLink
                to={it.to}
                end={it.end}
                className={({ isActive }) =>
                  cn('flex h-16 flex-col items-center justify-center gap-1 text-[10.5px] [&_svg]:size-5', isActive ? 'text-ember' : 'text-muted')
                }
              >
                {it.icon}
                {it.label}
              </NavLink>
            </li>
          ))}
          <li>
            <button
              onClick={() => setMore(true)}
              aria-expanded={more}
              aria-controls="mobile-more"
              className={cn('flex h-16 w-full flex-col items-center justify-center gap-1 text-[10.5px] [&_svg]:size-5', moreActive ? 'text-ember' : 'text-muted')}
            >
              <MoreHorizontal />
              Mais
            </button>
          </li>
        </ul>
      </nav>
      <AnimatePresence>
        {more && (
          <>
            <motion.div className="fixed inset-0 z-40 bg-abyss/70 lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setMore(false)} />
            <motion.div
              id="mobile-more"
              role="dialog"
              aria-label="Mais opções"
              className="fixed inset-x-0 bottom-0 z-50 rounded-t-[18px] border-t border-line-strong bg-surface p-4 pb-[calc(16px+env(safe-area-inset-bottom))] lg:hidden"
              initial={{ y: '100%' }}
              animate={{ y: 0 }}
              exit={{ y: '100%' }}
              transition={reduce ? { duration: 0 } : { type: 'spring', stiffness: 420, damping: 40 }}
            >
              <div className="mb-2 flex items-center justify-between">
                <p className="eyebrow">Mais</p>
                <button onClick={() => setMore(false)} className="rounded-[8px] p-2 text-muted hover:bg-raised" aria-label="Fechar">
                  <X className="size-4" />
                </button>
              </div>
              {mobileMore.map((it) => (
                <NavLink key={it.to} to={it.to} className={({ isActive }) => cn('flex h-12 items-center gap-3 rounded-[10px] px-3 text-[15px] [&_svg]:size-5', isActive ? 'bg-raised text-fg' : 'text-fg/85')}>
                  {it.icon}
                  {it.label}
                </NavLink>
              ))}
              <button onClick={() => void signOut()} className="mt-1 flex h-12 w-full items-center gap-3 rounded-[10px] px-3 text-[15px] text-down [&_svg]:size-5">
                <LogOut />
                Sair
              </button>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  )
}

export function AppShell() {
  const { me } = useAuth()
  const loc = useLocation()
  const main = useRef<HTMLElement>(null)
  useEffect(() => {
    main.current?.focus({ preventScroll: true })
    window.scrollTo(0, 0)
  }, [loc.pathname])
  return (
    <div className="flex min-h-[100dvh] bg-ink">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-line bg-ink/85 px-4 backdrop-blur-md sm:px-6 lg:h-16">
          <Link to="/app" className="flex items-center gap-2 lg:hidden" aria-label="Dashboard">
            <EclipseMark className="size-7" title="" />
            <Wordmark className="h-[10px] w-auto text-fg" />
          </Link>
          <p className="hidden truncate text-[13px] text-muted lg:block">{me?.workspace.name}</p>
          <div className="flex items-center gap-2">
            {me?.workspace.is_demo && (
              <Badge tone="caution" title="Workspace local de demonstração, separado do Supabase.">
                <span className="sm:hidden">Demo</span>
                <span className="hidden sm:inline">Modo demonstração</span>
              </Badge>
            )}
            <Badge tone="neutral" title="Nenhuma corretora conectada. Nenhuma ordem é enviada." className="hidden sm:inline-flex">
              Sem ordens reais
            </Badge>
          </div>
        </header>
        <main ref={main} tabIndex={-1} className="flex-1 px-4 pt-6 pb-28 outline-none sm:px-6 lg:px-8 lg:pb-12">
          <Outlet />
        </main>
      </div>
      <MobileNav />
    </div>
  )
}

export function PageHeader({ title, eyebrow, children, description }: { title: string; eyebrow?: string; description?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-4 sm:mb-8 md:flex-row md:items-end md:justify-between">
      <div className="min-w-0">
        {eyebrow && <p className="eyebrow mb-2">{eyebrow}</p>}
        <h1 className="text-2xl font-medium text-fg sm:text-[28px]">{title}</h1>
        {description && <div className="mt-1.5 max-w-2xl text-sm text-muted">{description}</div>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  )
}
