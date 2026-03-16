import { clearAccessToken, clearUserRole, getAccessToken, setAccessToken } from './auth'

function logoutToLogin(): void {
  clearAccessToken()
  clearUserRole()
  if (typeof window !== 'undefined') {
    window.location.href = '/login'
  }
}

export async function refreshAccessToken(): Promise<boolean> {
  const token = getAccessToken()
  if (!token) return false

  try {
    const response = await fetch('/api/auth/refresh', {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${token}`,
      },
    })

    if (!response.ok) {
      // If refresh itself is unauthorized, caller decides whether to logout.
      return false
    }

    const data = (await response.json()) as { accessToken: string }
    if (data?.accessToken) {
      setAccessToken(data.accessToken)
      return true
    }
    return false
  } catch {
    return false
  }
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const initHeaders = (init?.headers ?? {}) as Record<string, string>

  const doFetch = async () => {
    const token = getAccessToken()
    return fetch(path, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...initHeaders,
      },
    })
  }

  let response = await doFetch()
  if (response.ok) {
    return (await response.json()) as T
  }

  if (response.status === 401) {
    const token = getAccessToken()
    const isAuthRoute = path.startsWith('/api/auth/login') || path.startsWith('/api/auth/refresh')

    // If we have a token and this is not an auth route, try refresh once and retry.
    const canRetryBody = init?.body == null || typeof init.body === 'string'
    if (token && !isAuthRoute && canRetryBody) {
      const refreshed = await refreshAccessToken()
      if (refreshed) {
        response = await doFetch()
        if (response.ok) {
          return (await response.json()) as T
        }
      }
    }

    // Hard logout on unauthorized.
    logoutToLogin()
  }

  const message = await response.text().catch(() => '')
  throw new Error(`HTTP ${response.status} ${response.statusText}${message ? `: ${message}` : ''}`)
}
