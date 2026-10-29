/**
 * Dual-thumb range slider (after shadcnspace "Price Range Slider", whose
 * source needs a 21st.dev login; rebuilt on Radix Slider). Previews a ghost
 * extension when hovering outside the selected range, animates the values
 * and scales the thumbs. Fully keyboard accessible through Radix.
 */
import * as SliderPrimitive from '@radix-ui/react-slider'
import { useRef, useState, type PointerEvent } from 'react'
import { cn } from '@/lib/utils'

type Props = {
  min: number
  max: number
  step?: number
  value: [number, number]
  onChange: (v: [number, number]) => void
  format?: (v: number) => string
  label: string
  className?: string
}

export function RangeSlider({ min, max, step = 1, value, onChange, format = String, label, className }: Props) {
  const trackRef = useRef<HTMLDivElement>(null)
  const [ghost, setGhost] = useState<number | null>(null)
  const pct = (v: number) => ((v - min) / (max - min)) * 100

  function onMove(e: PointerEvent) {
    const r = trackRef.current?.getBoundingClientRect()
    if (!r) return
    const raw = min + ((e.clientX - r.left) / r.width) * (max - min)
    const v = Math.min(max, Math.max(min, Math.round(raw / step) * step))
    setGhost(v < value[0] || v > value[1] ? v : null)
  }

  const ghostFrom = ghost == null ? null : ghost < value[0] ? pct(ghost) : pct(value[1])
  const ghostTo = ghost == null ? null : ghost < value[0] ? pct(value[0]) : pct(ghost)

  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[13px] font-medium text-fg/90">{label}</span>
        <span className="num text-xs text-muted" aria-live="polite">
          <span className="text-fg">{format(value[0])}</span> – <span className="text-fg">{format(value[1])}</span>
        </span>
      </div>
      <SliderPrimitive.Root
        min={min}
        max={max}
        step={step}
        value={value}
        minStepsBetweenThumbs={1}
        onValueChange={(v) => onChange([v[0], v[1]])}
        onPointerMove={onMove}
        onPointerLeave={() => setGhost(null)}
        className="relative flex h-6 w-full touch-none items-center select-none"
      >
        <SliderPrimitive.Track ref={trackRef} className="relative h-1 w-full grow overflow-hidden rounded-full bg-line-strong">
          {ghostFrom != null && ghostTo != null && (
            <span
              className="absolute inset-y-0 bg-ember/25 transition-[left,width] duration-150"
              style={{ left: `${ghostFrom}%`, width: `${ghostTo - ghostFrom}%` }}
              aria-hidden
            />
          )}
          <SliderPrimitive.Range className="absolute h-full bg-ember" />
        </SliderPrimitive.Track>
        {[0, 1].map((i) => (
          <SliderPrimitive.Thumb
            key={i}
            aria-label={i === 0 ? `${label}: mínimo` : `${label}: máximo`}
            className="block size-4 rounded-full border-2 border-ember bg-ink shadow-[0_0_0_4px_rgba(255,65,3,0.12)] transition-transform duration-150 hover:scale-125 focus-visible:scale-125 focus-visible:outline-none active:scale-110"
          />
        ))}
      </SliderPrimitive.Root>
    </div>
  )
}
