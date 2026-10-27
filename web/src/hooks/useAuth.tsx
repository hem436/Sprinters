import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../api'
import { ApiError, loadCredentials, saveCredentials, UNAUTHORIZED_EVENT, type Credentials } from '../api/client'

// Admin pages use HTTP basic auth (contract 01 section 7). The server decides: GET /auth/me tells whether a
// login is needed. This context only decides what the page shows; the server checks every call.

type Status = 'checking' | 'open' | 'needs-login' | 'logged-in'

interface AuthState {
  status: Status
  user: string | null
  /** True when admin pages may open: the server needs no login, or the admin is logged in. */
  canAdmin: boolean
  /** True when the server asks for an admin login. */
  loginEnabled: boolean
  /** Checks the user name and password with the server, then saves them. Throws ApiError 401 when wrong. */
  login: (creds: Credentials) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('checking')
  const [user, setUser] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    api
      .authMe()
      .then((me) => {
        if (!alive) return
        setUser(me.username)
        setStatus(me.login_required ? 'logged-in' : 'open')
      })
      .catch((err) => {
        if (!alive) return
        // 401: a login is needed. Anything else (an older server without /auth/me, or the server down)
        // means the server does not ask for one; its own errors show on each page.
        const needsLogin = err instanceof ApiError && err.status === 401
        if (needsLogin) saveCredentials(null)
        setStatus(needsLogin ? 'needs-login' : 'open')
      })
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null)
      setStatus('needs-login')
    }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [])

  const login = useCallback(async (creds: Credentials) => {
    const me = await api.authMe(creds)
    saveCredentials(creds)
    setUser(me.username ?? creds.username)
    setStatus(me.login_required ? 'logged-in' : 'open')
  }, [])

  const logout = useCallback(() => {
    const hadLogin = loadCredentials() !== null
    saveCredentials(null)
    setUser(null)
    // Without a server login there is nothing to end; the button only leaves the admin view.
    setStatus((s) => (s === 'logged-in' || (hadLogin && s !== 'open') ? 'needs-login' : s))
  }, [])

  const value = useMemo(
    () => ({
      status,
      user,
      canAdmin: status === 'open' || status === 'logged-in',
      loginEnabled: status === 'needs-login' || status === 'logged-in',
      login,
      logout,
    }),
    [status, user, login, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth needs AuthProvider')
  return ctx
}
