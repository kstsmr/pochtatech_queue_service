import type { StaffSession } from '../api/types'

const STAFF_SESSION_KEY = 'digital-queue.staff-session.v1'

export function loadStaffSession(): StaffSession | null {
  try {
    localStorage.removeItem(STAFF_SESSION_KEY)
    const raw = sessionStorage.getItem(STAFF_SESSION_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as StaffSession
    if (!parsed.token || !parsed.branch?.id || !parsed.display_name || new Date(parsed.expires_at) <= new Date()) {
      sessionStorage.removeItem(STAFF_SESSION_KEY)
      return null
    }
    return parsed
  } catch {
    sessionStorage.removeItem(STAFF_SESSION_KEY)
    return null
  }
}

export function saveStaffSession(session: StaffSession): void {
  sessionStorage.setItem(STAFF_SESSION_KEY, JSON.stringify(session))
}

export function clearStaffSession(): void {
  sessionStorage.removeItem(STAFF_SESSION_KEY)
}
