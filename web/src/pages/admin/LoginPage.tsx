import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { ApiError, USE_MOCKS } from '../../api'
import { ErrorBanner } from '../../components/ui'
import { useAuth } from '../../hooks/useAuth'

export function LoginPage() {
  const { login, status } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/dashboard'
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  // The server needs no login, or the admin is already in: go straight on.
  if (status === 'open' || status === 'logged-in') return <Navigate to={from} replace />

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      await login({ username: username.trim(), password })
      navigate(from, { replace: true })
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? new Error('Wrong user name or password.') : err)
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto mt-10 max-w-sm">
      <form
        className="card space-y-4 !rounded-2xl p-6"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <div>
          <h1 className="text-lg font-semibold">Admin login</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">The dashboard, documents, evaluation and settings need the admin user name and password.</p>
        </div>
        <label className="block">
          <span className="label">User name</span>
          <input className="input" autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label className="block">
          <span className="label">Password</span>
          <input className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error ? <ErrorBanner error={error} /> : null}
        <button type="submit" className="btn-primary w-full" disabled={busy || !password}>
          {busy ? 'Checking' : 'Log in'}
        </button>
        {USE_MOCKS ? <p className="text-xs text-slate-500">Mock mode: user admin, password admin (VITE_MOCK_ADMIN_PASSWORD).</p> : null}
      </form>
    </div>
  )
}
