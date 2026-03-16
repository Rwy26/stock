const TOKEN_KEY = 'apollo.accessToken'
const USER_ROLE_KEY = 'apollo.userRole'

export function getAccessToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setAccessToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch {
    // ignore
  }
}

export function getUserRole(): string | null {
  try {
    return localStorage.getItem(USER_ROLE_KEY)
  } catch {
    return null
  }
}

export function setUserRole(role: string): void {
  try {
    localStorage.setItem(USER_ROLE_KEY, role)
  } catch {
    // ignore
  }
}

export function clearAccessToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    // ignore
  }
}

export function clearUserRole(): void {
  try {
    localStorage.removeItem(USER_ROLE_KEY)
  } catch {
    // ignore
  }
}

function base64UrlToString(input: string): string {
  const b64 = input.replace(/-/g, '+').replace(/_/g, '/')
  const padLen = (4 - (b64.length % 4)) % 4
  const padded = b64 + '='.repeat(padLen)
  return atob(padded)
}

export function getJwtExpMs(token: string): number | null {
  try {
    const parts = token.split('.')
    if (parts.length < 2) return null
    const payloadJson = base64UrlToString(parts[1])
    const payload = JSON.parse(payloadJson) as { exp?: number }
    if (!payload.exp) return null
    return payload.exp * 1000
  } catch {
    return null
  }
}
