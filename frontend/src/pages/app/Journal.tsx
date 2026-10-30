import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ImagePlus, Pencil, Plus, Search, Trash2, X } from 'lucide-react'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/app/AppShell'
import { Badge, DataBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmDialog, Dialog } from '@/components/ui/dialog'
import { Field, Input, Select, Textarea } from '@/components/ui/field'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/states'
import { api } from '@/lib/api'
import { fmt, localDateTime, shortDate, todayNY } from '@/lib/format'
import type { Experiment, JournalEntry, Strategy } from '@/lib/types'

const KINDS: Record<JournalEntry['kind'], { label: string; tone: 'neutral' | 'ember' | 'up' | 'down' | 'caution' | 'sim' }> = {
  note: { label: 'Nota', tone: 'neutral' },
  hypothesis: { label: 'Hipótese', tone: 'ember' },
  simulated_trade: { label: 'Operação simulada', tone: 'sim' },
  lesson: { label: 'Aprendizado', tone: 'up' },
  error: { label: 'Erro', tone: 'down' },
}

type Draft = {
  title: string
  body: string
  kind: JournalEntry['kind']
  symbol: string
  strategy_id: string
  experiment_id: string
  tags: string
  entry_date: string
  trade: { entry: string; stop: string; exit: string; shares: string }
}

const emptyDraft = (p?: Partial<Draft>): Draft => ({
  title: '',
  body: '',
  kind: 'note',
  symbol: '',
  strategy_id: '',
  experiment_id: '',
  tags: '',
  entry_date: todayNY(),
  trade: { entry: '', stop: '', exit: '', shares: '' },
  ...p,
})

function Attachment({ id, name }: { id: string; name: string }) {
  const [url, setUrl] = useState<string | null>(null)
  const [err, setErr] = useState(false)
  useEffect(() => {
    let alive = true
    let u: string | null = null
    api<Response>(`/attachments/${id}`, { raw: true })
      .then((r) => r.blob())
      .then((b) => {
        u = URL.createObjectURL(b)
        if (alive) setUrl(u)
      })
      .catch(() => alive && setErr(true))
    return () => {
      alive = false
      if (u) URL.revokeObjectURL(u)
    }
  }, [id])
  if (err) return <span className="text-xs text-down">Falha ao carregar {name}</span>
  if (!url) return <Skeleton className="h-24 w-36" />
  return (
    <a href={url} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-[8px] border border-line">
      <img src={url} alt={`Captura: ${name}`} className="h-24 w-36 object-cover" loading="lazy" />
    </a>
  )
}

function Editor({ open, onOpenChange, entry, preset }: { open: boolean; onOpenChange: (o: boolean) => void; entry: JournalEntry | null; preset?: Partial<Draft> }) {
  const qc = useQueryClient()
  const [d, setD] = useState<Draft>(emptyDraft(preset))
  const [file, setFile] = useState<File | null>(null)
  const strategies = useQuery({ queryKey: ['strategies', false], queryFn: ({ signal }) => api<Strategy[]>('/strategies', { signal }), enabled: open })
  const experiments = useQuery({ queryKey: ['experiments', 'all'], queryFn: ({ signal }) => api<Experiment[]>('/experiments?limit=100', { signal }), enabled: open })
  useEffect(() => {
    if (!open) return
    setFile(null)
    setD(
      entry
        ? {
            title: entry.title,
            body: entry.body,
            kind: entry.kind,
            symbol: entry.symbol ?? '',
            strategy_id: entry.strategy_id ?? '',
            experiment_id: entry.experiment_id ?? '',
            tags: entry.tags.join(', '),
            entry_date: entry.entry_date,
            trade: { entry: String(entry.trade?.entry ?? ''), stop: String(entry.trade?.stop ?? ''), exit: String(entry.trade?.exit ?? ''), shares: String(entry.trade?.shares ?? '') },
          }
        : emptyDraft(preset),
    )
  }, [open, entry, preset])
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }))
  const t = d.trade
  const r = Number(t.entry) > 0 && Number(t.stop) > 0 && Number(t.exit) > 0 && Number(t.stop) < Number(t.entry) ? (Number(t.exit) - Number(t.entry)) / (Number(t.entry) - Number(t.stop)) : null

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        title: d.title,
        body: d.body,
        kind: d.kind,
        symbol: d.symbol || null,
        strategy_id: d.strategy_id || null,
        experiment_id: d.experiment_id || null,
        tags: d.tags.split(',').map((x) => x.trim()).filter(Boolean),
        entry_date: d.entry_date,
        trade:
          d.kind === 'simulated_trade' && t.entry && t.stop
            ? { side: 'buy', entry: Number(t.entry), stop: Number(t.stop), exit: t.exit ? Number(t.exit) : null, shares: t.shares ? Number(t.shares) : null }
            : null,
      }
      const saved = entry ? await api<JournalEntry>(`/journal/${entry.id}`, { method: 'PUT', body }) : await api<JournalEntry>('/journal', { body })
      if (file) {
        const form = new FormData()
        form.append('file', file)
        await api(`/journal/${saved.id}/attachments`, { form })
      }
      return saved
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['journal'] })
      onOpenChange(false)
    },
  })
  const removeAtt = useMutation({
    mutationFn: (id: string) => api(`/attachments/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['journal'] }),
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    if (d.title.trim()) save.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={entry ? 'Editar registro' : 'Novo registro'} className="max-w-2xl">
      <form onSubmit={submit} className="space-y-3" noValidate>
        <Field label="Título" error={save.isError && !d.title.trim() ? 'Obrigatório.' : null}>
          {(p) => <Input {...p} value={d.title} onChange={(e) => set('title', e.target.value)} maxLength={160} autoFocus />}
        </Field>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Field label="Tipo">
            {(p) => (
              <Select {...p} value={d.kind} onChange={(e) => set('kind', e.target.value as Draft['kind'])}>
                {Object.entries(KINDS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v.label}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Data">{(p) => <Input {...p} type="date" value={d.entry_date} onChange={(e) => set('entry_date', e.target.value)} />}</Field>
          <Field label="Ativo">{(p) => <Input {...p} value={d.symbol} onChange={(e) => set('symbol', e.target.value.toUpperCase())} className="num" placeholder="opcional" />}</Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Estratégia">
            {(p) => (
              <Select {...p} value={d.strategy_id} onChange={(e) => set('strategy_id', e.target.value)}>
                <option value="">Nenhuma</option>
                {(strategies.data ?? []).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Experimento">
            {(p) => (
              <Select {...p} value={d.experiment_id} onChange={(e) => set('experiment_id', e.target.value)}>
                <option value="">Nenhum</option>
                {(experiments.data ?? []).map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.title}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>
        {d.kind === 'simulated_trade' && (
          <fieldset className="rounded-[var(--radius-md)] border border-line p-3">
            <legend className="px-1 text-xs text-muted">Operação simulada (compra)</legend>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {(['entry', 'stop', 'exit', 'shares'] as const).map((k) => (
                <Field key={k} label={{ entry: 'Entrada', stop: 'Stop', exit: 'Saída', shares: 'Ações' }[k]}>
                  {(p) => <Input {...p} type="number" step={k === 'shares' ? 1 : 0.01} value={t[k]} onChange={(e) => set('trade', { ...t, [k]: e.target.value })} />}
                </Field>
              ))}
            </div>
            <p className="num mt-2 text-xs text-muted">{r != null ? `Resultado: ${fmt.r(r, 2)}` : 'Preencha entrada, stop e saída para calcular o R.'}</p>
          </fieldset>
        )}
        <Field label="Tags" hint="Separadas por vírgula.">{(p) => <Input {...p} value={d.tags} onChange={(e) => set('tags', e.target.value)} placeholder="orb, gap, erro-de-execução" />}</Field>
        <Field label="Observações">{(p) => <Textarea {...p} value={d.body} onChange={(e) => set('body', e.target.value)} className="min-h-36" />}</Field>
        <div>
          <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-muted hover:text-fg">
            <ImagePlus className="size-4" />
            {file ? file.name : 'Anexar captura de gráfico (PNG, JPEG ou WebP, até 5 MB)'}
            <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
          {entry && entry.attachments.length > 0 && (
            <ul className="mt-2 flex flex-wrap gap-2">
              {entry.attachments.map((a) => (
                <li key={a.id} className="flex items-center gap-1 rounded-full border border-line-strong py-0.5 pr-1 pl-3 text-xs text-muted">
                  {a.filename}
                  <button type="button" onClick={() => removeAtt.mutate(a.id)} className="rounded-full p-1 hover:text-down" aria-label={`Remover ${a.filename}`}>
                    <X className="size-3" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {save.isError && <ErrorState error={save.error} />}
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" disabled={!d.title.trim() || save.isPending}>
            {save.isPending ? 'Salvando…' : 'Salvar'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

export default function Journal() {
  const qc = useQueryClient()
  const [sp, setSp] = useSearchParams()
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  const [kind, setKind] = useState('')
  const [tag, setTag] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [editing, setEditing] = useState<JournalEntry | null>(null)
  const [open, setOpen] = useState(false)
  const [del, setDel] = useState<JournalEntry | null>(null)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 250)
    return () => clearTimeout(t)
  }, [q])
  const preset = useMemo<Partial<Draft> | undefined>(
    () => (sp.get('new') ? { experiment_id: sp.get('experiment') ?? '', symbol: sp.get('symbol') ?? '', kind: 'lesson', title: '' } : undefined),
    [sp],
  )
  useEffect(() => {
    if (sp.get('new')) {
      setEditing(null)
      setOpen(true)
    }
  }, [sp])

  const params = new URLSearchParams()
  if (debounced) params.set('q', debounced)
  if (kind) params.set('kind', kind)
  if (tag) params.set('tag', tag)
  if (from) params.set('date_from', from)
  if (to) params.set('date_to', to)
  const list = useQuery({ queryKey: ['journal', params.toString()], queryFn: ({ signal }) => api<JournalEntry[]>(`/journal?${params}`, { signal }) })
  const strategies = useQuery({ queryKey: ['strategies', false], queryFn: ({ signal }) => api<Strategy[]>('/strategies', { signal }) })
  const sName = Object.fromEntries((strategies.data ?? []).map((s) => [s.id, s.name]))
  const remove = useMutation({
    mutationFn: (id: string) => api(`/journal/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      setDel(null)
      void qc.invalidateQueries({ queryKey: ['journal'] })
    },
  })
  const allTags = [...new Set((list.data ?? []).flatMap((e) => e.tags))].sort()

  return (
    <div className="mx-auto max-w-[1100px]">
      <PageHeader eyebrow="Resultados" title="Trading Journal" description="Diário compartilhado de hipóteses, operações simuladas, erros e aprendizados. Cada registro mostra quem escreveu.">
        <Button
          variant="primary"
          onClick={() => {
            setEditing(null)
            setOpen(true)
          }}
        >
          <Plus /> Novo registro
        </Button>
      </PageHeader>

      <div className="mb-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-[1fr_180px_160px_150px_150px]">
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint" aria-hidden />
          <label htmlFor="j-q" className="sr-only">
            Pesquisar registros
          </label>
          <Input id="j-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Pesquisar título, texto ou ativo" className="pl-9" />
        </div>
        <Select aria-label="Filtrar por tipo" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">Todos os tipos</option>
          {Object.entries(KINDS).map(([k, v]) => (
            <option key={k} value={k}>
              {v.label}
            </option>
          ))}
        </Select>
        <Select aria-label="Filtrar por tag" value={tag} onChange={(e) => setTag(e.target.value)}>
          <option value="">Todas as tags</option>
          {allTags.map((t) => (
            <option key={t} value={t}>
              #{t}
            </option>
          ))}
        </Select>
        <Input type="date" aria-label="Data inicial" value={from} onChange={(e) => setFrom(e.target.value)} />
        <Input type="date" aria-label="Data final" value={to} onChange={(e) => setTo(e.target.value)} />
      </div>

      {list.isLoading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
      ) : list.isError ? (
        <ErrorState error={list.error} retry={() => void list.refetch()} />
      ) : !list.data?.length ? (
        <EmptyState title={debounced || kind || tag || from || to ? 'Nenhum registro com esses filtros' : 'O diário está vazio'}>
          Registre hipóteses antes de testar e o que aprendeu depois. Isso evita reinterpretar resultados a posteriori.
        </EmptyState>
      ) : (
        <ol className="relative space-y-3 border-l border-line pl-5">
          {list.data.map((e) => (
            <li key={e.id} className="relative">
              <span className="absolute top-5 -left-[25px] size-2 rounded-full bg-line-strong ring-4 ring-ink" aria-hidden />
              <article className="panel p-4">
                <header className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={KINDS[e.kind].tone}>{KINDS[e.kind].label}</Badge>
                      {e.symbol && (
                        <Link to={`/app/scanner?symbol=${e.symbol}`} className="num text-xs text-fg hover:text-ember">
                          {e.symbol}
                        </Link>
                      )}
                      {e.is_demo && <DataBadge kind="demo" />}
                    </div>
                    <h2 className="mt-2 text-[15px] font-medium text-fg">{e.title}</h2>
                    <p className="mt-0.5 text-xs text-faint">
                      {shortDate(e.entry_date)}{e.author_name ? ` · ${e.author_name}` : ''} · editado {localDateTime(e.updated_at)}
                    </p>
                  </div>
                  <div className="flex gap-1">
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={`Editar ${e.title}`}
                      onClick={() => {
                        setEditing(e)
                        setOpen(true)
                      }}
                    >
                      <Pencil />
                    </Button>
                    <Button size="icon" variant="ghost" aria-label={`Excluir ${e.title}`} onClick={() => setDel(e)}>
                      <Trash2 />
                    </Button>
                  </div>
                </header>
                {e.body && <p className="mt-3 text-sm leading-relaxed whitespace-pre-wrap text-fg/85">{e.body}</p>}
                {e.trade && (
                  <p className="num mt-3 text-xs text-muted">
                    compra {fmt.num(e.trade.entry)} · stop {fmt.num(e.trade.stop)}
                    {e.trade.exit != null && ` · saída ${fmt.num(e.trade.exit)} · ${fmt.r((e.trade.exit - e.trade.entry) / (e.trade.entry - e.trade.stop), 2)}`}
                    {e.trade.shares != null && ` · ${e.trade.shares} ações`}
                  </p>
                )}
                {e.attachments.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {e.attachments.map((a) => (
                      <Attachment key={a.id} id={a.id} name={a.filename} />
                    ))}
                  </div>
                )}
                <footer className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  {e.tags.map((t) => (
                    <button key={t} onClick={() => setTag(t)} className="text-muted hover:text-ember">
                      #{t}
                    </button>
                  ))}
                  {e.strategy_id && (
                    <Link to={`/app/strategies/${e.strategy_id}`} className="text-ember hover:underline">
                      Estratégia: {sName[e.strategy_id] ?? 'abrir'}
                    </Link>
                  )}
                  {e.experiment_id && (
                    <Link to={`/app/time-machine?exp=${e.experiment_id}`} className="text-ember hover:underline">
                      Abrir experimento vinculado
                    </Link>
                  )}
                </footer>
              </article>
            </li>
          ))}
        </ol>
      )}

      <Editor
        open={open}
        onOpenChange={(o) => {
          setOpen(o)
          if (!o && sp.get('new')) setSp({})
        }}
        entry={editing}
        preset={preset}
      />
      <ConfirmDialog
        open={!!del}
        onOpenChange={(o) => !o && setDel(null)}
        title="Excluir registro?"
        description={`“${del?.title ?? ''}” e os anexos serão apagados para os dois membros do workspace.`}
        confirmLabel="Excluir"
        busy={remove.isPending}
        onConfirm={() => del && remove.mutate(del.id)}
      />
    </div>
  )
}
