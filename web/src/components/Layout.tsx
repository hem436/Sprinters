import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { USE_MOCKS } from '../api'
import { useAuth } from '../hooks/useAuth'
import { HealthBadge } from './HealthBadge'
import { ThemeToggle } from './ThemeToggle'

// Two simple views, like Verba: employees see the chat; admins and reviewers see the dashboard first.

const USER_NAV = [{ to: '/chat', label: 'Chat' }]

const ADMIN_NAV = [
  { to: '/dashboard', label: 'Dashboard', match: ['/dashboard', '/queries'] },
  { to: '/admin/documents', label: 'Documents', match: ['/admin/documents', '/admin/finance'] },
  { to: '/eval', label: 'Evaluation', match: ['/eval'] },
  { to: '/admin/tools', label: 'Settings', match: ['/admin/tools'] },
]

const ADMIN_PREFIXES = ['/dashboard', '/queries', '/eval', '/admin']

export function isAdminPath(path: string): boolean {
  return ADMIN_PREFIXES.some((p) => path === p || path.startsWith(`${p}/`))
}

const pill = (active: boolean) =>
  `inline-flex min-h-[38px] items-center whitespace-nowrap rounded-full px-4 text-sm font-medium transition ${
    active ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900' : 'text-slate-600 hover:bg-slate-200/70 dark:text-slate-300 dark:hover:bg-slate-800'
  }`

const ghost =
  'inline-flex min-h-[38px] items-center whitespace-nowrap rounded-full border border-slate-300 bg-white px-4 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800'

export function Layout() {
  const { user, canAdmin, loginEnabled, logout } = useAuth()
  const { pathname } = useLocation()
  const admin = isAdminPath(pathname)

  return (
    <div className="flex min-h-screen flex-col bg-slate-100 dark:bg-slate-950">
      <header className="mx-auto flex w-full max-w-7xl flex-wrap items-center gap-x-5 gap-y-2 px-4 pb-2 pt-4 sm:px-6">
        <NavLink to={admin ? '/dashboard' : '/chat'} className="flex items-center gap-2.5 text-base font-bold">
          <img src="/favicon.svg" alt="" className="h-8 w-8" />
          <span>Knowledge Assistant</span>
          {admin ? (
            <span className="rounded-full border border-slate-300 px-2 py-0.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:text-slate-300">Admin</span>
          ) : null}
        </NavLink>
        {USE_MOCKS ? (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase text-amber-800 dark:bg-amber-500/20 dark:text-amber-200" title="VITE_USE_MOCKS=true: data comes from src/api/mock">
            Mock data
          </span>
        ) : null}

        <nav aria-label={admin ? 'Admin' : 'Main'} className="ml-auto flex flex-wrap items-center gap-1.5">
          {admin
            ? ADMIN_NAV.map((n) => (
                <NavLink key={n.to} to={n.to} className={() => pill(n.match.some((m) => pathname.startsWith(m)))}>
                  {n.label}
                </NavLink>
              ))
            : USER_NAV.map((n) => (
                <NavLink key={n.to} to={n.to} className={({ isActive }) => pill(isActive)}>
                  {n.label}
                </NavLink>
              ))}
          {admin ? (
            <NavLink to="/chat" className={ghost}>
              Back to chat
            </NavLink>
          ) : (
            <NavLink to={canAdmin ? '/dashboard' : '/login'} className={ghost}>
              Admin
            </NavLink>
          )}
          <ThemeToggle />
        </nav>

        {admin ? (
          <div className="flex w-full items-center justify-end gap-3 sm:w-auto">
            <HealthBadge />
            {loginEnabled && user ? (
              <button type="button" onClick={logout} className="text-xs text-slate-500 hover:underline">
                {user} · Log out
              </button>
            ) : null}
          </div>
        ) : null}
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 pb-8 pt-4 sm:px-6">
        <Outlet />
      </main>
    </div>
  )
}
