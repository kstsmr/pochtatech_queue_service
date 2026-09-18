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
  branch_timezone: string
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

export type ManagerService = Service & {
  active: boolean
}

export type ManagerPriority = {
  version: number
  actor_id: string
  created_at: string
  config: {
    schema_version: 2
    rule_version: number
    early_minutes: number
    grace_minutes: number
    max_wait_minutes: Record<'prebooking' | 'qr' | 'walk_in', number>
    levels: Record<'overdue' | 'appointment' | 'qr' | 'walk_in' | 'late_prebooking', number>
  }
}

export type ManagerMetrics = {
  waiting_count: number
  average_wait_minutes: number
  maximum_wait_minutes: number
  served_today: number
  open_windows: number
  total_windows: number
  window_load_percent: number
  unresolved_incidents: number
  unfinished_tickets: number
}

export type ManagerIncident = StaffIncident & {
  actor_id: string
  window_number: number | null
  ticket_number: number | null
}

export type ManagerDeviation = {
  id: string
  kind: 'wait_limit' | 'stale_call' | 'long_service' | 'unresolved_incident'
  label: string
  detail: string
  occurred_at: string
}

export type ManagerDashboard = {
  generated_at: string
  metrics: ManagerMetrics
  recommendation: {
    level: 'normal' | 'attention' | 'critical'
    title: string
    detail: string
    suggested_windows: number
  }
  windows: StaffWindow[]
  queue: StaffTicket[]
  services: ManagerService[]
  incidents: ManagerIncident[]
  deviations: ManagerDeviation[]
  unfinished_tickets: StaffTicket[]
  priority_rule: ManagerPriority
}

export type ManagerPriorityUpdate = {
  early_minutes: number
  grace_minutes: number
  prebooking_max_wait_minutes: number
  qr_max_wait_minutes: number
  walk_in_max_wait_minutes: number
  appointment_level: number
  qr_level: number
  walk_in_level: number
  late_prebooking_level: number
}
