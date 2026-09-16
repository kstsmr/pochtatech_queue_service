import { CalendarDays, Clock3, MapPin, RotateCw, Ticket as TicketIcon, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { queueApi } from '../api/client'
import type { Ticket } from '../api/types'
import { clearTicketSession, loadTicketSession } from '../lib/ticketSession'

const statusLabels: Record<Ticket['status'], string> = {
  booked: 'Запись подтверждена',
  waiting: 'Ожидайте вызова',
  called: 'Подойдите к окну',
  serving: 'Обслуживание',
  served: 'Обслужен',
  no_show: 'Вызов пропущен',
  cancelled: 'Отменён',
}

const sourceLabels: Record<Ticket['source'], string> = {
  prebooking: 'Предварительная запись',
  qr: 'Талон по QR-коду',
  walk_in: 'Живая очередь',
}

export function TicketPage() {
  const location = useLocation()
  const [session, setSession] = useState(() => loadTicketSession())
  const [ticket, setTicket] = useState<Ticket | null>(null)
  const [loading, setLoading] = useState(Boolean(session))
  const [error, setError] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const justSaved = Boolean((location.state as { justSaved?: boolean } | null)?.justSaved)

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!session) return
    setLoading(true)
    setError(null)
    try {
      setTicket(await queueApi.getTicket(session.ticketId, session.sessionToken, signal))
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === 'AbortError') return
      setError(requestError instanceof Error ? requestError.message : 'Не удалось обновить талон')
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [session])

  useEffect(() => {
    if (!session) return
    const controller = new AbortController()
    queueApi.getTicket(session.ticketId, session.sessionToken, controller.signal)
      .then((data) => {
        setTicket(data)
        setError(null)
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === 'AbortError') return
        setError(requestError instanceof Error ? requestError.message : 'Не удалось обновить талон')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [session])

  async function cancelTicket() {
    if (!session || !ticket || cancelling) return
    if (!window.confirm('Отменить талон? Вернуть его в очередь будет нельзя.')) return
    setCancelling(true)
    setError(null)
    try {
      setTicket(await queueApi.cancelTicket(ticket.id, session.sessionToken, crypto.randomUUID()))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Не удалось отменить талон')
    } finally {
      setCancelling(false)
    }
  }

  function forgetTicket() {
    clearTicketSession()
    setSession(null)
    setTicket(null)
    setError(null)
  }

  if (!session) {
    return (
      <section className="empty-page ticket-empty">
        <span className="empty-ticket-icon"><TicketIcon size={34} aria-hidden="true" /></span>
        <p className="route-kicker">Мой визит</p>
        <h1>Активного талона пока нет</h1>
        <p>Запишитесь ко времени или получите талон по коду внутри отделения.</p>
        <div className="empty-actions">
          <Link className="button primary inline-button" to="/book">Записаться</Link>
          <Link className="button secondary inline-button" to="/qr">Ввести код</Link>
        </div>
      </section>
    )
  }

  if (loading && !ticket) {
    return <section className="empty-page"><p className="route-kicker">Мой визит</p><h1>Загружаем талон…</h1></section>
  }

  if (error && !ticket) {
    return (
      <section className="empty-page">
        <p className="route-kicker">Мой визит</p>
        <h1>Талон пока не загрузился</h1>
        <p>{error}. Данные сохранены на этом устройстве — можно повторить запрос.</p>
        <div className="empty-actions">
          <button className="button primary inline-button" type="button" onClick={() => void refresh()}>
            <RotateCw size={18} aria-hidden="true" /> Повторить
          </button>
          <button className="button secondary inline-button" type="button" onClick={forgetTicket}>Убрать с устройства</button>
        </div>
      </section>
    )
  }

  if (!ticket) return null

  const scheduled = ticket.scheduled_time
    ? new Date(ticket.scheduled_time).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
    : null
  const canCancel = ticket.status === 'booked' || ticket.status === 'waiting'

  return (
    <section className="ticket-page">
      <div className="ticket-heading">
        <p className="route-kicker">Мой визит</p>
        <h1>{justSaved ? 'Талон создан' : statusLabels[ticket.status]}</h1>
        <p>
          {ticket.status === 'called' && ticket.window_number
            ? `Вас ждут в окне № ${ticket.window_number}.`
            : ticket.status === 'waiting'
              ? `Перед вами: ${Math.max((ticket.position ?? 1) - 1, 0)}. Ожидание около ${ticket.estimated_wait_minutes ?? 0} мин.`
              : sourceLabels[ticket.source]}
        </p>
      </div>

      <article className="ticket-sheet">
        <header>
          <span className={`ticket-status status-${ticket.status}`}>{statusLabels[ticket.status]}</span>
          <span className="ticket-mark">О / {String(ticket.ticket_number).padStart(3, '0')}</span>
        </header>
        <div className="ticket-service">
          <small>Услуга</small>
          <h2>{ticket.service_name}</h2>
        </div>
        <div className="ticket-details">
          <div>
            {scheduled ? <CalendarDays size={20} aria-hidden="true" /> : <Clock3 size={20} aria-hidden="true" />}
            <span><small>{scheduled ? 'Дата и время' : 'Очередь'}</small><strong>{scheduled ?? `Позиция ${ticket.position ?? '—'}`}</strong></span>
          </div>
          <div><MapPin size={20} aria-hidden="true" /><span><small>Отделение</small><strong>{ticket.branch_address}</strong></span></div>
        </div>
        <div className="ticket-perforation" aria-hidden="true" />
        <footer>
          <span>{sourceLabels[ticket.source]}</span>
          <span>{new Date(ticket.created_at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })}</span>
        </footer>
      </article>

      {error && <p className="submit-error centered" role="alert">{error}</p>}
      <div className="ticket-actions">
        <button className="button secondary inline-button" type="button" onClick={() => void refresh()} disabled={loading}>
          <RotateCw size={18} aria-hidden="true" /> Обновить
        </button>
        {canCancel ? (
          <button className="button danger inline-button" type="button" onClick={() => void cancelTicket()} disabled={cancelling}>
            <Trash2 size={18} aria-hidden="true" /> {cancelling ? 'Отменяем…' : 'Отменить талон'}
          </button>
        ) : (
          <button className="button secondary inline-button" type="button" onClick={forgetTicket}>Убрать с устройства</button>
        )}
      </div>
    </section>
  )
}
