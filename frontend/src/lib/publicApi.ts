// Public (guest) API helper.
// Deliberately separate from lib/api.ts: NO auth header, NO logout-on-401 redirect.
// The guest "identity" (name + phone) is a lead-capture marker, not authentication.

const GUEST_KEY = 'apollo.guest'

export type Guest = { name: string; phone: string }

export function getGuest(): Guest | null {
  try {
    const raw = localStorage.getItem(GUEST_KEY)
    if (!raw) return null
    const g = JSON.parse(raw) as Guest
    if (g && typeof g.name === 'string' && typeof g.phone === 'string' && g.name && g.phone) return g
    return null
  } catch {
    return null
  }
}

export function setGuest(g: Guest): void {
  try {
    localStorage.setItem(GUEST_KEY, JSON.stringify(g))
  } catch {
    // ignore
  }
}

export function clearGuest(): void {
  try {
    localStorage.removeItem(GUEST_KEY)
  } catch {
    // ignore
  }
}

export async function publicFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const extraHeaders = (init?.headers ?? {}) as Record<string, string>
  const res = await fetch(path, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.body != null ? { 'Content-Type': 'application/json' } : {}),
      ...extraHeaders,
    },
  })
  if (!res.ok) {
    const msg = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}${msg ? `: ${msg}` : ''}`)
  }
  return (await res.json()) as T
}
