/**
 * Segmented control with a sliding thumb (after Halaska Studio's "Segmented
 * Control — two segments"; original source requires a 21st.dev login, so this
 * is an in-house build of the documented behavior). Radio-group semantics,
 * arrow-key navigation.
 */
import { motion, useReducedMotion } from 'motion/react'
import { useId, useRef, type KeyboardEvent } from 'react'
import { cn } from '@/lib/utils'

type Option<T extends string> = { value: T; label: string }

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  label,
  size = 'md',
  className,
}: {
  options: Option<T>[]
  value: T
  onChange: (v: T) => void
  label: string
  size?: 'sm' | 'md'
  className?: string
}) {
  const id = useId()
  const reduce = useReducedMotion()
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const idx = Math.max(0, options.findIndex((o) => o.value === value))

  function onKey(e: KeyboardEvent) {
    const d = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0
    if (!d) return
    e.preventDefault()
    const next = (idx + d + options.length) % options.length
    onChange(options[next].value)
    refs.current[next]?.focus()
  }

  return (
    <div
      role="radiogroup"
      aria-label={label}
      onKeyDown={onKey}
      className={cn('relative inline-flex rounded-[var(--radius-md)] border border-line bg-abyss/70 p-1', className)}
    >
      {options.map((o, i) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el
            }}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(o.value)}
            className={cn(
              'relative z-0 flex-1 rounded-[7px] font-medium whitespace-nowrap transition-colors duration-200 focus-visible:outline-offset-0',
              size === 'sm' ? 'h-7 px-3 text-xs' : 'h-8 px-4 text-[13px]',
              active ? 'text-fg' : 'text-muted hover:text-fg',
            )}
          >
            {active && (
              <motion.span
                layoutId={`seg-thumb-${id}`}
                className="absolute inset-0 -z-10 rounded-[7px] border border-line-strong bg-overlay shadow-[0_1px_0_0_rgba(255,255,255,0.04)_inset]"
                transition={reduce ? { duration: 0 } : { type: 'spring', stiffness: 520, damping: 40 }}
              />
            )}
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
