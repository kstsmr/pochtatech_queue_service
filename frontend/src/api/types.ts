export type Branch = {
  id: string
  postal_code: string
  name: string
  address: string
  timezone: string
}

export type BranchQr = {
  branch_id: string
  postal_code: string
  join_url: string
  qr_svg_path: string
}

export type Service = {
  id: string
  name: string
  average_service_seconds: number
}

export type AppointmentSlot = {
  id: string
  starts_at: string
  ends_at: string
  available: number
}

export type TicketStatus = 'booked' | 'waiting' | 'called' | 'serving' | 'served' | 'no_show' | 'cancelled'

export type Ticket = {
  id: string
  branch_id: string
  service_id: string
  ticket_number: number
  source: 'prebooking' | 'qr' | 'walk_in'
  status: TicketStatus
  scheduled_time: string | null
  created_at: string
  updated_at: string
  window_number: number | null
  position: number | null
  estimated_wait_minutes: number | null
  branch_name: string
  branch_address: string
  service_name: string
  session_token: string | null
}

export type TicketSession = {
  ticketId: string
  sessionToken: string
}
