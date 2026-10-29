import { Link } from 'react-router-dom'
import { EclipseMark } from '@/brand/EclipseMark'

export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-5 px-4 text-center">
      <EclipseMark className="size-16" title="" />
      <p className="eyebrow">Erro 404</p>
      <h1 className="text-2xl text-fg">Esta página não existe.</h1>
      <Link to="/" className="text-sm text-ember hover:underline">
        Voltar ao início
      </Link>
    </div>
  )
}
