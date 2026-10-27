import { sha256Hex } from './sha256'

// Admin login checked in the web app only (the team keeps the back end open, issue #48).
// This hides the admin pages; it does not protect the API, which anyone can still call directly.
//
// VITE_ADMIN_USERNAME   user name, default "admin"
// VITE_ADMIN_PASSWORD_SHA256   hex SHA-256 of the password; empty means no login
//
// Only the hash is in the built app. The password itself is never stored, in the build or in the browser.

export interface Credentials {
  username: string
  password: string
}

interface Session {
  username: string
  expires: number
  /** First characters of the hash, so a new password ends old sessions. */
  key: string
}

const SESSION_KEY = 'ka.admin'
const SESSION_MS = 8 * 60 * 60 * 1000
const MAX_FAILURES = 5
const LOCK_MS = 30 * 1000

let failures = 0
let lockedUntil = 0

// Read at call time, so tests can change the settings with vi.stubEnv.
function settings(): { username: string; hash: string } {
  return {
    username: (import.meta.env.VITE_ADMIN_USERNAME ?? '').trim() || 'admin',
    hash: (import.meta.env.VITE_ADMIN_PASSWORD_SHA256 ?? '').trim().toLowerCase(),
  }
}

export function loginRequired(): boolean {
  return settings().hash !== ''
}

/** Same time for every string of the same length, so the compare does not leak how much matched. */
function sameText(a: string, b: string): boolean {
  let diff = a.length ^ b.length
  for (let i = 0; i < Math.max(a.length, b.length); i++) diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0)
  return diff === 0
}

/** Milliseconds until another try is allowed; 0 when not locked. */
export function lockedForMs(now = Date.now()): number {
  return Math.max(0, lockedUntil - now)
}

/** Checks the user name and password. On success, saves a session and returns true. */
export function checkLogin(creds: Credentials, now = Date.now()): boolean {
  if (lockedForMs(now) > 0) return false
  const { username, hash } = settings()
  // Run both checks every time, so a wrong user name takes as long as a wrong password.
  const userOk = sameText(creds.username.trim(), username)
  const passwordOk = sameText(sha256Hex(creds.password), hash)
  const ok = hash !== '' && userOk && passwordOk
  if (!ok) {
    failures += 1
    if (failures >= MAX_FAILURES) {
      failures = 0
      lockedUntil = now + LOCK_MS
    }
    return false
  }
  failures = 0
  try {
    const session: Session = { username, expires: now + SESSION_MS, key: hash.slice(0, 12) }
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(session))
  } catch {
    // Storage blocked: the login lasts until the page reloads.
  }
  return true
}

/** The logged-in user name, or null when there is no valid session. */
export function currentSession(now = Date.now()): string | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    if (!raw) return null
    const s = JSON.parse(raw) as Session
    if (s.expires > now && s.key === settings().hash.slice(0, 12)) return s.username
    sessionStorage.removeItem(SESSION_KEY)
  } catch {
    // Unreadable or blocked storage: treat as logged out.
  }
  return null
}

export function endSession(): void {
  try {
    sessionStorage.removeItem(SESSION_KEY)
  } catch {
    // Nothing saved.
  }
}

/** Test helper: forget failed tries and the lock. */
export function resetLoginLimits(): void {
  failures = 0
  lockedUntil = 0
}
