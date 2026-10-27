import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { ADMIN_LOGIN, loadCredentials, saveCredentials, type Credentials } from '../api/client'

// Admin and reviewer pages use HTTP basic auth (contract 01 section 7). The server checks every call.
// This context only decides what the page shows.

interface AuthState {
  user: string | null
  /** True when admin pages may open: always without a login, else once logged in. */
  canAdmin: boolean
  loginEnabled: boolean
  login: (creds: Credentials) => void
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<string | null>(() => loadCredentials()?.username ?? null)
  const login = useCallback((creds: Credentials) => {
    saveCredentials(creds)
    setUser(creds.username)
  }, [])
  const logout = useCallback(() => {
    saveCredentials(null)
    setUser(null)
  }, [])
  const value = useMemo(() => ({ user, canAdmin: !ADMIN_LOGIN || !!user, loginEnabled: ADMIN_LOGIN, login, logout }), [user, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth needs AuthProvider')
  return ctx
}
