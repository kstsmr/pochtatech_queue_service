import { ArrowLeft } from 'lucide-react'
import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <section className="empty-page">
      <p className="route-kicker">Ошибка 404</p>
      <h1>Такой страницы нет</h1>
      <p>Похоже, адрес изменился или был введён с ошибкой.</p>
      <Link className="button primary inline-button" to="/">
        <ArrowLeft size={19} aria-hidden="true" />
        На главную
      </Link>
    </section>
  )
}
