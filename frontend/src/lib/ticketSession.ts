import type { Ticket, TicketSession } from '../api/types'

const STORAGE_KEY = 'digital-queue.ticket-session.v1'

export function saveTicketSession(ticket: Ticket): void {
  if (!ticket.session_token) throw new Error('Сервер не вернул токен талона')
  const session: TicketSession = { ticketId: ticket.id, sessionToken: ticket.session_token }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
}

export function loadTicketSession(): TicketSession | null {
  const value = localStorage.getItem(STORAGE_KEY)
  if (!value) return null
  try {
    const session = JSON.parse(value) as Partial<TicketSession>
    if (!session.ticketId || !session.sessionToken || session.sessionToken.length < 20) return null
    return session as TicketSession
  } catch {
    return null
  }
}

export function clearTicketSession(): void {
  localStorage.removeItem(STORAGE_KEY)
}
