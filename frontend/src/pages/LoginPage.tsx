import { useEffect, useRef, useState } from 'react'
import { Navigate, useNavigate, Link } from 'react-router-dom'
import { fetchJson } from '../lib/api'
import { getAccessToken, setAccessToken, setUserRole } from '../lib/auth'
import { isPublicHost } from '../lib/publicApi'

type GoogleCfg = { enabled: boolean; clientId: string | null }

export function LoginPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('administrator')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const publicHost = isPublicHost()
  const [gcfg, setGcfg] = useState<GoogleCfg | null>(null)
  const [gErr, setGErr] = useState<string | null>(null)
  const gBtnRef = useRef<HTMLDivElement>(null)

  // 공개 도메인: 구글 로그인 설정 여부 조회
  useEffect(() => {
    if (!publicHost) return
    fetchJson<GoogleCfg>('/api/auth/google/config')
      .then(setGcfg)
      .catch(() => setGcfg({ enabled: false, clientId: null }))
  }, [publicHost])

  // 공개 도메인: 구글 버튼 렌더 (GIS 스크립트 동적 로드)
  useEffect(() => {
    if (!publicHost || !gcfg?.enabled || !gcfg.clientId) return
    const onCredential = (resp: { credential: string }) => {
      setGErr(null)
      fetchJson<{ accessToken: string; user?: { role?: string } }>('/api/auth/google', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential: resp.credential }),
      })
        .then(res => {
          setAccessToken(res.accessToken)
          if (res.user?.role) setUserRole(res.user.role)
          navigate('/', { replace: true })
        })
        .catch(e => setGErr(e instanceof Error ? e.message : '구글 로그인 실패'))
    }
    const init = () => {
      const g = (window as unknown as { google?: { accounts?: { id?: {
        initialize: (o: object) => void
        renderButton: (el: HTMLElement, o: object) => void
      } } } }).google
      if (!g?.accounts?.id || !gBtnRef.current) return
      g.accounts.id.initialize({ client_id: gcfg.clientId, callback: onCredential })
      g.accounts.id.renderButton(gBtnRef.current, { theme: 'filled_black', size: 'large', width: 280 })
    }
    if ((window as unknown as { google?: unknown }).google) {
      init()
      return
    }
    const s = document.createElement('script')
    s.src = 'https://accounts.google.com/gsi/client'
    s.async = true
    s.onload = init
    document.head.appendChild(s)
  }, [publicHost, gcfg, navigate])

  useEffect(() => {
    // Local-only convenience: if backend enables ALLOW_LOCAL_AUTO_LOGIN, skip the login form.
    // Guardrails:
    // - Only try on localhost
    // - Only when we don't already have a token
    // - Best-effort: if it fails, keep showing the login form
    const token = getAccessToken()
    if (token) return
    if (typeof window === 'undefined') return
    const host = window.location.hostname
    if (host !== '127.0.0.1' && host !== 'localhost') return

    let cancelled = false
    const run = async () => {
      if (cancelled) return
      setBusy(true)
      try {
        const res = await fetchJson<{ accessToken: string; user?: { role?: string } }>('/api/dev/auto-login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        })
        if (cancelled) return
        setAccessToken(res.accessToken)
        if (res.user?.role) setUserRole(res.user.role)
        const profile = await fetchJson<{
          nickname: string | null
          kis: { appKey: string | null; accountPrefix: string | null; hasAppSecret: boolean }
        }>('/api/profile')
        if (cancelled || !profile) return
        const needsSetup = !profile.nickname || !profile.kis?.appKey || !profile.kis?.accountPrefix || !profile.kis?.hasAppSecret
        navigate(needsSetup ? '/profile-setup' : '/', { replace: true })
      } catch {
        // Keep UX minimal: no extra modals/toasts.
      } finally {
        if (!cancelled) setBusy(false)
      }
    }
    void run()

    return () => {
      cancelled = true
    }
  }, [navigate])

  // 공개 도메인: 비밀번호 폼은 절대 노출하지 않는다.
  // 구글 로그인이 설정돼 있으면 구글 버튼만, 아니면 게스트 게이트로 보낸다.
  if (publicHost) {
    if (getAccessToken()) {
      return <Navigate to="/" replace />
    }
    if (gcfg === null) {
      return null // 설정 조회 중
    }
    if (!gcfg.enabled) {
      return <Navigate to="/public" replace />
    }
    return (
      <main className="auth-shell">
        <section className="auth-card glass reveal">
          <h1 className="auth-title">MOON STOCK</h1>
          <p className="subtle">관리자 로그인 — 등록된 구글 계정만 허용됩니다</p>
          <div className="divider"></div>
          <div ref={gBtnRef} style={{ display: 'flex', justifyContent: 'center', minHeight: 44 }} />
          {gErr && <p style={{ color: '#f87171', fontSize: 13, marginTop: 10 }}>{gErr}</p>}
          <p className="hint" style={{ marginTop: 14 }}>
            <Link to="/public" style={{ color: '#93c5fd' }}>게스트 페이지로 이동 →</Link>
          </p>
        </section>
      </main>
    )
  }

  return (
    <main className="auth-shell">
      <section className="auth-card glass reveal">
        <h1 className="auth-title">MOON STOCK</h1>
        <p className="subtle">AI 주식 분석 시스템</p>
        <div className="divider"></div>
        <div className="settings-grid" style={{ gridTemplateColumns: '1fr' }}>
          <label>
            이메일 주소
            <input placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label>
            비밀번호
            <input type="password" placeholder="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
        </div>
        <div className="auth-actions">
          <button
            className="btn"
            type="button"
            disabled={busy}
            onClick={() => {
              setBusy(true)
              fetchJson<{ accessToken: string; user?: { role?: string } }>('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password }),
              })
                .then((res) => {
                  setAccessToken(res.accessToken)
                  if (res.user?.role) setUserRole(res.user.role)
                  return fetchJson<{
                    nickname: string | null
                    kis: { appKey: string | null; accountPrefix: string | null; hasAppSecret: boolean }
                  }>('/api/profile')
                })
                .then((profile) => {
                  const needsSetup =
                    !profile.nickname || !profile.kis?.appKey || !profile.kis?.accountPrefix || !profile.kis?.hasAppSecret
                  navigate(needsSetup ? '/profile-setup' : '/', { replace: true })
                })
                .catch(() => {
                  // Keep UX minimal: no extra modals/toasts.
                })
                .finally(() => setBusy(false))
            }}
          >
            로그인
          </button>
        </div>
      </section>
    </main>
  )
}
