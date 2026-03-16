import type { PropsWithChildren } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { getAccessToken } from '../lib/auth'

export function RequireAuth({ children }: PropsWithChildren) {
  const location = useLocation()
  const token = getAccessToken()

  if (!token) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return <>{children}</>
}
