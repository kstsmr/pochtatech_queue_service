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

export type StaffSession = {
  token: string
  expires_at: string
  employee_code: string
  display_name: string
  role: 'operator' | 'manager'
  branch: Branch
}

export type StaffIdentity = Omit<StaffSession, 'token' | 'expires_at'>

export type StaffTicket = {
  id: string
  ticket_number: number
  source: Ticket['source']
  status: TicketStatus
  service_id: string
  service_name: string
  window_id: string | null
  window_number: number | null
  target_window_id: string | null
  scheduled_time: string | null
  created_at: string
  called_at: string | null
  waiting_minutes: number
  return_count: number
  redirect_count: number
}

export type StaffWindow = {
  id: string
  number: number
  status: 'closed' | 'open' | 'draining'
  version: number
  owned_by_current_session: boolean
  operator_code: string | null
  service_ids: string[]
  service_names: string[]
  active_ticket: StaffTicket | null
}

export type StaffIncident = {
  id: string
  category: 'technical' | 'operational'
  description: string
  created_at: string
}
