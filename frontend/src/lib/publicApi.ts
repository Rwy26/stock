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

/** True when served from a non-local host (i.e. the public tunnel domain), not 127.0.0.1/localhost. */
export function isPublicHost(): boolean {
  if (typeof window === 'undefined') return false
  const h = window.location.hostname
  return h !== '127.0.0.1' && h !== 'localhost'
}

/**
 * 공유 계층 정적 스냅샷 로더.
 *
 * 배치가 생성한 `/static/snapshots/<file>` 를 `?t=` 캐시버스터로 받아
 * `{updated_at,count,source,stale,data}` 봉투에서 `data` 를 푼다.
 * 스냅샷이 없거나(404/HTML 폴백) 실패하면 라이브 공개 API(`apiFallback`)로 폴백한다.
 */
export async function fetchPublicSnapshot<T>(file: string, apiFallback: string): Promise<T> {
  try {
    const res = await fetch(`/static/snapshots/${file}?t=${Date.now()}`, {
      headers: { Accept: 'application/json' },
    })
    if (res.ok) {
      const env = (await res.json()) as { data?: T }
      if (env && env.data != null) return env.data
    }
  } catch {
    // fall through to live API
  }
  return publicFetch<T>(apiFallback)
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
