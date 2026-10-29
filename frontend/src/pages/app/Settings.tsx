import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { useAuth } from '@/auth/AuthProvider'
import { PageHeader } from '@/components/app/AppShell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field, Input, Select } from '@/components/ui/field'
import { ErrorState, Notice, Skeleton } from '@/components/ui/states'
import { api } from '@/lib/api'
import { localDateTime, shortDate } from '@/lib/format'

type Ws = {
  workspace: { id: string; name: string; is_demo: boolean; created_at: string }
  members: { user_id: string; role: string; email: string; display_name: string; created_at: string }[]
  data_sources: { name: string; use: string; status: string; last_fetch: string | null }[]
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

export default function Settings() {
  const { me, mode, refreshMe, updatePassword } = useAuth()
  const ws = useQuery({ queryKey: ['workspace'], queryFn: ({ signal }) => api<Ws>('/workspace', { signal }) })
  const [name, setName] = useState('')
  const prefs = (me?.preferences ?? {}) as Record<string, number | string | boolean>
  const [p, setP] = useState(prefs)
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [pwMsg, setPwMsg] = useState<string | null>(null)
  useEffect(() => {
    setName(me?.display_name ?? '')
    setP((me?.preferences ?? {}) as Record<string, number | string | boolean>)
  }, [me])

  const saveProfile = useMutation({
    mutationFn: (body: Record<string, unknown>) => api('/me', { method: 'PATCH', body }),
    onSuccess: () => void refreshMe(),
  })
  const changePw = useMutation({
    mutationFn: async () => {
      if (pw.length < 10) throw new Error('Use pelo menos 10 caracteres.')
      if (pw !== pw2) throw new Error('As senhas não coincidem.')
      await updatePassword(pw)
    },
    onSuccess: () => {
      setPw('')
      setPw2('')
      setPwMsg('Senha alterada.')
    },
  })

  return (
    <div className="mx-auto max-w-[1000px]">
      <PageHeader eyebrow="Conta" title="Configurações" />

      <Section id="perfil" title="Perfil" description="Seu nome aparece como autor das estratégias, experimentos e registros.">
        <form
          className="flex max-w-md flex-col gap-3 sm:flex-row sm:items-end"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            saveProfile.mutate({ display_name: name })
          }}
        >
          <Field label="Nome de exibição" className="flex-1">
            {(fp) => <Input {...fp} value={name} onChange={(e) => setName(e.target.value)} maxLength={80} />}
          </Field>
          <Button type="submit" disabled={!name.trim() || saveProfile.isPending}>
            Salvar
          </Button>
        </form>
        <p className="mt-2 text-sm text-muted">E-mail: {me?.email}</p>
        {saveProfile.isError && <ErrorState error={saveProfile.error} className="mt-2" />}
      </Section>

      <Section id="senha" title="Senha" description="A senha é gerenciada pelo Supabase Auth.">
        {mode !== 'supabase' ? (
          <Notice tone="caution">Indisponível no modo demonstração: não existe senha neste ambiente.</Notice>
        ) : (
          <form
            className="grid max-w-md gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              setPwMsg(null)
              changePw.mutate()
            }}
            noValidate
          >
            <Field label="Nova senha">{(fp) => <Input {...fp} type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} />}</Field>
            <Field label="Repita a nova senha">{(fp) => <Input {...fp} type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} />}</Field>
            {changePw.isError && <p role="alert" className="text-sm text-down">{(changePw.error as Error).message}</p>}
            {pwMsg && <p className="text-sm text-up">{pwMsg}</p>}
            <Button type="submit" disabled={changePw.isPending} className="w-fit">
              Alterar senha
            </Button>
          </form>
        )}
      </Section>

      <Section id="preferencias" title="Preferências" description="Interface, pesquisa e simulação. Ficam salvas no seu perfil.">
        <form
          className="grid max-w-xl gap-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault()
            saveProfile.mutate({ preferences: p })
          }}
        >
          <Field label="Densidade da interface">
            {(fp) => (
              <Select {...fp} value={String(p.density ?? 'comfortable')} onChange={(e) => setP({ ...p, density: e.target.value })}>
                <option value="comfortable">Confortável</option>
                <option value="compact">Compacta</option>
              </Select>
            )}
          </Field>
          <Field label="Reduzir animações" hint="O sistema operacional também é respeitado.">
            {(fp) => (
              <Select {...fp} value={String(p.reduced_motion ?? false)} onChange={(e) => setP({ ...p, reduced_motion: e.target.value === 'true' })}>
                <option value="false">Seguir o sistema</option>
                <option value="true">Sempre reduzir</option>
              </Select>
            )}
          </Field>
          <Field label="Preço mínimo padrão no scanner (US$)">
            {(fp) => <Input {...fp} type="number" min={0} value={Number(p.default_min_price ?? 5)} onChange={(e) => setP({ ...p, default_min_price: e.target.valueAsNumber })} />}
          </Field>
          <Field label="Volume mínimo padrão">
            {(fp) => <Input {...fp} type="number" min={0} step={100000} value={Number(p.default_min_volume ?? 1000000)} onChange={(e) => setP({ ...p, default_min_volume: e.target.valueAsNumber })} />}
          </Field>
          <Field label="Replays padrão no Time Machine">
            {(fp) => <Input {...fp} type="number" min={100} max={50000} step={1000} value={Number(p.default_replays ?? 10000)} onChange={(e) => setP({ ...p, default_replays: e.target.valueAsNumber })} />}
          </Field>
          <Field label="Seed padrão">{(fp) => <Input {...fp} type="number" min={0} value={Number(p.default_seed ?? 19)} onChange={(e) => setP({ ...p, default_seed: e.target.valueAsNumber })} />}</Field>
          <div className="sm:col-span-2">
            <Button type="submit" disabled={saveProfile.isPending}>
              Salvar preferências
            </Button>
          </div>
        </form>
      </Section>

      <Section id="workspace" title="Workspace" description="Tudo é compartilhado entre os membros: estratégias, experimentos, watchlists, relatórios e o diário.">
        {ws.isLoading ? (
          <Skeleton className="h-32" />
        ) : ws.isError ? (
          <ErrorState error={ws.error} />
        ) : (
          <>
            <p className="text-sm text-fg">
              {ws.data?.workspace.name} {ws.data?.workspace.is_demo && <Badge tone="caution">demonstração</Badge>}
            </p>
            <p className="text-xs text-faint">criado em {shortDate(ws.data?.workspace.created_at)}</p>
            <ul className="mt-4 divide-y divide-line rounded-[var(--radius-md)] border border-line">
              {ws.data?.members.map((m) => (
                <li key={m.user_id} className="flex items-center justify-between gap-3 px-3 py-2.5 text-sm">
                  <div className="min-w-0">
                    <p className="truncate text-fg">{m.display_name}</p>
                    <p className="truncate text-xs text-muted">{m.email}</p>
                  </div>
                  <Badge tone={m.role === 'owner' ? 'ember' : 'neutral'}>{m.role === 'owner' ? 'Proprietário' : 'Membro'}</Badge>
                </li>
              ))}
            </ul>
          </>
        )}
      </Section>

      <Section id="acesso" title="Gerenciamento de acesso" description="Sem cadastro público. Convites só pelo proprietário, fora do navegador.">
        <div className="space-y-3 text-sm text-muted">
          <p>
            Por segurança, adicionar ou remover membros não é possível pela interface. O proprietário roda, no próprio computador, o script de convite com a chave
            de serviço do Supabase guardada em variável de ambiente:
          </p>
          <pre className="num overflow-x-auto rounded-[var(--radius-md)] bg-abyss p-3 text-[12px] text-fg/90">py -3 scripts/invite_member.py --email pessoa@exemplo.com --workspace-id {ws.data?.workspace.id ?? '<id>'} --role member</pre>
          <p>A pessoa recebe um e-mail do Supabase e define a própria senha. As permissões são aplicadas pelo banco (Row Level Security).</p>
        </div>
      </Section>

      <Section id="fontes" title="Fontes de dados" description="Origem de cada número exibido no laboratório.">
        <ul className="divide-y divide-line rounded-[var(--radius-md)] border border-line">
          {(ws.data?.data_sources ?? []).map((d) => (
            <li key={d.name} className="flex flex-col gap-1 px-3 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-fg">{d.name}</p>
                <p className="text-xs text-muted">{d.use}</p>
              </div>
              <div className="text-left sm:text-right">
                <Badge tone={d.status.startsWith('requer') || d.status.startsWith('não') ? 'caution' : 'up'}>{d.status}</Badge>
                <p className="mt-1 text-[11px] text-faint">{d.last_fetch ? `última coleta ${localDateTime(d.last_fetch)}` : 'sem coleta registrada'}</p>
              </div>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-faint">Cotações gratuitas têm atraso e não são tempo real.</p>
      </Section>

      <Section id="versao" title="Versão">
        <dl className="grid max-w-md grid-cols-[140px_1fr] gap-y-1.5 text-sm">
          <dt className="text-muted">DARK POOL</dt>
          <dd className="num text-fg">{ws.data?.version.app}</dd>
          <dt className="text-muted">Motores</dt>
          <dd className="num text-fg">{ws.data?.version.engine} (sem trader-broker)</dd>
          <dt className="text-muted">Autenticação</dt>
          <dd className="num text-fg">{ws.data?.version.mode}</dd>
          <dt className="text-muted">Banco</dt>
          <dd className="num text-fg">{ws.data?.version.database}</dd>
        </dl>
      </Section>
    </div>
  )
}
