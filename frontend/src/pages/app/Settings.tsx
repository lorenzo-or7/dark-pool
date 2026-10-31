import { useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { PageHeader } from '@/components/app/AppShell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field, Input, Select } from '@/components/ui/field'
import { ErrorState, Notice, Skeleton } from '@/components/ui/states'
import { api } from '@/lib/api'
import { localDateTime, shortDate } from '@/lib/format'
import { loadPrefs, savePrefs, type Prefs } from '@/lib/prefs'

type DataSource = {
  id?: string
  name: string
  use: string
  status: string
  tone?: 'up' | 'caution' | 'down'
  kind?: 'official' | 'unofficial' | 'library' | 'commercial'
  delay?: string
  terms_url?: string | null
  published_limit?: string
  usage?: { minute: number; per_minute: number | null; today: number; per_day: number | null }
  last_fetch: string | null
}

type DisplayPolicy = {
  shared: boolean
  show_raw_prices: boolean
  show_trigger_prices: boolean
  pelosi_public: boolean
  allow_unofficial_sources: boolean
  note: string | null
}

const KIND_LABEL: Record<string, string> = { official: 'oficial', unofficial: 'não oficial', library: 'cálculo local', commercial: 'comercial' }

function PolicyRow({ label, on, detail }: { label: string; on: boolean; detail: string }) {
  return (
    <li className="flex flex-col gap-1 px-3 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="text-fg">{label}</p>
        <p className="text-xs text-muted">{detail}</p>
      </div>
      <Badge tone={on ? 'up' : 'caution'} className="self-start sm:self-auto">{on ? 'exibido' : 'oculto'}</Badge>
    </li>
  )
}

type Ws = {
  workspace: { id: string; name: string; is_demo: boolean; created_at: string }
  shared?: boolean
  data_sources: DataSource[]
  display_policy?: DisplayPolicy
  intraday_provider?: { setting: string; provider: string; feed?: string | null; daily_provider: string }
  version: { app: string; engine: string; mode: string; database: string }
}

function Section({ id, title, description, children }: { id: string; title: string; description?: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-h`} className="grid gap-4 border-t border-line py-8 md:grid-cols-[260px_1fr]">
      <div>
        <h2 id={`${id}-h`} className="text-base font-medium text-fg">
          {title}
        </h2>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  )
}

/** Numbers typed by hand: keep them inside the ranges the lab accepts. */
function clean(p: Prefs): Prefs {
  const n = (v: number, lo: number, hi: number, d: number) => (Number.isFinite(v) ? Math.min(hi, Math.max(lo, Math.round(v))) : d)
  return {
    ...p,
    default_min_price: n(p.default_min_price, 0, 100000, 5),
    default_min_volume: n(p.default_min_volume, 0, 10 ** 10, 1_000_000),
    default_replays: n(p.default_replays, 100, 50000, 10000),
    default_seed: n(p.default_seed, 0, 2 ** 31 - 1, 19),
  }
}

export default function Settings() {
  const ws = useQuery({ queryKey: ['workspace'], queryFn: ({ signal }) => api<Ws>('/workspace', { signal }) })
  const [p, setP] = useState<Prefs>(loadPrefs)
  const [saved, setSaved] = useState<null | boolean>(null)

  return (
    <div className="mx-auto max-w-[1000px]">
      <PageHeader eyebrow="Laboratório" title="Configurações" />

      <Section id="preferencias" title="Preferências" description="Interface e valores padrão. Ficam salvas só neste navegador; não alteram nada para os outros visitantes.">
        <form
          className="grid max-w-xl gap-3 sm:grid-cols-2"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            setSaved(savePrefs(clean(p)))
          }}
        >
          <Field label="Densidade da interface">
            {(fp) => (
              <Select {...fp} value={p.density} onChange={(e) => setP({ ...p, density: e.target.value as Prefs['density'] })}>
                <option value="comfortable">Confortável</option>
                <option value="compact">Compacta</option>
              </Select>
            )}
          </Field>
          <Field label="Reduzir animações" hint="O sistema operacional também é respeitado.">
            {(fp) => (
              <Select {...fp} value={String(p.reduced_motion)} onChange={(e) => setP({ ...p, reduced_motion: e.target.value === 'true' })}>
                <option value="false">Seguir o sistema</option>
                <option value="true">Sempre reduzir</option>
              </Select>
            )}
          </Field>
          <Field label="Preço mínimo padrão no scanner (US$)">
            {(fp) => <Input {...fp} type="number" min={0} value={p.default_min_price} onChange={(e) => setP({ ...p, default_min_price: e.target.valueAsNumber })} />}
          </Field>
          <Field label="Volume mínimo padrão">
            {(fp) => <Input {...fp} type="number" min={0} step={100000} value={p.default_min_volume} onChange={(e) => setP({ ...p, default_min_volume: e.target.valueAsNumber })} />}
          </Field>
          <Field label="Replays padrão no Time Machine">
            {(fp) => <Input {...fp} type="number" min={100} max={50000} step={1000} value={p.default_replays} onChange={(e) => setP({ ...p, default_replays: e.target.valueAsNumber })} />}
          </Field>
          <Field label="Seed padrão">{(fp) => <Input {...fp} type="number" min={0} value={p.default_seed} onChange={(e) => setP({ ...p, default_seed: e.target.valueAsNumber })} />}</Field>
          <div className="flex items-center gap-3 sm:col-span-2">
            <Button type="submit">Salvar preferências</Button>
            {saved === true && <p className="text-sm text-up">Salvas neste navegador.</p>}
            {saved === false && <p role="alert" className="text-sm text-down">Este navegador não permite salvar preferências.</p>}
          </div>
        </form>
      </Section>

      <Section id="workspace" title="Laboratório compartilhado" description="Quem abre o link usa o mesmo laboratório: estratégias, experimentos, varreduras, simulações, watchlists e o diário.">
        {ws.isLoading ? (
          <Skeleton className="h-24" />
        ) : ws.isError ? (
          <ErrorState error={ws.error} />
        ) : (
          <>
            <p className="text-sm text-fg">
              {ws.data?.workspace.name} {ws.data?.workspace.is_demo && <Badge tone="caution">demonstração</Badge>}
            </p>
            <p className="text-xs text-faint">criado em {shortDate(ws.data?.workspace.created_at)}</p>
            <Notice tone="caution" className="mt-4">
              Não há contas nem login. Tudo o que você cria ou exclui aqui aparece para todos os visitantes. Nenhuma ordem real é enviada.
            </Notice>
          </>
        )}
      </Section>

      <Section
        id="politica"
        title="Política de exibição"
        description="Configuração compartilhada, definida no servidor. Vale para todos os visitantes e não muda por navegador."
      >
        {ws.data?.display_policy ? (
          <>
            <ul className="divide-y divide-line rounded-[var(--radius-md)] border border-line">
              <PolicyRow label="Preços e candles brutos" on={ws.data.display_policy.show_raw_prices} detail="Cotações, gráficos de candles e séries de preço." />
              <PolicyRow label="Preço do gatilho nos sinais" on={ws.data.display_policy.show_trigger_prices} detail="Aguarda confirmação por escrito do provedor de dados." />
              <PolicyRow label="Divulgações do Congresso (Pelosi)" on={ws.data.display_policy.pelosi_public} detail="Aguarda parecer jurídico sobre a 5 U.S.C. §13107." />
              <PolicyRow label="Fontes não oficiais (Yahoo)" on={ws.data.display_policy.allow_unofficial_sources} detail="Os termos do Yahoo não permitem coleta automatizada em site público." />
            </ul>
            {ws.data.display_policy.note && <p className="mt-2 text-xs text-faint">{ws.data.display_policy.note}</p>}
          </>
        ) : ws.isLoading ? (
          <Skeleton className="h-24" />
        ) : null}
      </Section>

      <Section id="fontes" title="Fontes de dados" description="Origem de cada número usado no laboratório, estado atual e uso da cota compartilhada.">
        <ul className="divide-y divide-line rounded-[var(--radius-md)] border border-line">
          {(ws.data?.data_sources ?? []).map((d) => (
            <li key={d.id ?? d.name} className="flex flex-col gap-1 px-3 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <p className="text-fg">
                  {d.name} {d.kind && <span className="text-xs text-faint">· {KIND_LABEL[d.kind] ?? d.kind}</span>}
                </p>
                <p className="text-xs text-muted">{d.use}</p>
                {d.delay && <p className="text-[11px] text-faint">{d.delay}</p>}
                {d.terms_url && (
                  <a href={d.terms_url} target="_blank" rel="noreferrer" className="text-[11px] text-faint underline hover:text-ember">
                    termos de uso
                  </a>
                )}
              </div>
              <div className="shrink-0 text-left sm:text-right">
                <Badge tone={d.tone ?? (d.status.startsWith('requer') || d.status.startsWith('não') ? 'caution' : 'up')}>{d.status}</Badge>
                {d.usage && (d.usage.per_minute != null || d.usage.per_day != null) && (
                  <p className="num mt-1 text-[11px] text-faint">
                    {d.usage.per_minute != null && `${d.usage.minute}/${d.usage.per_minute} por min`}
                    {d.usage.per_minute != null && d.usage.per_day != null && ' · '}
                    {d.usage.per_day != null && `${d.usage.today}/${d.usage.per_day} hoje`}
                  </p>
                )}
                <p className="mt-1 text-[11px] text-faint">{d.last_fetch ? `última coleta ${localDateTime(d.last_fetch)}` : 'sem coleta registrada'}</p>
              </div>
            </li>
          ))}
        </ul>
        {ws.data?.intraday_provider && (
          <p className="mt-2 text-xs text-muted">
            Candles de 5 min (Time Machine, backtests ORB e plano ORB): {ws.data.intraday_provider.provider === 'alpaca'
              ? `Alpaca, feed ${ws.data.intraday_provider.feed === 'iex' ? 'IEX (uma bolsa)' : 'SIP (consolidado, mais de 15 min)'}`
              : 'Yahoo'}
            {ws.data.intraday_provider.setting === 'auto' ? ' (automático)' : ' (fixado no servidor)'}. Candles diários: Yahoo. Sem troca automática de fonte em caso de falha.
          </p>
        )}
        <p className="mt-2 text-xs text-faint">Cotações gratuitas têm atraso e não são tempo real. As cotas são compartilhadas por todos os visitantes e voltam a zero quando o servidor reinicia.</p>
      </Section>

      <Section id="versao" title="Versão">
        <dl className="grid max-w-md grid-cols-[140px_1fr] gap-y-1.5 text-sm">
          <dt className="text-muted">DARK POOL</dt>
          <dd className="num text-fg">{ws.data?.version.app}</dd>
          <dt className="text-muted">Motores</dt>
          <dd className="num text-fg">{ws.data?.version.engine} (sem trader-broker)</dd>
          <dt className="text-muted">Acesso</dt>
          <dd className="num text-fg">{ws.data?.version.mode === 'public' ? 'público, compartilhado' : ws.data?.version.mode}</dd>
          <dt className="text-muted">Banco</dt>
          <dd className="num text-fg">{ws.data?.version.database}</dd>
        </dl>
      </Section>
    </div>
  )
}
