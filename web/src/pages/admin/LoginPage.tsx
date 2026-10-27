import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { USE_MOCKS } from '../../api'
import { useAuth } from '../../hooks/useAuth'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/dashboard'
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  return (
    <div className="mx-auto mt-10 max-w-sm">
      <form
        className="card space-y-4 p-6"
        onSubmit={(e) => {
          e.preventDefault()
          login({ username: username.trim(), password })
          navigate(from, { replace: true })
        }}
      >
        <div>
          <h1 className="text-lg font-semibold">Admin and reviewer login</h1>
          <p className="text-sm text-slate-500">The dashboard, evaluation and admin pages need the admin password. The server checks it on every call.</p>
        </div>
        <label className="block">
          <span className="label">User name</span>
          <input className="input" autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label className="block">
          <span className="label">Password</span>
          <input className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <button type="submit" className="btn-primary w-full">
          Log in
        </button>
        {USE_MOCKS ? <p className="text-xs text-slate-500">Mock mode: any user name and password work.</p> : null}
      </form>
    </div>
  )
}
