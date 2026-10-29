import { EclipseMark } from '@/brand/EclipseMark'
import { FeatureBento } from '@/components/landing/FeatureBento'
import { Footer } from '@/components/landing/Footer'
import { IslandNavbar } from '@/components/landing/IslandNavbar'
import { LabPreview } from '@/components/landing/LabPreview'
import { SpotlightCards } from '@/components/landing/SpotlightCards'
import { WovenLightHero } from '@/components/landing/WovenLightHero'
import AnimatedContent from '@/components/reactbits/AnimatedContent'
import { InteractiveHoverLink } from '@/components/ui/interactive-hover-button'

const steps = [
  { n: '01', t: 'Observar', d: 'Varrer o mercado e registrar o que chama atenção, com a data, a fonte e o atraso da cotação.' },
  { n: '02', t: 'Formular hipóteses', d: 'Escrever a regra antes de olhar o resultado: entrada, saída, stop, alvo e limite de risco.' },
  { n: '03', t: 'Testar', d: 'Rodar a regra sobre dados históricos congelados e simular o resto da sessão milhares de vezes.' },
  { n: '04', t: 'Medir', d: 'Ler a taxa de acerto com o intervalo de confiança, a expectativa em R e o drawdown, separando dados de desenvolvimento e fora da amostra.' },
  { n: '05', t: 'Aprender', d: 'Registrar no diário o que funcionou, o que falhou e por quê. Ajustar a hipótese e voltar ao passo 01.' },
]

function Section({ id, eyebrow, title, children, className = '' }: { id?: string; eyebrow: string; title: string; children: React.ReactNode; className?: string }) {
  return (
    <section id={id} className={`scroll-mt-24 px-4 py-24 sm:px-6 sm:py-32 ${className}`}>
      <div className="mx-auto max-w-7xl">
        <AnimatedContent distance={28} duration={0.9} threshold={0.15}>
          <p className="eyebrow flex items-center gap-3">
            <span className="h-px w-8 bg-ember" aria-hidden />
            {eyebrow}
          </p>
          <h2 className="mt-5 max-w-3xl text-3xl leading-[1.1] font-medium text-fg sm:text-[44px]">{title}</h2>
        </AnimatedContent>
        <div className="mt-12 sm:mt-16">{children}</div>
      </div>
    </section>
  )
}

/** publicOnly: the static GitHub Pages build. No login, no lab links, no backend calls. */
export default function Landing({ authed = false, publicOnly = false }: { authed?: boolean; publicOnly?: boolean }) {
  const enter = publicOnly ? '#acesso' : authed ? '/app' : '/login'

  return (
    <div className="min-h-screen bg-ink">
      <a href="#conteudo" className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded focus:bg-ember focus:px-3 focus:py-2 focus:text-ember-ink">
        Pular para o conteúdo
      </a>
      <IslandNavbar enterTo={enter} enterLabel={publicOnly ? 'Acesso privado' : authed ? 'Abrir laboratório' : 'Entrar'} />
      <main id="conteudo">
        <WovenLightHero sub="Explore o mercado além dos gráficos. Pesquise estratégias, simule cenários e transforme dados em conhecimento.">
          <InteractiveHoverLink to={enter}>{publicOnly ? 'Acesso por convite' : 'Acessar laboratório'}</InteractiveHoverLink>
          <InteractiveHoverLink to="#funcionalidades" tone="ghost">
            Explorar funcionalidades
          </InteractiveHoverLink>
        </WovenLightHero>

        <Section id="plataforma" eyebrow="Plataforma" title="Um laboratório para testar ideias sobre o mercado antes de acreditar nelas.">
          <div className="grid gap-12 lg:grid-cols-[1.1fr_1fr] lg:gap-20">
            <AnimatedContent distance={24} delay={0.05}>
              <div className="space-y-5 text-[17px] leading-relaxed text-fg/85">
                <p>
                  O DARK POOL reúne em um só lugar o que normalmente fica espalhado em planilhas e abas do navegador: a varredura de ativos, a
                  definição das regras, os testes históricos, as simulações e as anotações de quem está pesquisando.
                </p>
                <p className="text-muted">
                  Nenhum resultado aqui é promessa. Um backtest mostra o que uma regra teria feito em um período; uma simulação mostra a
                  dispersão de caminhos possíveis com base no comportamento recente do ativo. Os dois ajudam a descartar hipóteses fracas,
                  e nenhum dos dois prevê o próximo pregão.
                </p>
              </div>
            </AnimatedContent>
            <AnimatedContent distance={24} delay={0.12}>
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius-lg)] border border-line bg-line">
                {[
                  ['5.942', 'ações listadas nos EUA no universo do scanner', 'Nasdaq Trader, out/2026'],
                  ['60 dias', 'de candles de 5 minutos por simulação', 'janela máxima da fonte gratuita'],
                  ['2', 'pesquisadores no mesmo workspace', 'acesso por convite'],
                  ['0', 'ordens enviadas a corretoras', 'por definição do projeto'],
                ].map(([v, l, s]) => (
                  <div key={l} className="bg-surface p-5 sm:p-6">
                    <dt className="sr-only">{l}</dt>
                    <dd className="num text-2xl text-fg sm:text-3xl">{v}</dd>
                    <dd className="mt-2 text-sm text-fg/80">{l}</dd>
                    <dd className="mt-1 text-xs text-faint">{s}</dd>
                  </div>
                ))}
              </dl>
            </AnimatedContent>
          </div>
        </Section>

        <Section id="funcionalidades" eyebrow="Funcionalidades" title="Cinco ferramentas, um fluxo de pesquisa." className="border-t border-line">
          <AnimatedContent distance={30}>
            <FeatureBento />
          </AnimatedContent>
          <div className="mt-20">
            <AnimatedContent distance={24}>
              <p className="eyebrow mb-6">Princípios do laboratório</p>
              <SpotlightCards />
            </AnimatedContent>
          </div>
        </Section>

        <Section eyebrow="Prévia do laboratório" title="O Time Machine, com uma execução de verdade." className="border-t border-line">
          <AnimatedContent distance={40} duration={1}>
            <LabPreview />
          </AnimatedContent>
        </Section>

        <Section id="metodologia" eyebrow="Metodologia" title="Observar, formular, testar, medir, aprender." className="border-t border-line">
          <ol className="grid gap-px overflow-hidden rounded-[var(--radius-lg)] border border-line bg-line md:grid-cols-5">
            {steps.map((s, i) => (
              <li key={s.n} className="bg-ink p-6">
                <AnimatedContent distance={20} delay={i * 0.06}>
                  <span className="num text-sm text-ember">{s.n}</span>
                  <h3 className="mt-6 text-lg font-medium text-fg">{s.t}</h3>
                  <p className="mt-3 text-sm leading-relaxed text-muted">{s.d}</p>
                </AnimatedContent>
              </li>
            ))}
          </ol>
          <p className="mt-8 max-w-3xl border-l-2 border-ember pl-5 text-[15px] leading-relaxed text-fg/85">
            Simulações não são previsões de mercado. Elas reamostram o passado recente do próprio ativo; resultados, notícias e suspensões
            podem produzir movimentos que esse passado nunca mostrou.
          </p>
        </Section>

        <section id="acesso" className="relative scroll-mt-24 overflow-hidden border-t border-line px-4 py-28 sm:px-6 sm:py-36">
          <EclipseMark className="pointer-events-none absolute top-1/2 left-1/2 size-[min(120vw,900px)] -translate-x-1/2 -translate-y-1/2 opacity-30" flare={false} title="" weight={0.35} />
          <div className="relative mx-auto flex max-w-3xl flex-col items-center text-center">
            <AnimatedContent distance={24}>
              <p className="eyebrow">Acesso privado</p>
              <h2 className="mt-5 text-3xl leading-tight font-medium text-fg sm:text-5xl">{publicOnly ? 'Um laboratório privado.' : 'Entre no laboratório.'}</h2>
              <p className="mx-auto mt-5 max-w-lg text-muted">
                {publicOnly
                  ? 'O DARK POOL é usado por convite, no ambiente dos membros do projeto. Esta página apresenta a proposta e a metodologia; o laboratório não fica aberto ao público.'
                  : 'O acesso é feito por convite. Se você faz parte do projeto, use o e-mail cadastrado.'}
              </p>
              {!publicOnly && (
                <div className="mt-9 flex justify-center">
                  <InteractiveHoverLink to={enter}>Acessar laboratório</InteractiveHoverLink>
                </div>
              )}
            </AnimatedContent>
          </div>
        </section>
      </main>
      <Footer publicOnly={publicOnly} />
    </div>
  )
}
