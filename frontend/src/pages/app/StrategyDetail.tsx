import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, Copy, Pencil, Play, Rewind, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { PageHeader } from '@/components/app/AppShell'
import { JobProgress } from '@/components/app/JobProgress'
import { Badge, DataBadge, StatusBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmDialog, Dialog } from '@/components/ui/dialog'
import { Field, Input, Select } from '@/components/ui/field'
import { ErrorState, Notice, Skeleton } from '@/components/ui/states'
import { api } from '@/lib/api'
import { intradayLabel, useIntradayProvider } from '@/lib/intraday'
import { localDateTime, relative, shortDate } from '@/lib/format'
import { describe, diffConfig, ruleLabel } from '@/lib/strategy'
import type { Experiment, Job, Snapshot, Strategy } from '@/lib/types'

function BacktestDialog({ s, open, onOpenChange }: { s: Strategy; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient()
  const orb = s.rule_type === 'orb'
  const [range, setRange] = useState<'1y' | '2y' | '5y'>('2y')
  const [snap, setSnap] = useState('')
  const [split, setSplit] = useState('')
  const [sessions, setSessions] = useState(60)
  const intraday = useIntradayProvider()
  const [job, setJob] = useState<{ id: string; exp: string } | null>(null)
  const snaps = useQuery({
    queryKey: ['snapshots', s.symbol, orb ? '5m' : '1d'],
    queryFn: ({ signal }) => api<Snapshot[]>(`/snapshots?symbol=${s.symbol}&interval=${orb ? '5m' : '1d'}`, { signal }),
    enabled: open,
  })
  const run = useMutation({
    mutationFn: () =>
      api<{ job: Job; experiment_id: string }>('/backtests', {
        body: { strategy_id: s.id, range, snapshot_id: snap || null, split_date: split || null, ...(orb ? { history_sessions: Math.min(250, Math.max(20, Math.round(sessions) || 60)) } : {}) },
      }),
    onSuccess: (r) => setJob({ id: r.job.id, exp: r.experiment_id }),
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Rodar backtest" description={`${s.name} · versão ${s.current_version}`}>
      <div className="space-y-4">
        <Field label="Dados" hint="Um download novo é congelado como snapshot com hash, para a execução poder ser repetida.">
          {(p) => (
            <Select {...p} value={snap} onChange={(e) => setSnap(e.target.value)}>
              <option value="">{orb ? intradayLabel(intraday, sessions) : `Baixar agora (${range} de candles diários, Yahoo)`}</option>
              {(snaps.data ?? []).map((x) => (
                <option key={x.id} value={x.id}>
                  Snapshot {x.is_fixture ? 'de referência' : ''} {x.range}/{x.interval} · {localDateTime(x.fetched_at)} · {x.sha256.slice(0, 10)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        {orb && !snap && intraday?.provider === 'alpaca' && (
          <Field label="Sessões de histórico" hint="Últimas sessões encerradas da NYSE (20 a 250). Sessões com lacunas no IEX ficam de fora.">
            {(p) => (
              <Input {...p} type="number" min={20} max={250} value={sessions} onChange={(e) => setSessions(Number(e.target.value))} />
            )}
          </Field>
        )}
        {!orb && !snap && (
          <Field label="Período">
            {(p) => (
              <Select {...p} value={range} onChange={(e) => setRange(e.target.value as typeof range)}>
                <option value="1y">1 ano</option>
                <option value="2y">2 anos</option>
                <option value="5y">5 anos (candles semanais não são usados; diários até onde houver)</option>
              </Select>
            )}
          </Field>
        )}
        <Field label="Separar fora da amostra a partir de (opcional)" hint="Operações antes desta data contam como desenvolvimento; a partir dela, fora da amostra.">
          {(p) => <Input {...p} type="date" value={split} onChange={(e) => setSplit(e.target.value)} />}
        </Field>
        {run.isError && <ErrorState error={run.error} />}
        {job ? (
          <>
            <JobProgress
              jobId={job.id}
              label="Backtest"
              onDone={() => {
                void qc.invalidateQueries({ queryKey: ['strategy', s.id] })
                void qc.invalidateQueries({ queryKey: ['dashboard'] })
              }}
            />
            <Button asChild variant="primary" className="w-full">
              <Link to={`/app/analytics?exp=${job.exp}`}>Ver resultado em Analytics</Link>
            </Button>
          </>
        ) : (
          <Button variant="primary" className="w-full" onClick={() => run.mutate()} disabled={run.isPending}>
            <Play /> Iniciar
          </Button>
        )}
      </div>
    </Dialog>
  )
}

export default function StrategyDetail() {
  const { id } = useParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['strategy', id], queryFn: ({ signal }) => api<Strategy & { experiments: Experiment[] }>(`/strategies/${id}`, { signal }) })
  const [bt, setBt] = useState(false)
  const [del, setDel] = useState(false)
  const [cmp, setCmp] = useState<[number, number] | null>(null)
  const inv = () => {
    void qc.invalidateQueries({ queryKey: ['strategies'] })
    void qc.invalidateQueries({ queryKey: ['strategy', id] })
  }
  const dup = useMutation({ mutationFn: () => api<Strategy>(`/strategies/${id}/duplicate`, { method: 'POST' }), onSuccess: (s) => (inv(), nav(`/app/strategies/${s.id}`)) })
  const arch = useMutation({ mutationFn: (v: boolean) => api(`/strategies/${id}`, { method: 'PATCH', body: { archived: v } }), onSuccess: inv })
  const remove = useMutation({ mutationFn: () => api(`/strategies/${id}`, { method: 'DELETE' }), onSuccess: () => (inv(), nav('/app/strategies')) })

  if (q.isLoading) return <Skeleton className="mx-auto h-96 max-w-[1100px]" />
  if (q.isError || !q.data) return <ErrorState error={q.error} />
  const s = q.data
  const versions = s.versions ?? []
  const cur = versions.find((v) => v.version === s.current_version)
  const cfg = cur?.config
  const pair = cmp ?? (versions.length > 1 ? [versions[1].version, versions[0].version] : null)
  const diff = pair && versions.length > 1 ? diffConfig(versions.find((v) => v.version === pair[0])!.config, versions.find((v) => v.version === pair[1])!.config) : []
  const tmLink = cfg ? `/app/time-machine?symbol=${cfg.symbol}&or=${cfg.rule.params.or_minutes ?? 15}&strategy=${s.id}${cfg.exit.flat_by ? `&until=${cfg.exit.flat_by}` : ''}` : '/app/time-machine'

  return (
    <div className="mx-auto max-w-[1100px]">
      <PageHeader eyebrow="Strategy Lab" title={s.name} description={s.description}>
        <Button variant="primary" onClick={() => setBt(true)}>
          <Play /> Rodar backtest
        </Button>
        {s.rule_type === 'orb' && (
          <Button asChild>
            <Link to={tmLink}>
              <Rewind /> Enviar ao Time Machine
            </Link>
          </Button>
        )}
        <Button asChild variant="ghost">
          <Link to={`/app/strategies/${s.id}/edit`}>
            <Pencil /> Editar
          </Link>
        </Button>
        <Button variant="ghost" onClick={() => dup.mutate()} disabled={dup.isPending}>
          <Copy /> Duplicar
        </Button>
        <Button variant="ghost" onClick={() => arch.mutate(!s.archived)}>
          <Archive /> {s.archived ? 'Restaurar' : 'Arquivar'}
        </Button>
        <Button variant="danger" size="icon" onClick={() => setDel(true)} aria-label="Excluir estratégia">
          <Trash2 />
        </Button>
      </PageHeader>
      {(dup.isError || arch.isError) && <ErrorState error={dup.error ?? arch.error} className="mb-4" />}

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <section className="panel p-5" aria-labelledby="cfg-h">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <h2 id="cfg-h" className="text-base font-medium text-fg">
              Configuração atual · v{s.current_version}
            </h2>
            <Badge tone="ember">{ruleLabel(s.rule_type)}</Badge>
            {s.is_demo && <DataBadge kind="demo" />}
          </div>
          {cfg && <p className="text-[15px] leading-relaxed text-fg/90">{describe(cfg)}</p>}
          {cfg && (
            <dl className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius-md)] border border-line bg-line sm:grid-cols-3">
              {[
                ['Capital simulado', `US$ ${cfg.risk.account_size.toLocaleString('pt-BR')}`],
                ['Perda máx./operação', `US$ ${cfg.risk.max_loss_per_trade.toLocaleString('pt-BR')}`],
                ['Posição máxima', `${cfg.risk.max_position_pct} %`],
                ['Perda diária máx.', `US$ ${cfg.risk.daily_loss_limit.toLocaleString('pt-BR')}`],
                ['Operações/dia', String(cfg.risk.max_trades_per_day)],
                ['Retorno/risco mín.', `${cfg.risk.min_reward_risk}R`],
              ].map(([l, v]) => (
                <div key={l} className="bg-surface p-3">
                  <dt className="text-[11px] text-muted">{l}</dt>
                  <dd className="num mt-0.5 text-sm text-fg">{v}</dd>
                </div>
              ))}
            </dl>
          )}
          {s.rule_type !== 'orb' && <Notice className="mt-4">O Time Machine simula planos intradiários de ORB. Estratégias diárias são avaliadas pelo backtest.</Notice>}
        </section>

        <section className="panel p-5" aria-labelledby="ver-h">
          <h2 id="ver-h" className="mb-3 text-base font-medium text-fg">
            Versões
          </h2>
          <ol className="space-y-2">
            {versions.map((v) => (
              <li key={v.id} className="flex items-start gap-3 text-sm">
                <span className="num mt-0.5 w-8 shrink-0 text-muted">v{v.version}</span>
                <div className="min-w-0">
                  <p className="text-fg">{v.note || '—'}</p>
                  <p className="text-xs text-faint">{localDateTime(v.created_at)}</p>
                </div>
              </li>
            ))}
          </ol>
          {versions.length > 1 && pair && (
            <div className="mt-5 border-t border-line pt-4">
              <p className="mb-2 text-sm text-fg">Comparar configurações</p>
              <div className="flex items-center gap-2">
                {[0, 1].map((i) => (
                  <Select key={i} aria-label={i ? 'Versão B' : 'Versão A'} value={pair[i]} onChange={(e) => setCmp(i ? [pair[0], Number(e.target.value)] : [Number(e.target.value), pair[1]])} className="h-8 text-xs">
                    {versions.map((v) => (
                      <option key={v.version} value={v.version}>
                        v{v.version}
                      </option>
                    ))}
                  </Select>
                ))}
              </div>
              {diff.length === 0 ? (
                <p className="mt-3 text-xs text-faint">Configurações idênticas.</p>
              ) : (
                <table className="mt-3 w-full text-xs">
                  <caption className="sr-only">Diferenças entre versões</caption>
                  <thead>
                    <tr className="text-left text-faint">
                      <th className="pb-1 font-normal">Campo</th>
                      <th className="pb-1 font-normal">v{pair[0]}</th>
                      <th className="pb-1 font-normal">v{pair[1]}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {diff.map((d) => (
                      <tr key={d.key} className="border-t border-line">
                        <td className="num py-1.5 pr-2 text-muted">{d.key}</td>
                        <td className="num py-1.5 pr-2 text-down">{String(d.a ?? '—')}</td>
                        <td className="num py-1.5 text-up">{String(d.b ?? '—')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </section>
      </div>

      <section className="panel mt-4 p-5" aria-labelledby="exp-h">
        <h2 id="exp-h" className="mb-3 text-base font-medium text-fg">
          Experimentos desta estratégia
        </h2>
        {s.experiments.length === 0 ? (
          <p className="text-sm text-faint">Nenhum ainda. Rode um backtest para começar.</p>
        ) : (
          <ul className="divide-y divide-line">
            {s.experiments.map((e) => (
              <li key={e.id} className="flex flex-wrap items-center gap-3 py-2.5">
                <StatusBadge status={e.status} />
                <Badge tone={e.kind === 'monte_carlo' ? 'sim' : 'neutral'}>{e.kind === 'monte_carlo' ? 'Monte Carlo' : `Backtest v${e.strategy_version}`}</Badge>
                <Link to={e.kind === 'monte_carlo' ? `/app/time-machine?exp=${e.id}` : `/app/analytics?exp=${e.id}`} className="min-w-0 flex-1 truncate text-sm text-fg hover:text-ember">
                  {e.title}
                </Link>
                <span className="text-xs text-faint">{relative(e.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <p className="mt-4 text-xs text-faint">
        Criada em {shortDate(s.created_at)} · última alteração {localDateTime(s.updated_at)}
      </p>

      {bt && <BacktestDialog s={s} open={bt} onOpenChange={setBt} />}
      <ConfirmDialog
        open={del}
        onOpenChange={setDel}
        title="Excluir estratégia?"
        description="As versões são apagadas. Experimentos já executados ficam guardados, sem o vínculo com a estratégia."
        confirmLabel="Excluir"
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </div>
  )
}
