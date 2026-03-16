import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchJson } from '../lib/api'
import { setAccessToken, setUserRole } from '../lib/auth'

export function LoginPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('administrator')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)

  return (
    <main className="auth-shell">
      <section className="auth-card glass reveal">
        <h1 className="auth-title">APOLLO</h1>
        <p className="subtle">Apollo Stock Trading System (SongStock2)</p>
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
                  return fetchJson<{ nickname: string | null; kis: { appKey: string | null; accountPrefix: string | null } }>('/api/profile')
                })
                .then((profile) => {
                  const needsSetup = !profile.nickname || !profile.kis?.appKey || !profile.kis?.accountPrefix
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
          기본 계정: administrator / !Sunset22
        </p>
      </section>
    </main>
  )
}
