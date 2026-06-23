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

/**
 * 읽기 계층 정적 스냅샷 로더 (대시보드 효율설계).
 *
 * 배치가 생성한 `/static/snapshots/<file>` 를 `?t=` 캐시버스터로 받아
 * `{updated_at,count,source,stale,data}` 봉투에서 `data` 를 푼다.
 * 스냅샷이 없거나(404) 실패하면 라이브 API(`apiFallback`)로 폴백한다.
 * `apiFallback` 이 없으면(스냅샷 전용 산출물) 실패 시 throw — 호출자가 처리.
 * 인증 불필요(공개 정적 파일) — fetchJson 의 토큰 흐름을 타지 않는다.
 */
export async function fetchSnapshot<T>(
  file: string,
  apiFallback?: string,
): Promise<T> {
  try {
    const res = await fetch(`/static/snapshots/${file}?t=${Date.now()}`, {
      headers: { Accept: 'application/json' },
    })
    if (res.ok) {
      const env = (await res.json()) as { data?: T }
      if (env && env.data != null) return env.data
    }
  } catch {
    // fall through to live API (or throw if no fallback)
  }
  if (apiFallback) return fetchJson<T>(apiFallback)
  throw new Error(`snapshot unavailable: ${file}`)
}

export interface SnapshotEnvelope<T> {
  updated_at?: string
  count?: number
  source?: string
  stale?: boolean
  data: T
}

/**
 * fetchSnapshot 의 봉투 버전 — `data` 뿐 아니라 봉투 메타(`updated_at` 등)도 돌려준다.
 *
 * 헤더 '마지막 업데이트'·0단계 asof 를 라이브 계산시각이 아닌 **스냅샷 발행시각**
 * (봉투 `updated_at`)으로 표시할 때 사용한다. 스냅샷이 없으면 라이브로 폴백하되
 * `updated_at` 은 비운다(호출부가 라이브 타임스탬프로 폴백하도록).
 */
export async function fetchSnapshotEnvelope<T>(
  file: string,
  apiFallback?: string,
): Promise<SnapshotEnvelope<T>> {
  try {
    const res = await fetch(`/static/snapshots/${file}?t=${Date.now()}`, {
      headers: { Accept: 'application/json' },
    })
    if (res.ok) {
      const env = (await res.json()) as SnapshotEnvelope<T>
      if (env && env.data != null) return env
    }
  } catch {
    // fall through to live API (or throw if no fallback)
  }
  if (apiFallback) return { data: await fetchJson<T>(apiFallback), source: 'live' }
  throw new Error(`snapshot unavailable: ${file}`)
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
