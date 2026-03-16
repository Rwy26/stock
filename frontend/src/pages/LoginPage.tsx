import { Link } from 'react-router-dom'

export function LoginPage() {
  return (
    <main className="auth-shell">
      <section className="auth-card glass reveal">
        <h1 className="auth-title">APOLLO</h1>
        <p className="subtle">Apollo Stock Trading System (SongStock2)</p>
        <div className="divider"></div>
        <div className="settings-grid" style={{ gridTemplateColumns: '1fr' }}>
          <label>
            이메일 주소
            <input placeholder="email" />
          </label>
          <label>
            비밀번호
            <input type="password" placeholder="password" />
          </label>
        </div>
        <div className="auth-actions">
          <Link className="btn" to="/" style={{ display: 'inline-grid', placeItems: 'center', textDecoration: 'none' }}>
            로그인
          </Link>
          <Link
            className="btn secondary"
            to="/profile-setup"
            style={{ display: 'inline-grid', placeItems: 'center', textDecoration: 'none' }}
          >
            최초 설정
          </Link>
        </div>
        <p className="hint" style={{ marginTop: 12 }}>
          기본 계정: administrator / !Sunset22
        </p>
      </section>
    </main>
  )
}
