/**
 * DARK POOL wordmark, rebuilt as a vector from the approved identity board
 * (06_IDENTIDADE_FINAL_APROVADA.png): wide geometry, uniform strokes, precision
 * cuts between stems and bowls, an open A carrying the orange triangle.
 * Provisional until the designer's master vector file is delivered.
 */
import { useId } from 'react'

const S = 15 // stroke
const W = 120 // letter width
const G = 46 // letter gap
const WORD = 110 // word gap
const H = 100
const h = S / 2

type Props = {
  className?: string
  title?: string
  /** The thin orange horizon line that crosses the primary lockup. */
  horizon?: boolean
}

function D(x: number) {
  return (
    <>
      <path d={`M${x + h},${h}V${H - h}`} />
      <path d={`M${x + S + 7},${h}H${x + W - 40}A32.5 32.5 0 0 1 ${x + W - h},40V60A32.5 32.5 0 0 1 ${x + W - 40},${H - h}H${x + S + 7}`} />
    </>
  )
}

function A(x: number) {
  return <path d={`M${x + 3},${H + 8}L${x + W / 2},-6L${x + W - 3},${H + 8}`} strokeLinejoin="miter" />
}

function bowl(x: number) {
  return `M${x + S + 7},${h}H${x + W - 31}A23.75 23.75 0 0 1 ${x + W - 31},55H${x + S + 7}`
}

function R(x: number) {
  return (
    <>
      <path d={`M${x + h},${h}V${H - h}`} />
      <path d={`M${x + S + 7},${h}H${x + W - 31}A23.75 23.75 0 0 1 ${x + W - 31},55H${x + S + 7}`} />
      <path d={`M${x + W - 52},55L${x + W - 4},${H + 12}`} />
    </>
  )
}

function K(x: number) {
  return (
    <>
      <path d={`M${x + h},${h}V${H - h}`} />
      <path d={`M${x + W - 2},-8L${x + 36},50L${x + W - 2},${H + 8}`} strokeLinejoin="bevel" />
    </>
  )
}

function P(x: number) {
  return (
    <>
      <path d={`M${x + h},${h}V${H - h}`} />
      <path d={bowl(x)} />
    </>
  )
}

function O(x: number) {
  return <rect x={x + h} y={h} width={W - S} height={H - S} rx={32} />
}

function L(x: number) {
  return <path d={`M${x + h},${h}V${H - h}H${x + W}`} strokeLinejoin="miter" />
}

const X = (i: number, word: number) => word * (4 * W + 3 * G + WORD) + i * (W + G)
export const WORDMARK_WIDTH = 2 * (4 * W + 3 * G) + WORD
const A_X = X(1, 0)

export function Wordmark({ className, title = 'DARK POOL', horizon = false }: Props) {
  const clip = useId()
  return (
    <svg
      viewBox={`0 0 ${WORDMARK_WIDTH} ${H}`}
      className={className}
      role="img"
      aria-label={title}
      overflow="visible"
    >
      <title>{title}</title>
      <defs>
        <clipPath id={clip}>
          <rect x="-1" y="0" width={WORDMARK_WIDTH + 2} height={H} />
        </clipPath>
      </defs>
      {horizon && (
        <line
          x1={-WORDMARK_WIDTH * 0.06}
          x2={WORDMARK_WIDTH * 1.06}
          y1={H / 2}
          y2={H / 2}
          stroke="var(--color-ember)"
          strokeOpacity="0.55"
          strokeWidth="1.5"
        />
      )}
      <g clipPath={`url(#${clip})`} fill="none" stroke="currentColor" strokeWidth={S} strokeLinecap="butt">
        {D(X(0, 0))}
        {A(X(1, 0))}
        {R(X(2, 0))}
        {K(X(3, 0))}
        {P(X(0, 1))}
        {O(X(1, 1))}
        {O(X(2, 1))}
        {L(X(3, 1))}
      </g>
      <path d={`M${A_X + W / 2 - 14},${H}L${A_X + W / 2},${H - 25}L${A_X + W / 2 + 14},${H}Z`} fill="var(--color-ember)" />
    </svg>
  )
}

export function Tagline({ className }: { className?: string }) {
  return (
    <span className={className} style={{ fontFamily: 'var(--font-mono)', letterSpacing: '0.62em', textTransform: 'uppercase' }}>
      Beyond the market
    </span>
  )
}
