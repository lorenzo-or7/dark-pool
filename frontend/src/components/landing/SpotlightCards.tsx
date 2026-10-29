/**
 * Feature Grid Spotlight Cards (after Mohammad Shehadeh "feature-08"; source
 * needs a 21st.dev login): six cards on hairline rails, inline icon beside the
 * title, corner crosshair marks and a radial spotlight that follows the pointer.
 */
import { Ban, Database, Fingerprint, Gauge, Hourglass, Users } from 'lucide-react'
import type { PointerEvent, ReactNode } from 'react'

const items: { icon: ReactNode; title: string; body: string }[] = [
  { icon: <Fingerprint />, title: 'Reprodutível', body: 'Parâmetros, seed, versão do algoritmo e hash dos dados ficam gravados. A mesma execução dá os mesmos números.' },
  { icon: <Database />, title: 'Procedência', body: 'Cada número diz de onde veio: histórico, simulado ou demonstração, com fonte e horário da coleta.' },
  { icon: <Hourglass />, title: 'Atraso declarado', body: 'Cotações gratuitas chegam com atraso e são identificadas assim. Nada aqui é tempo real.' },
  { icon: <Gauge />, title: 'Amostra explícita', body: 'Com poucas operações, as taxas ficam ocultas ou marcadas como inconclusivas, com o intervalo de confiança à vista.' },
  { icon: <Users />, title: 'Workspace compartilhado', body: 'Dois pesquisadores, um laboratório. O acesso é controlado no banco de dados, não só na tela.' },
  { icon: <Ban />, title: 'Sem ordens reais', body: 'Não há corretora conectada nem envio de ordens. Risco e tamanho de posição são calculados apenas em simulação.' },
]

function Crosshair({ className }: { className: string }) {
  return (
    <svg viewBox="0 0 11 11" className={`absolute size-2.5 text-line-strong ${className}`} aria-hidden>
      <path d="M5.5 0v11M0 5.5h11" stroke="currentColor" strokeWidth="1" />
    </svg>
  )
}

export function SpotlightCards() {
  function onMove(e: PointerEvent<HTMLLIElement>) {
    const r = e.currentTarget.getBoundingClientRect()
    e.currentTarget.style.setProperty('--sx', `${e.clientX - r.left}px`)
    e.currentTarget.style.setProperty('--sy', `${e.clientY - r.top}px`)
  }
  return (
    <ul className="grid grid-cols-1 border-t border-l border-line sm:grid-cols-2 lg:grid-cols-3">
      {items.map((it) => (
        <li
          key={it.title}
          onPointerMove={onMove}
          className="group relative border-r border-b border-line p-7 transition-colors [background:radial-gradient(240px_circle_at_var(--sx,-200px)_var(--sy,-200px),rgba(255,65,3,0.07),transparent_70%)]"
        >
          <span className="pointer-events-none absolute inset-x-0 top-0 h-16 bg-gradient-to-b from-ember/[0.05] to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" aria-hidden />
          <Crosshair className="-top-[5px] -left-[5px]" />
          <div className="flex items-center gap-2.5 text-fg [&_svg]:size-4 [&_svg]:text-ember">
            {it.icon}
            <h3 className="text-[15px] font-medium">{it.title}</h3>
          </div>
          <p className="mt-3 text-sm leading-relaxed text-muted">{it.body}</p>
        </li>
      ))}
    </ul>
  )
}
