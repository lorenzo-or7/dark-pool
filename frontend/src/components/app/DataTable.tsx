/**
 * Sortable, searchable table with column resizing (after isaiahbjork
 * "Resizable Table" and "Financial Markets Table"; both sources need a
 * 21st.dev login). Horizontal scroll inside its own box on small screens.
 */
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'
import { useMemo, useRef, useState, type PointerEvent, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

export type Column<T> = {
  key: string
  header: string
  cell: (row: T) => ReactNode
  sort?: (row: T) => number | string | null
  align?: 'left' | 'right'
  width?: number
  className?: string
}

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  caption,
  empty,
  onRowClick,
  selectedKey,
  initialSort,
  minWidth = 560,
}: {
  rows: T[]
  columns: Column<T>[]
  rowKey: (r: T) => string
  caption: string
  empty?: ReactNode
  onRowClick?: (r: T) => void
  selectedKey?: string | null
  initialSort?: { key: string; dir: 'asc' | 'desc' }
  minWidth?: number
}) {
  const [sort, setSort] = useState(initialSort ?? null)
  const [widths, setWidths] = useState<Record<string, number>>(() => Object.fromEntries(columns.filter((c) => c.width).map((c) => [c.key, c.width!])))
  const drag = useRef<{ key: string; x: number; w: number } | null>(null)

  const sorted = useMemo(() => {
    if (!sort) return rows
    const col = columns.find((c) => c.key === sort.key)
    if (!col?.sort) return rows
    const get = col.sort
    return [...rows].sort((a, b) => {
      const va = get(a)
      const vb = get(b)
      if (va == null && vb == null) return 0
      if (va == null) return 1
      if (vb == null) return -1
      const r = typeof va === 'number' && typeof vb === 'number' ? va - vb : String(va).localeCompare(String(vb), 'pt-BR')
      return sort.dir === 'asc' ? r : -r
    })
  }, [rows, sort, columns])

  function startResize(e: PointerEvent, key: string) {
    e.preventDefault()
    e.stopPropagation()
    const th = (e.target as HTMLElement).parentElement as HTMLElement
    drag.current = { key, x: e.clientX, w: th.getBoundingClientRect().width }
    const move = (ev: globalThis.PointerEvent) => {
      if (!drag.current) return
      const w = Math.max(64, Math.min(520, drag.current.w + ev.clientX - drag.current.x))
      setWidths((s) => ({ ...s, [drag.current!.key]: w }))
    }
    const up = () => {
      drag.current = null
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  if (!rows.length) return <>{empty}</>

  return (
    <div className="-mx-1 overflow-x-auto px-1">
      <table className="w-full table-fixed border-collapse text-sm" style={{ minWidth }}>
        <caption className="sr-only">{caption}</caption>
        <colgroup>
          {columns.map((c) => (
            <col key={c.key} style={widths[c.key] ? { width: widths[c.key] } : undefined} />
          ))}
        </colgroup>
        <thead>
          <tr className="border-b border-line">
            {columns.map((c) => {
              const active = sort?.key === c.key
              return (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={active ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : undefined}
                  className={cn('group relative pb-2 text-[11.5px] font-normal text-faint', c.align === 'right' ? 'text-right' : 'text-left')}
                >
                  {c.sort ? (
                    <button
                      type="button"
                      onClick={() => setSort((s) => (s?.key === c.key ? { key: c.key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key: c.key, dir: 'desc' }))}
                      className={cn('inline-flex items-center gap-1 hover:text-fg', active && 'text-fg')}
                    >
                      {c.header}
                      {active ? sort!.dir === 'asc' ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" /> : <ArrowUpDown className="size-3 opacity-40" />}
                    </button>
                  ) : (
                    c.header
                  )}
                  <span
                    onPointerDown={(e) => startResize(e, c.key)}
                    className="absolute top-0 right-0 hidden h-full w-2 cursor-col-resize group-hover:block after:absolute after:top-1 after:right-0.5 after:h-4 after:w-px after:bg-line-strong md:block md:opacity-0 md:group-hover:opacity-100"
                    aria-hidden
                  />
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const k = rowKey(r)
            return (
              <tr
                key={k}
                onClick={onRowClick ? () => onRowClick(r) : undefined}
                className={cn(
                  'border-b border-line/70 transition-colors',
                  onRowClick && 'cursor-pointer hover:bg-raised/60',
                  selectedKey === k && 'bg-raised shadow-[inset_2px_0_0_0_var(--color-ember)]',
                )}
              >
                {columns.map((c) => (
                  <td key={c.key} className={cn('truncate py-2.5 pr-3', c.align === 'right' && 'text-right', c.className)}>
                    {c.cell(r)}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
