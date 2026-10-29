/**
 * Landing navigation. Combines the two approved references (both need a
 * 21st.dev login, so this is an in-house build of their documented behavior):
 * - Morphing Island Navbar: floating island, subtle glass, a layoutId pill that
 *   morphs between items;
 * - Morphing Scroll Navbar: starts as a full-width header, becomes a floating
 *   capsule after scrolling, compacts while scrolling down, restores on the
 *   way up, and tracks reading progress.
 */
import { AnimatePresence, motion, useMotionValueEvent, useReducedMotion, useScroll, useSpring } from 'motion/react'
import { Menu, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { EclipseMark } from '@/brand/EclipseMark'
import { Wordmark } from '@/brand/Wordmark'
import { cn } from '@/lib/utils'

const items = [
  { href: '#plataforma', label: 'Plataforma' },
  { href: '#funcionalidades', label: 'Funcionalidades' },
  { href: '#metodologia', label: 'Metodologia' },
]

export function IslandNavbar({ enterTo, enterLabel }: { enterTo: string; enterLabel: string }) {
  const reduce = useReducedMotion()
  const { scrollY, scrollYProgress } = useScroll()
  const progress = useSpring(scrollYProgress, { stiffness: 200, damping: 40, restDelta: 0.001 })
  const [floating, setFloating] = useState(false)
  const [compact, setCompact] = useState(false)
  const [hover, setHover] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState<string | null>(null)

  useMotionValueEvent(scrollY, 'change', (y) => {
    const prev = scrollY.getPrevious() ?? 0
    setFloating(y > 40)
    setCompact(y > 240 && y > prev)
  })

  useEffect(() => {
    const ids = items.map((i) => i.href.slice(1))
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) setActive(`#${e.target.id}`)
      },
      { rootMargin: '-45% 0px -50% 0px' },
    )
    ids.forEach((id) => {
      const el = document.getElementById(id)
      if (el) io.observe(el)
    })
    return () => io.disconnect()
  }, [])

  const spring = reduce ? { duration: 0 } : { type: 'spring' as const, stiffness: 380, damping: 36 }

  return (
    <header className="pointer-events-none fixed inset-x-0 top-0 z-40 flex justify-center px-3 pt-3 sm:px-4">
      <motion.nav
        aria-label="Principal"
        layout
        transition={spring}
        className={cn(
          'pointer-events-auto relative flex items-center justify-between gap-2 overflow-hidden border transition-colors duration-300',
          floating
            ? 'w-full max-w-[860px] rounded-full border-line-strong/80 bg-ink/70 px-2 py-1.5 shadow-[0_10px_40px_-12px_rgba(0,0,0,0.6)] backdrop-blur-md'
            : 'w-full max-w-7xl rounded-none border-transparent bg-transparent px-2 py-3',
          compact && 'max-w-[560px]',
        )}
      >
        <Link to="/" className="flex shrink-0 items-center gap-2.5 rounded-full px-2 py-1" aria-label="DARK POOL, início">
          <EclipseMark className="size-7" />
          <Wordmark className={cn('h-3 w-auto text-fg transition-opacity duration-300', compact ? 'hidden sm:block sm:opacity-0 sm:w-0' : 'hidden sm:block')} />
        </Link>

        <ul className="hidden items-center md:flex" onMouseLeave={() => setHover(null)}>
          {items.map((it) => {
            const on = (hover ?? active) === it.href
            return (
              <li key={it.href}>
                <a
                  href={it.href}
                  onMouseEnter={() => setHover(it.href)}
                  onFocus={() => setHover(it.href)}
                  onBlur={() => setHover(null)}
                  aria-current={active === it.href ? 'location' : undefined}
                  className={cn('relative block rounded-full px-4 py-2 text-[13px] transition-colors', on ? 'text-fg' : 'text-muted hover:text-fg')}
                >
                  {on && (
                    <motion.span layoutId="nav-pill" transition={spring} className="absolute inset-0 -z-10 rounded-full bg-raised/90 ring-1 ring-line-strong" />
                  )}
                  {it.label}
                </a>
              </li>
            )
          })}
        </ul>

        <div className="flex items-center gap-1.5">
          <Link
            to={enterTo}
            className="inline-flex h-9 items-center rounded-full bg-ember px-4 text-[13px] font-semibold text-ember-ink transition-colors hover:bg-ember-hi"
          >
            {enterLabel}
          </Link>
          <button
            type="button"
            className="inline-flex size-9 items-center justify-center rounded-full text-muted hover:bg-raised hover:text-fg md:hidden"
            aria-label={open ? 'Fechar menu' : 'Abrir menu'}
            aria-expanded={open}
            aria-controls="mobile-nav"
            onClick={() => setOpen((o) => !o)}
          >
            {open ? <X className="size-4" /> : <Menu className="size-4" />}
          </button>
        </div>

        <motion.span
          aria-hidden
          style={{ scaleX: progress }}
          className={cn('absolute bottom-0 left-0 h-px w-full origin-left bg-ember/80', !floating && 'opacity-0')}
        />
      </motion.nav>

      <AnimatePresence>
        {open && (
          <motion.div
            id="mobile-nav"
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.98 }}
            transition={{ duration: reduce ? 0 : 0.2 }}
            className="pointer-events-auto absolute top-[68px] inset-x-3 rounded-[var(--radius-lg)] border border-line-strong bg-ink/95 p-2 backdrop-blur-md md:hidden"
          >
            {items.map((it) => (
              <a key={it.href} href={it.href} onClick={() => setOpen(false)} className="block rounded-[var(--radius-md)] px-4 py-3 text-[15px] text-fg hover:bg-raised">
                {it.label}
              </a>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  )
}
