import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export function RequireAuth({ children }: { children: ReactNode }) {
  const { canAdmin } = useAuth()
  const location = useLocation()
  if (!canAdmin) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <>{children}</>
}
