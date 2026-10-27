import { NavLink, Outlet } from 'react-router-dom'
import { USE_MOCKS } from '../api'
import { useAuth } from '../hooks/useAuth'
import { HealthBadge } from './HealthBadge'

const NAV = [
  { to: '/chat', label: 'Chat' },
  { to: '/dashboard', label: 'Dashboard', auth: true },
  { to: '/queries', label: 'Queries', auth: true },
  { to: '/eval', label: 'Evaluation', auth: true },
  { to: '/admin/documents', label: 'Documents', auth: true },
  { to: '/admin/finance', label: 'Tables', auth: true },
  { to: '/admin/tools', label: 'Tools', auth: true },
]

export function Layout() {
  const { user, logout } = useAuth()
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5">
          <NavLink to="/chat" className="flex items-center gap-2 font-semibold">
            <img src="/favicon.svg" alt="" className="h-6 w-6" />
            <span>Knowledge Assistant</span>
          </NavLink>
          <nav className="-mx-1 flex flex-1 gap-1 overflow-x-auto text-sm">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-md px-2.5 py-1 ${
                    isActive ? 'bg-indigo-50 font-medium text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-200' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
                  }`
                }
              >
                {n.label}
                {n.auth && !user ? <span className="ml-1 text-[10px] opacity-60">🔒</span> : null}
              </NavLink>
            ))}
          </nav>
          <div className="flex items-center gap-3">
            {USE_MOCKS ? (
              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-amber-800 dark:bg-amber-500/20 dark:text-amber-200" title="VITE_USE_MOCKS=true: data comes from src/api/mock">
                Mock data
              </span>
            ) : null}
            <HealthBadge />
            {user ? (
              <button type="button" onClick={logout} className="text-xs text-slate-500 hover:underline">
                {user} · Log out
              </button>
            ) : (
              <NavLink to="/login" className="text-xs text-indigo-600 hover:underline">
                Admin login
              </NavLink>
            )}
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
