import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { Spinner } from './ui'

export function RequireAuth({ children }: { children: ReactNode }) {
  const { status, canAdmin } = useAuth()
  const location = useLocation()
  if (status === 'checking') return <Spinner label="Checking access" />
  if (!canAdmin) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <>{children}</>
}
