import type { AppointmentSlot, Branch, BranchQr, Service, Ticket } from './types'

const API_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/$/, '')

export function apiAssetUrl(path: string): string {
  return `${API_URL}${path}`
}

export class ApiClientError extends Error {
  readonly status: number | undefined

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'ApiClientError'
    this.status = status
  }
}

type RequestOptions = {
  method?: 'GET' | 'POST'
  body?: unknown
  headers?: Record<string, string>
  signal?: AbortSignal
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response: Response

  try {
    response = await fetch(`${API_URL}${path}`, {
      method: options.method ?? 'GET',
      headers: {
        Accept: 'application/json',
        ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...options.headers,
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: 'omit',
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }
    throw new ApiClientError('Не удалось связаться с сервером очереди')
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null) as { message?: string } | null
    throw new ApiClientError(body?.message ?? 'Сервер не смог выполнить запрос', response.status)
  }

  return response.json() as Promise<T>
}

export const queueApi = {
  getBranches: (signal?: AbortSignal) => request<Branch[]>('/api/branches', { signal }),
  getBranchByCode: (code: string, signal?: AbortSignal) =>
    request<Branch>(`/api/branches/code/${encodeURIComponent(code)}`, { signal }),
  getBranchQr: (branchId: string, signal?: AbortSignal) =>
    request<BranchQr>(`/api/branches/${encodeURIComponent(branchId)}/queue-qr`, { signal }),
  getServices: (branchId: string, signal?: AbortSignal) =>
    request<Service[]>(`/api/branches/${encodeURIComponent(branchId)}/services`, { signal }),
  getSlots: (branchId: string, serviceId: string, date: string, signal?: AbortSignal) => {
    const query = new URLSearchParams({ service_id: serviceId, date })
    return request<AppointmentSlot[]>(`/api/branches/${encodeURIComponent(branchId)}/slots?${query}`, { signal })
  },
  createBooking: (branchId: string, serviceId: string, slotId: string, idempotencyKey: string) =>
    request<Ticket>('/api/bookings', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: { branch_id: branchId, service_id: serviceId, slot_id: slotId },
    }),
  joinQueue: (branchCode: string, serviceId: string, idempotencyKey: string) =>
    request<Ticket>('/api/queue/join', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: { branch_code: branchCode, service_id: serviceId },
    }),
  getTicket: (ticketId: string, sessionToken: string, signal?: AbortSignal) =>
    request<Ticket>(`/api/tickets/${encodeURIComponent(ticketId)}`, {
      headers: { 'X-Session-Token': sessionToken },
      signal,
    }),
  cancelTicket: (ticketId: string, sessionToken: string, idempotencyKey: string) =>
    request<Ticket>(`/api/tickets/${encodeURIComponent(ticketId)}/cancel`, {
      method: 'POST',
      headers: { 'X-Session-Token': sessionToken, 'Idempotency-Key': idempotencyKey },
    }),
}
