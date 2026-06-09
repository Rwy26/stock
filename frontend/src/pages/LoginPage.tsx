import { useEffect, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { fetchJson } from '../lib/api'
import { getAccessToken, setAccessToken, setUserRole } from '../lib/auth'
import { isPublicHost } from '../lib/publicApi'

export function LoginPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('administrator')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)

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

  // On the public tunnel domain, never show the admin login — send guests to the name+phone gate.
  if (isPublicHost()) {
    return <Navigate to="/public" replace />
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
        <p className="hint" style={{ marginTop: 12 }}>
          기본 계정: administrator / ChangeMe!
        </p>
      </section>
    </main>
  )
}
