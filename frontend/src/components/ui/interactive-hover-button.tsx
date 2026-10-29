/**
 * Interactive Hover Button (after Dillion Verma / Magic UI): a small dot grows
 * to fill the pill on hover while the label slides out and an arrow label
 * slides in. In-house build: the 21st.dev source needs a login. Accent #FF4103.
 */
import { ArrowRight } from 'lucide-react'
import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { Link } from 'react-router-dom'
import { cn } from '@/lib/utils'

type Common = { children: string; tone?: 'ember' | 'ghost'; className?: string }

function Inner({ children, tone }: { children: string; tone: 'ember' | 'ghost' }) {
  return (
    <>
      <span className="flex items-center gap-2.5">
        <span
          className={cn(
            'size-2 rounded-full transition-all duration-300 ease-[var(--ease-out-expo)] group-hover:scale-[100.8]',
            tone === 'ember' ? 'bg-ember' : 'bg-fg',
          )}
          aria-hidden
        />
        <span className="inline-block transition-all duration-300 ease-[var(--ease-out-expo)] group-hover:translate-x-12 group-hover:opacity-0">
          {children}
        </span>
      </span>
      <span
        className={cn(
          'absolute inset-0 z-10 flex translate-x-12 items-center justify-center gap-2 opacity-0 transition-all duration-300 ease-[var(--ease-out-expo)] group-hover:-translate-x-1 group-hover:opacity-100',
          tone === 'ember' ? 'text-ember-ink' : 'text-ink',
        )}
        aria-hidden
      >
        <span>{children}</span>
        <ArrowRight className="size-4" />
      </span>
    </>
  )
}

const base =
  'group relative inline-flex h-12 min-w-44 cursor-pointer items-center justify-center overflow-hidden rounded-full border px-6 text-[15px] font-semibold focus-visible:outline-offset-4'

export const InteractiveHoverButton = forwardRef<HTMLButtonElement, Common & ButtonHTMLAttributes<HTMLButtonElement>>(
  ({ children, tone = 'ember', className, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(base, tone === 'ember' ? 'border-ember/60 bg-ink text-fg' : 'border-line-strong bg-ink/40 text-fg', className)}
      {...props}
    >
      <Inner tone={tone}>{children}</Inner>
    </button>
  ),
)
InteractiveHoverButton.displayName = 'InteractiveHoverButton'

export function InteractiveHoverLink({ to, children, tone = 'ember', className }: Common & { to: string }) {
  const external = to.startsWith('#')
  const cls = cn(base, tone === 'ember' ? 'border-ember/60 bg-ink text-fg' : 'border-line-strong bg-ink/40 text-fg', className)
  if (external)
    return (
      <a href={to} className={cls}>
        <Inner tone={tone}>{children}</Inner>
      </a>
    )
  return (
    <Link to={to} className={cls}>
      <Inner tone={tone}>{children}</Inner>
    </Link>
  )
}
