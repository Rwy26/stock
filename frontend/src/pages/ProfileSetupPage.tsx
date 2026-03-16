import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { fetchJson } from '../lib/api'

export function ProfileSetupPage() {
  const navigate = useNavigate()

  const [nickname, setNickname] = useState('')
  const [appKey, setAppKey] = useState('')
  const [appSecret, setAppSecret] = useState('')
  const [hasAppSecret, setHasAppSecret] = useState(false)
  const [accountPrefix, setAccountPrefix] = useState('')
  const [accountProductCode, setAccountProductCode] = useState('01')
  const [tradeType, setTradeType] = useState<'실계좌' | '모의투자'>('실계좌')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetchJson<{
      nickname: string | null
      kis: {
        appKey: string | null
        hasAppSecret: boolean
        accountPrefix: string | null
        accountProductCode?: string | null
        tradeType: '실계좌' | '모의투자'
      }
    }>('/api/profile')
      .then((data) => {
        if (data.nickname != null) setNickname(data.nickname)
        if (data.kis?.appKey != null) setAppKey(data.kis.appKey)
        if (typeof data.kis?.hasAppSecret === 'boolean') setHasAppSecret(data.kis.hasAppSecret)
        if (data.kis?.accountPrefix != null) setAccountPrefix(data.kis.accountPrefix)
        if (data.kis?.accountProductCode != null) setAccountProductCode(data.kis.accountProductCode)
        if (data.kis?.tradeType != null) setTradeType(data.kis.tradeType)
      })
      .catch(() => {
        // Keep UX minimal: no extra modals/toasts.
      })
  }, [])

  return (
    <main className="auth-shell">
      <section className="auth-card glass reveal">
        <h1 className="auth-title">프로필 설정</h1>
        <p className="subtle">최초 로그인 후 1회 설정</p>
        <div className="divider"></div>

        <div className="settings-grid" style={{ gridTemplateColumns: '1fr' }}>
          <label>
            닉네임
            <input placeholder="nickname" value={nickname} onChange={(e) => setNickname(e.target.value)} />
          </label>
        </div>

        <div className="divider"></div>
        <h3 style={{ fontSize: '1rem' }}>KIS API 정보</h3>
        <p className="hint" style={{ marginTop: 6 }}>
          KIS 웹 → MY → 고객서비스 → Open API → 서비스 신청
        </p>

        <div className="settings-grid" style={{ gridTemplateColumns: '1fr', marginTop: 10 }}>
          <label>
            KIS 앱키(App Key)
            <input placeholder="app key" value={appKey} onChange={(e) => setAppKey(e.target.value)} />
          </label>
          <label>
            KIS 앱 시크릿(App Secret)
            <input
              placeholder={hasAppSecret ? '******** (변경 시에만 입력)' : 'app secret'}
              value={appSecret}
              onChange={(e) => setAppSecret(e.target.value)}
            />
          </label>
          <label>
            계좌번호(앞 8자리)
            <input placeholder="12345678" value={accountPrefix} onChange={(e) => setAccountPrefix(e.target.value)} />
          </label>
          <label>
            계좌 상품코드(2자리)
            <input
              placeholder="01"
              value={accountProductCode}
              onChange={(e) => setAccountProductCode(e.target.value)}
            />
          </label>
          <label>
            거래 구분
            <select value={tradeType} onChange={(e) => setTradeType(e.target.value as '실계좌' | '모의투자')}>
              <option>실계좌</option>
              <option>모의투자</option>
            </select>
          </label>
        </div>

        <div className="auth-actions">
          <button
            className="btn"
            type="button"
            disabled={busy}
            onClick={() => {
              setBusy(true)
              fetchJson<{ ok: boolean }>('/api/profile', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ nickname, appKey, appSecret, accountPrefix, accountProductCode, tradeType }),
              })
                .then(() => navigate('/'))
                .catch(() => {
                  // Keep UX minimal: no extra modals/toasts.
                })
                .finally(() => setBusy(false))
            }}
          >
            저장
          </button>
          <Link className="btn secondary" to="/login" style={{ display: 'inline-grid', placeItems: 'center', textDecoration: 'none' }}>
            뒤로
          </Link>
        </div>
      </section>
    </main>
  )
}
