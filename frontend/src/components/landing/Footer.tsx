/**
 * Footer 7 (after Shadcnblocks; source needs a 21st.dev login): logo and
 * tagline, menu columns, copyright and legal line. Only real links; no social
 * accounts are listed because the project has none.
 */
import { Link } from 'react-router-dom'
import { EclipseMark } from '@/brand/EclipseMark'
import { Tagline, Wordmark } from '@/brand/Wordmark'

const cols = [
  { title: 'Plataforma', links: [{ l: 'Apresentação', h: '#plataforma' }, { l: 'Funcionalidades', h: '#funcionalidades' }, { l: 'Metodologia', h: '#metodologia' }] },
  {
    title: 'Laboratório',
    links: [
      { l: 'Dashboard', h: '/app' },
      { l: 'Market Scanner', h: '/app/scanner' },
      { l: 'Time Machine', h: '/app/time-machine' },
      { l: 'Trading Journal', h: '/app/journal' },
    ],
  },
  { title: 'Acesso', links: [{ l: 'Abrir laboratório', h: '/app' }] },
]

/** publicOnly: the GitHub Pages build links only to sections of the landing page. */
export function Footer({ publicOnly = false }: { publicOnly?: boolean }) {
  return (
    <footer className="border-t border-line bg-abyss">
      <div className="mx-auto max-w-7xl px-4 py-14 sm:px-6">
        <div className="grid gap-10 lg:grid-cols-[1.4fr_2fr]">
          <div>
            <div className="flex items-center gap-3">
              <EclipseMark className="size-9" />
              <Wordmark className="h-4 w-auto text-fg" />
            </div>
            <Tagline className="mt-4 block text-[10px] text-muted" />
            <p className="mt-6 max-w-sm text-sm leading-relaxed text-muted">
              Laboratório compartilhado de pesquisa quantitativa. Resultados históricos e simulações servem para estudo e não são recomendação de
              investimento nem previsão de mercado.
            </p>
          </div>
          <nav aria-label="Rodapé" className="grid grid-cols-2 gap-8 sm:grid-cols-3">
            {(publicOnly ? cols.slice(0, 1) : cols).map((c) => (
              <div key={c.title}>
                <p className="eyebrow mb-4 text-[10px]">{c.title}</p>
                <ul className="space-y-2.5">
                  {c.links.map((l) => (
                    <li key={l.l}>
                      {l.h.startsWith('#') ? (
                        <a href={l.h} className="text-sm text-fg/85 hover:text-ember">
                          {l.l}
                        </a>
                      ) : (
                        <Link to={l.h} className="text-sm text-fg/85 hover:text-ember">
                          {l.l}
                        </Link>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        </div>
        <div className="mt-14 flex flex-col gap-3 border-t border-line pt-6 text-xs text-faint sm:flex-row sm:items-center sm:justify-between">
          <p>© 2026 DARK POOL · Market Research Lab · uso de pesquisa, sem ordens reais</p>
          <p>
            Desenvolvido por <span className="text-muted">Or7</span>
          </p>
        </div>
      </div>
    </footer>
  )
}
