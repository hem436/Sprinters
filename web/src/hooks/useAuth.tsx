import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { checkLogin, currentSession, endSession, loginRequired, type Credentials } from '../lib/adminAuth'

// Admin login in the web app only (lib/adminAuth.ts). It decides what the page shows; the API stays open.

interface AuthState {
  user: string | null
  /** True when admin pages may open: no login is set up, or the admin is logged in. */
  canAdmin: boolean
  /** True when an admin password is set up. */
  loginEnabled: boolean
  /** Returns false when the user name or password is wrong, or while too many wrong tries lock the form. */
  login: (creds: Credentials) => boolean
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<string | null>(() => currentSession())
  const loginEnabled = loginRequired()

  const login = useCallback((creds: Credentials) => {
    const ok = checkLogin(creds)
    if (ok) setUser(currentSession() ?? creds.username.trim())
    return ok
  }, [])

  const logout = useCallback(() => {
    endSession()
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, canAdmin: !loginEnabled || user !== null, loginEnabled, login, logout }),
    [user, loginEnabled, login, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth needs AuthProvider')
  return ctx
}
