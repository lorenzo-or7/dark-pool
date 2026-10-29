/**
 * The eclipse icon: a dark core inside a thin orange rim that brightens toward
 * the upper right, crossed by a short horizontal flare (board section 03).
 */
import { useId } from 'react'

type Props = { className?: string; title?: string; flare?: boolean; /** rim stroke in viewBox units; thinner for large decorative use */ weight?: number }

export function EclipseMark({ className, title = 'DARK POOL', flare = true, weight = 2.25 }: Props) {
  const id = useId().replace(/:/g, '')
  return (
    <svg viewBox="0 0 64 64" className={className} {...(title ? { role: 'img', 'aria-label': title } : { 'aria-hidden': true })}>
      {title && <title>{title}</title>}
      <defs>
        <radialGradient id={`core-${id}`} cx="0.46" cy="0.54" r="0.62">
          <stop offset="0" stopColor="#000a10" />
          <stop offset="0.82" stopColor="#00121b" />
          <stop offset="1" stopColor="#02202c" />
        </radialGradient>
        <linearGradient id={`rim-${id}`} x1="0.15" y1="0.95" x2="0.9" y2="0.08">
          <stop offset="0" stopColor="#ff4103" stopOpacity="0.35" />
          <stop offset="0.55" stopColor="#ff4103" stopOpacity="0.85" />
          <stop offset="1" stopColor="#ff8a55" />
        </linearGradient>
        <linearGradient id={`flare-${id}`} x1="0" x2="1">
          <stop offset="0" stopColor="#ff4103" stopOpacity="0" />
          <stop offset="0.5" stopColor="#ffb08a" />
          <stop offset="1" stopColor="#ff4103" stopOpacity="0" />
        </linearGradient>
      </defs>
      <circle cx="32" cy="32" r="22.5" fill={`url(#core-${id})`} />
      <circle cx="32" cy="32" r="22.5" fill="none" stroke={`url(#rim-${id})`} strokeWidth={weight} />
      <path d="M44.5 13.2a22.5 22.5 0 0 1 9.4 13.4" fill="none" stroke="#ffd2bd" strokeWidth={weight * 0.55} strokeLinecap="round" opacity={weight < 1 ? 0.7 : 0.9} />
      {flare && <rect x="4" y={32 - weight * 0.27} width="56" height={weight * 0.53} rx={weight * 0.27} fill={`url(#flare-${id})`} />}
    </svg>
  )
}
