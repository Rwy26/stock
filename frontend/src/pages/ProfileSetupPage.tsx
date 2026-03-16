import { Link } from 'react-router-dom'

export function ProfileSetupPage() {
  return (
    <main className="auth-shell">
      <section className="auth-card glass reveal">
        <h1 className="auth-title">프로필 설정</h1>
        <p className="subtle">최초 로그인 후 1회 설정</p>
        <div className="divider"></div>

        <div className="settings-grid" style={{ gridTemplateColumns: '1fr' }}>
          <label>
            닉네임
            <input placeholder="nickname" />
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
            <input placeholder="app key" />
          </label>
          <label>
            KIS 앱 시크릿(App Secret)
            <input placeholder="app secret" />
          </label>
          <label>
            계좌번호(앞 8자리)
            <input placeholder="12345678" />
          </label>
          <label>
            거래 구분
            <select>
              <option>실계좌</option>
              <option>모의투자</option>
            </select>
          </label>
        </div>

        <div className="auth-actions">
          <Link className="btn" to="/" style={{ display: 'inline-grid', placeItems: 'center', textDecoration: 'none' }}>
            저장
          </Link>
          <Link className="btn secondary" to="/login" style={{ display: 'inline-grid', placeItems: 'center', textDecoration: 'none' }}>
            뒤로
          </Link>
        </div>
      </section>
    </main>
  )
}
