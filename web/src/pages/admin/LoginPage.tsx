import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth'
import { lockedForMs } from '../../lib/adminAuth'

export function LoginPage() {
  const { login, canAdmin } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/dashboard'
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  // No login is set up, or the admin is already in: go straight on.
  if (canAdmin) return <Navigate to={from} replace />

  function submit() {
    if (login({ username, password })) {
      navigate(from, { replace: true })
      return
    }
    setPassword('')
    const wait = lockedForMs()
    setError(wait > 0 ? `Too many wrong tries. Try again in ${Math.ceil(wait / 1000)} seconds.` : 'Wrong user name or password.')
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
        {error ? (
          <p role="alert" className="m-0 rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-200">
            {error}
          </p>
        ) : null}
        <button type="submit" className="btn-primary w-full" disabled={!password}>
          Log in
        </button>
      </form>
    </div>
  )
}
