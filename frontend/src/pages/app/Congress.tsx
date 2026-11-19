/**
 * Congresso (Bloco 10): House Periodic Transaction Reports from the House Clerk, read by
 * trader-pelosi on the server (GET /api/congress/ptrs and /api/congress/ptrs/{doc_id}).
 * The display policy is decided by the API; this page only reflects it.
 */
import { useQuery } from '@tanstack/react-query'
import { ExternalLink, Search } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { PageHeader } from '@/components/app/AppShell'
import { DataTable, type Column } from '@/components/app/DataTable'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field, Input, Select } from '@/components/ui/field'
import { EmptyState, ErrorState, Notice, Skeleton } from '@/components/ui/states'
import { api } from '@/lib/api'
import { fmt, localDateTime, shortDate } from '@/lib/format'
import { useDisplayPolicy } from '@/lib/policy'

type Senate = { covered: boolean; url: string; note: string }

export type PtrFiling = {
  doc_id: string
  type: string
  type_name: string
  last: string
  first: string
  name: string
  district: string
  year: number
  filed: string | null
  url: string
  collected_at: string
}

export type PtrIndex = {
  year: number
  filings: PtrFiling[]
  total: number
  collected_at: string
  from_cache: boolean
  source: string
  source_url: string
  senate: Senate
  disclaimer: string
}

export type PtrRow = {
  owner: string
  owner_name: string
  asset: string
  ticker: string | null
  asset_type: string | null
  type: string
  type_name: string
  date: string | null
  notified: string | null
  amount: string
  amount_low: number | null
  amount_high: number | null
  status: string | null
  account: string | null
  description: string | null
  option?: { contracts: number; kind: string; strike: number; expires: string | null; exercised: boolean }
  shares?: number
  days_to_disclose?: number
  late?: boolean
}

export type PtrReport = {
  doc_id: string
  year: number
  pdf_url: string
  collected_at: string
  from_cache: boolean
  readable: boolean
  name?: string | null
  status?: string | null
  district?: string | null
  filed: string | null
  rows: PtrRow[] | null
  note: string | null
  dates_note?: string
  source: string
  senate: Senate
  disclaimer: string
}

const TXN: Record<string, { label: string; tone: 'up' | 'down' | 'neutral' | 'caution' }> = {
  purchase: { label: 'Compra', tone: 'up' },
  sale: { label: 'Venda', tone: 'down' },
  'partial sale': { label: 'Venda parcial', tone: 'down' },
  exchange: { label: 'Troca', tone: 'neutral' },
}
const OWNER: Record<string, string> = { spouse: 'Cônjuge', joint: 'Conjunta', 'dependent child': 'Filho dependente', self: 'Parlamentar' }
const ASSET: Record<string, string> = { ST: 'ação', OP: 'opção', AB: 'outro ativo', GS: 'título público', CS: 'título corporativo', EF: 'ETF', MF: 'fundo' }

const thisYear = new Date().getFullYear()
const YEARS = Array.from({ length: 6 }, (_, i) => thisYear - i)

function SenateNotice({ senate }: { senate?: Senate }) {
  return (
    <Notice>
      {senate?.note ?? 'Senado não coberto: os relatórios ficam atrás de um termo que cada pessoa aceita no eFD; o laboratório não automatiza esse aceite.'}{' '}
      <a href={senate?.url ?? 'https://efdsearch.senate.gov/search/'} target="_blank" rel="noopener noreferrer" className="text-fg underline-offset-2 hover:text-ember hover:underline">
        Abrir o eFD do Senado
      </a>
    </Notice>
  )
}

function asset(r: PtrRow) {
  const extra = r.option
    ? `${r.option.exercised ? 'exercício de ' : ''}${fmt.int(r.option.contracts)} ${r.option.kind === 'call' ? 'calls' : 'puts'}, strike US$ ${fmt.num(r.option.strike)}, vencimento ${shortDate(r.option.expires)}`
    : r.shares
      ? `${fmt.int(r.shares)} ações`
      : null
  return (
    <div className="min-w-0 whitespace-normal">
      <p className="text-fg">
        {r.ticker && <span className="num mr-1.5 text-ember">{r.ticker}</span>}
        {r.asset}
        {r.asset_type && <span className="ml-1 text-faint">({ASSET[r.asset_type] ?? r.asset_type})</span>}
      </p>
      {extra && <p className="text-[11px] text-muted">{extra}</p>}
      {r.account && <p className="text-[11px] text-faint">Conta: {r.account}</p>}
    </div>
  )
}

const rowColumns: Column<PtrRow>[] = [
  { key: 'date', header: 'Operação', cell: (r) => <span className="num">{shortDate(r.date)}</span>, sort: (r) => r.date, width: 112 },
  {
    key: 'type',
    header: 'Tipo',
    cell: (r) => {
      const t = TXN[r.type_name] ?? { label: r.type_name, tone: 'neutral' as const }
      return <Badge tone={t.tone}>{t.label}</Badge>
    },
    sort: (r) => r.type_name,
    width: 132,
  },
  { key: 'asset', header: 'Ativo', cell: asset, sort: (r) => r.ticker ?? r.asset },
  { key: 'owner', header: 'Titular', cell: (r) => OWNER[r.owner_name] ?? r.owner_name, sort: (r) => r.owner_name, width: 128 },
  { key: 'amount', header: 'Faixa de valor', cell: (r) => <span className="num">{r.amount}</span>, sort: (r) => r.amount_low, width: 220, className: 'whitespace-normal' },
  {
    key: 'days',
    header: 'Dias até divulgar',
    align: 'right',
    cell: (r) => (
      <span className="inline-flex items-center gap-2">
        <span className="num">{r.days_to_disclose ?? '—'}</span>
        {r.late && (
          <Badge tone="caution" title="Divulgado mais de 45 dias depois da operação (limite do STOCK Act).">
            atrasado
          </Badge>
        )}
      </span>
    ),
    sort: (r) => r.days_to_disclose ?? null,
    width: 168,
  },
]

function Report({ filing }: { filing: PtrFiling }) {
  const q = useQuery({
    queryKey: ['congress', 'ptr', filing.year, filing.doc_id],
    queryFn: ({ signal }) =>
      api<PtrReport>(`/congress/ptrs/${encodeURIComponent(filing.doc_id)}?year=${filing.year}${filing.filed ? `&filed=${filing.filed}` : ''}`, { signal }),
    staleTime: 10 * 60_000,
    retry: false,
  })
  const d = q.data
  return (
    <section className="panel p-4 sm:p-5" aria-labelledby="ptr-h">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="eyebrow mb-1">PTR {filing.doc_id}</p>
          <h2 id="ptr-h" className="text-lg text-fg">
            {d?.name ?? filing.name} <span className="text-sm text-muted">· {d?.district ?? filing.district}</span>
          </h2>
          <p className="num mt-1 text-xs text-muted">
            Documento de {shortDate(d?.filed ?? filing.filed)}
            {d && <> · coletado em {localDateTime(d.collected_at)}</>}
          </p>
        </div>
        <a
          href={d?.pdf_url ?? filing.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-md)] border border-line-strong px-3 text-[13px] text-fg hover:border-ember hover:text-ember"
        >
          PDF na House Clerk <ExternalLink className="size-3.5" aria-hidden />
        </a>
      </div>
      {q.isLoading ? (
        <Skeleton className="h-40" />
      ) : q.error ? (
        <ErrorState error={q.error} retry={() => void q.refetch()} />
      ) : d && !d.readable ? (
        <Notice tone="caution">{d.note}</Notice>
      ) : d ? (
        <>
          <DataTable
            rows={d.rows ?? []}
            columns={rowColumns}
            rowKey={(r) => `${r.date}-${r.type}-${r.ticker ?? r.asset}-${r.amount}-${r.owner}-${r.description ?? ''}`}
            caption={`Operações declaradas no PTR ${d.doc_id}`}
            minWidth={940}
            empty={<Notice tone="caution">{d.note ?? 'Nenhuma operação reconhecida no PDF; confira o documento.'}</Notice>}
          />
          <p className="mt-3 text-[11px] text-faint">
            Datas: operação = quando a operação aconteceu; documento = quando o relatório foi entregue à Câmara; coleta = quando o laboratório baixou o arquivo. Valores em faixas, como no formulário.
          </p>
        </>
      ) : null}
    </section>
  )
}

const filingColumns = (open: (f: PtrFiling) => void): Column<PtrFiling>[] => [
  {
    key: 'name',
    header: 'Parlamentar',
    cell: (f) => (
      <span>
        <span className="text-fg">{f.name}</span> <span className="text-faint">· {f.district}</span>
      </span>
    ),
    sort: (f) => f.last,
  },
  {
    key: 'doc',
    header: 'Documento',
    cell: (f) => (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          open(f)
        }}
        className="num text-fg underline-offset-2 hover:text-ember hover:underline"
        aria-label={`Ver as operações do PTR ${f.doc_id}`}
      >
        {f.doc_id}
      </button>
    ),
    sort: (f) => f.doc_id,
  },
  { key: 'filed', header: 'Data do documento', cell: (f) => <span className="num">{shortDate(f.filed)}</span>, sort: (f) => f.filed },
  {
    key: 'pdf',
    header: 'PDF',
    cell: (f) => (
      <a href={f.url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="inline-flex items-center gap-1 text-muted hover:text-ember">
        abrir <ExternalLink className="size-3" aria-hidden />
      </a>
    ),
  },
]

export default function Congress() {
  const policy = useDisplayPolicy()
  const shown = policy ? (policy.pelosi_shown ?? (policy.mode !== 'public' || policy.pelosi_public)) : null
  const [form, setForm] = useState({ year: String(thisYear), member: 'pelosi', since: '' })
  const [params, setParams] = useState(form)
  const [selected, setSelected] = useState<PtrFiling | null>(null)

  const qs = new URLSearchParams({ year: params.year, limit: '200' })
  if (params.member.trim()) qs.set('member', params.member.trim())
  if (params.since) qs.set('since', params.since)
  const list = useQuery({
    queryKey: ['congress', 'ptrs', params],
    queryFn: ({ signal }) => api<PtrIndex>(`/congress/ptrs?${qs.toString()}`, { signal }),
    enabled: shown === true,
    staleTime: 10 * 60_000,
    retry: false,
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    setSelected(null)
    setParams(form)
  }

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        eyebrow="Pesquisa"
        title="Congresso"
        description="Relatórios periódicos de transações (PTRs) de parlamentares da Câmara dos EUA, lidos dos arquivos públicos da House Clerk."
      />

      {policy == null ? (
        <Skeleton className="h-28" />
      ) : !shown ? (
        <div className="space-y-3">
          <Notice tone="caution">
            As operações de parlamentares não são exibidas neste laboratório público até o parecer jurídico sobre o uso comercial (5 U.S.C. §13107(c)). A decisão é do servidor e vale
            para todos os visitantes.
          </Notice>
          <p className="text-sm text-muted">
            Os documentos originais estão no site oficial da{' '}
            <a href="https://disclosures-clerk.house.gov/FinancialDisclosure" target="_blank" rel="noopener noreferrer" className="text-fg hover:text-ember">
              House Clerk (Financial Disclosure)
            </a>
            .
          </p>
          <SenateNotice />
        </div>
      ) : (
        <div className="space-y-5">
          <form onSubmit={submit} className="panel grid gap-3 p-4 sm:grid-cols-[120px_1fr_180px_auto] sm:items-start">
            <Field label="Ano">
              {(p) => (
                <Select {...p} value={form.year} onChange={(e) => setForm({ ...form, year: e.target.value })}>
                  {YEARS.map((y) => (
                    <option key={y} value={y}>
                      {y}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Parlamentar" hint="Sobrenome ou “Nome Sobrenome”; vazio = todos">
              {(p) => <Input {...p} value={form.member} maxLength={60} placeholder="pelosi" onChange={(e) => setForm({ ...form, member: e.target.value })} />}
            </Field>
            <Field label="Documentos desde">
              {(p) => <Input {...p} type="date" value={form.since} onChange={(e) => setForm({ ...form, since: e.target.value })} />}
            </Field>
            <Button type="submit" className="sm:mt-[26px]">
              <Search className="size-4" aria-hidden /> Buscar
            </Button>
          </form>

          {policy.mode === 'public' && (
            <Notice tone="caution">Exibição liberada no laboratório público pela configuração do servidor (DP_PELOSI_PUBLIC).</Notice>
          )}

          <section className="panel p-4 sm:p-5" aria-labelledby="ptrs-h">
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h2 id="ptrs-h" className="text-base text-fg">
                PTRs de {params.year}
                {list.data && <span className="ml-2 text-sm text-muted">{fmt.int(list.data.total)} documento(s)</span>}
              </h2>
              {list.data && (
                <p className="num text-[11px] text-faint">
                  Índice coletado em {localDateTime(list.data.collected_at)}
                  {list.data.from_cache ? ' (cache de até 6 h)' : ''}
                </p>
              )}
            </div>
            {list.isLoading ? (
              <Skeleton className="h-40" />
            ) : list.error ? (
              <ErrorState error={list.error} retry={() => void list.refetch()} />
            ) : list.data ? (
              <>
                <DataTable
                  rows={list.data.filings}
                  columns={filingColumns(setSelected)}
                  rowKey={(f) => f.doc_id}
                  caption={`PTRs da Câmara em ${list.data.year}`}
                  onRowClick={setSelected}
                  selectedKey={selected?.doc_id ?? null}
                  initialSort={{ key: 'filed', dir: 'desc' }}
                  empty={<EmptyState title="Nenhum PTR encontrado">Mude o ano, o nome ou a data inicial.</EmptyState>}
                />
                {list.data.filings.length > 0 && !selected && <p className="mt-2 text-xs text-muted">Escolha um documento para ver as operações declaradas.</p>}
                {list.data.total > list.data.filings.length && (
                  <p className="mt-2 text-xs text-faint">Mostrando {list.data.filings.length} de {fmt.int(list.data.total)}. Refine a busca para ver os demais.</p>
                )}
              </>
            ) : null}
          </section>

          {selected && <Report key={`${selected.year}-${selected.doc_id}`} filing={selected} />}

          <SenateNotice senate={list.data?.senate} />
          <p className="text-[11px] text-faint">
            Fonte: Office of the Clerk, U.S. House of Representatives · {list.data?.source ?? 'House Clerk'}.{' '}
            {list.data?.disclaimer ?? 'Divulgação pública obrigatória (STOCK Act), feita dias ou semanas depois da operação e com valores em faixas. Não é informação privilegiada nem recomendação.'}
          </p>
        </div>
      )}
    </div>
  )
}
