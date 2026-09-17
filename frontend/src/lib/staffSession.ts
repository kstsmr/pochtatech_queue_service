import type { StaffSession } from '../api/types'

const STAFF_SESSION_KEY = 'digital-queue.staff-session.v1'

export function loadStaffSession(): StaffSession | null {
  try {
    const raw = localStorage.getItem(STAFF_SESSION_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as StaffSession
    if (!parsed.token || !parsed.branch?.id || !parsed.display_name || new Date(parsed.expires_at) <= new Date()) {
      localStorage.removeItem(STAFF_SESSION_KEY)
      return null
    }
    return parsed
  } catch {
    localStorage.removeItem(STAFF_SESSION_KEY)
    return null
  }
}

export function saveStaffSession(session: StaffSession): void {
  localStorage.setItem(STAFF_SESSION_KEY, JSON.stringify(session))
}

export function clearStaffSession(): void {
  localStorage.removeItem(STAFF_SESSION_KEY)
}
