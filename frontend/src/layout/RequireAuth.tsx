import type { PropsWithChildren } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { getAccessToken } from '../lib/auth'
import { isPublicHost } from '../lib/publicApi'

export function RequireAuth({ children }: PropsWithChildren) {
  const location = useLocation()
  const token = getAccessToken()

  if (!token) {
    // On the public tunnel domain, guests get the name+phone gate, not the admin login.
    return <Navigate to={isPublicHost() ? '/public' : '/login'} replace state={{ from: location.pathname }} />
  }

  return <>{children}</>
}
