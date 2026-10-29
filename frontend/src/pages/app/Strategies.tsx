import { useQuery } from '@tanstack/react-query'
import { FlaskConical, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/app/AppShell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input, Select } from '@/components/ui/field'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/states'
import { api } from '@/lib/api'
import { relative } from '@/lib/format'
import { RULES, ruleLabel } from '@/lib/strategy'
import type { Strategy } from '@/lib/types'

export default function Strategies() {
  const [q, setQ] = useState('')
  const [rule, setRule] = useState('all')
  const [archived, setArchived] = useState(false)
  const list = useQuery({ queryKey: ['strategies', archived], queryFn: ({ signal }) => api<Strategy[]>(`/strategies?archived=${archived}`, { signal }) })
  const rows = useMemo(
    () =>
      (list.data ?? []).filter(
        (s) => (rule === 'all' || s.rule_type === rule) && (!q.trim() || `${s.name} ${s.symbol} ${s.description}`.toLowerCase().includes(q.trim().toLowerCase())),
      ),
    [list.data, q, rule],
  )
  return (
    <div className="mx-auto max-w-[1200px]">
      <PageHeader eyebrow="Pesquisa" title="Strategy Lab" description="Regras de entrada, saída e risco, com versões. Escolha uma estratégia para rodar um backtest ou abrir no Time Machine.">
        <Button asChild variant="primary">
          <Link to="/app/strategies/new">
            <FlaskConical /> Nova estratégia
          </Link>
        </Button>
      </PageHeader>
      <div className="mb-4 flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint" aria-hidden />
          <label htmlFor="st-q" className="sr-only">
            Buscar estratégia
          </label>
          <Input id="st-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar por nome, ativo ou descrição" className="pl-9" />
        </div>
        <Select aria-label="Filtrar por regra" value={rule} onChange={(e) => setRule(e.target.value)} className="sm:w-72">
          <option value="all">Todas as regras</option>
          {RULES.map((r) => (
            <option key={r.type} value={r.type}>
              {r.label}
            </option>
          ))}
        </Select>
        <Select aria-label="Situação" value={String(archived)} onChange={(e) => setArchived(e.target.value === 'true')} className="sm:w-40">
          <option value="false">Ativas</option>
          <option value="true">Arquivadas</option>
        </Select>
      </div>
      {list.isLoading ? (
        <div className="grid gap-3 md:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : list.isError ? (
        <ErrorState error={list.error} retry={() => void list.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState
          title={list.data?.length ? 'Nenhuma estratégia com esses filtros' : 'Nenhuma estratégia ainda'}
          action={
            !list.data?.length && (
              <Button asChild size="sm" variant="primary">
                <Link to="/app/strategies/new">Criar a primeira</Link>
              </Button>
            )
          }
        >
          {list.data?.length ? 'Limpe a busca ou troque o filtro de regra.' : 'Uma estratégia descreve a regra que você quer testar.'}
        </EmptyState>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {rows.map((s) => (
            <li key={s.id}>
              <Link to={`/app/strategies/${s.id}`} className="panel group flex h-full flex-col gap-3 p-4 transition-colors hover:border-line-strong">
                <div className="flex items-start justify-between gap-3">
                  <h2 className="text-[15px] font-medium text-fg group-hover:text-ember">{s.name}</h2>
                  <span className="num shrink-0 text-xs text-muted">v{s.current_version}</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {s.symbol && <Badge tone="neutral">{s.symbol}</Badge>}
                  <Badge tone="ember">{ruleLabel(s.rule_type)}</Badge>
                  {s.is_demo && <Badge tone="caution">Demonstração</Badge>}
                </div>
                {s.description && <p className="line-clamp-2 text-sm text-muted">{s.description}</p>}
                <p className="mt-auto text-xs text-faint">
                  {s.experiments ?? 0} experimentos · atualizada {relative(s.updated_at)}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
