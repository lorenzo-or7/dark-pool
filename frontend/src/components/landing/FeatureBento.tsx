/**
 * Cybernetic Bento Grid (after Dhileep Kumar; source needs a 21st.dev login):
 * mixed-size cards over a faint grid, a border that lights up under the
 * pointer on hover. Kept quiet: one accent, no permanent glow.
 */
import { Activity, BookOpenText, FlaskConical, Radar, Rewind } from 'lucide-react'
import { useRef, type PointerEvent, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

function Cell({ className, children }: { className?: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  function onMove(e: PointerEvent<HTMLDivElement>) {
    const r = ref.current?.getBoundingClientRect()
    if (!r || !ref.current) return
    ref.current.style.setProperty('--mx', `${e.clientX - r.left}px`)
    ref.current.style.setProperty('--my', `${e.clientY - r.top}px`)
  }
  return (
    <div
      ref={ref}
      onPointerMove={onMove}
      className={cn(
        'group relative overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface/80 p-6 transition-colors duration-300 hover:border-transparent',
        'before:pointer-events-none before:absolute before:inset-0 before:rounded-[inherit] before:p-px before:opacity-0 before:transition-opacity before:duration-300 hover:before:opacity-100',
        'before:[background:radial-gradient(260px_circle_at_var(--mx)_var(--my),rgba(255,65,3,0.75),transparent_70%)] before:[mask:linear-gradient(#000_0_0)_content-box_exclude,linear-gradient(#000_0_0)]',
        className,
      )}
    >
      {children}
    </div>
  )
}

function Head({ icon, title, tag }: { icon: ReactNode; title: string; tag: string }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="flex items-center gap-3">
        <span className="flex size-9 items-center justify-center rounded-[var(--radius-md)] border border-line-strong text-ember [&_svg]:size-4">{icon}</span>
        <h3 className="text-lg font-medium text-fg">{title}</h3>
      </div>
      <span className="eyebrow hidden text-[10px] sm:inline">{tag}</span>
    </div>
  )
}

export function FeatureBento() {
  return (
    <div className="relative">
      <div className="hairline-grid pointer-events-none absolute -inset-x-6 -inset-y-6 opacity-40 [mask-image:radial-gradient(ellipse_at_center,#000_40%,transparent_75%)]" aria-hidden />
      <div className="relative grid grid-cols-1 gap-3 md:grid-cols-6">
        <Cell className="md:col-span-4 md:row-span-2">
          <Head icon={<Rewind />} title="Time Machine" tag="01 · simulação" />
          <p className="mt-4 max-w-md text-[15px] leading-relaxed text-muted">
            Reconstrói o resto da sessão 10.000 vezes a partir dos candles de 5 minutos do próprio ativo e reexecuta a mesma regra em cada
            sessão passada. Mostra as chances de bater o alvo ou o stop primeiro, a dispersão do preço no fechamento e o histórico real.
          </p>
          <dl className="mt-8 grid grid-cols-3 gap-4 border-t border-line pt-5">
            {[
              ['10.000', 'replays por execução'],
              ['seed', 'registrada para repetir'],
              ['SHA-256', 'de cada snapshot de dados'],
            ].map(([v, l]) => (
              <div key={l}>
                <dt className="sr-only">{l}</dt>
                <dd className="num text-xl text-fg">{v}</dd>
                <dd className="mt-1 text-xs text-muted">{l}</dd>
              </div>
            ))}
          </dl>
        </Cell>
        <Cell className="md:col-span-2">
          <Head icon={<Radar />} title="Market Scanner" tag="02" />
          <p className="mt-3 text-sm leading-relaxed text-muted">
            Varre ações americanas em busca de rompimentos, bandeiras e sobrevenda. Cada padrão vem com o critério, a data e a fonte.
          </p>
        </Cell>
        <Cell className="md:col-span-2">
          <Head icon={<FlaskConical />} title="Strategy Lab" tag="03" />
          <p className="mt-3 text-sm leading-relaxed text-muted">
            Monta regras de entrada, saída e risco em etapas, com versões, duplicação e comparação de configurações.
          </p>
        </Cell>
        <Cell className="md:col-span-3">
          <Head icon={<Activity />} title="Analytics" tag="04" />
          <p className="mt-3 text-sm leading-relaxed text-muted">
            Taxa de acerto com intervalo de confiança, expectativa em R, profit factor, drawdown e consistência por mês. Amostras pequenas
            aparecem como inconclusivas.
          </p>
        </Cell>
        <Cell className="md:col-span-3">
          <Head icon={<BookOpenText />} title="Trading Journal" tag="05" />
          <p className="mt-3 text-sm leading-relaxed text-muted">
            Diário compartilhado de hipóteses, erros e aprendizados, ligado às estratégias e simulações que os originaram.
          </p>
        </Cell>
      </div>
    </div>
  )
}
