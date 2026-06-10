import { useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { clearGuest, getGuest, publicFetch, setGuest, type Guest } from '../lib/publicApi'

const publicMenu = [
  { to: '/public/watchlist', end: false, label: '⭐ 관심 종목' },
  { to: '/public/sector', end: false, label: '🧭 섹터 나침반' },
  { to: '/public/ai-request', end: false, label: '🤖 AI 종목 분석 요청' },
] as const

const inputStyle: CSSProperties = {
  width: '100%',
  padding: '10px 12px',
  margin: '6px 0 14px',
  borderRadius: 8,
  border: '1px solid rgba(255,255,255,0.15)',
  background: 'rgba(255,255,255,0.05)',
  color: '#f1f5f9',
  boxSizing: 'border-box',
}

export function PublicShell() {
  const [guest, setGuestState] = useState<Guest | null>(() => getGuest())
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    const n = name.trim()
    const p = phone.trim()
    if (!n || !p) {
      setErr('이름과 전화번호를 입력하세요.')
      return
    }
    setBusy(true)
    setErr(null)
    try {
      await publicFetch('/api/public/signup', { method: 'POST', body: JSON.stringify({ name: n, phone: p }) })
      const g: Guest = { name: n, phone: p }
      setGuest(g)
      setGuestState(g)
    } catch {
      setErr('등록에 실패했습니다. 잠시 후 다시 시도하세요.')
    } finally {
      setBusy(false)
    }
  }

  if (!guest) {
    return (
      <div className="app-shell" data-page="public-gate">
        <main className="main-panel" style={{ display: 'grid', placeItems: 'center' }}>
          <form className="glass" onSubmit={submit} style={{ padding: 32, width: 360, maxWidth: '90vw' }}>
            <h1 className="brand" style={{ marginBottom: 4 }}>MOON STOCK</h1>
            <p className="brand-sub" style={{ marginBottom: 20 }}>공개 시장 분석 · 게스트 입장</p>
            <label style={{ fontSize: 13, color: '#cbd5e1' }}>이름</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="이름" style={inputStyle} />
            <label style={{ fontSize: 13, color: '#cbd5e1' }}>전화번호</label>
            <input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="010-0000-0000"
              inputMode="tel"
              style={inputStyle}
            />
            {err && <p style={{ color: '#f87171', fontSize: 13, margin: '0 0 8px' }}>{err}</p>}
            <button className="btn" type="submit" disabled={busy} style={{ width: '100%', marginTop: 4 }}>
              {busy ? '입장 중…' : '입장하기'}
            </button>
            <p style={{ fontSize: 11, color: '#94a3b8', marginTop: 14, lineHeight: 1.5 }}>
              입력하신 이름·전화번호는 방문 기록 및 AI 분석 요청 처리에 사용됩니다.
            </p>
          </form>
        </main>
      </div>
    )
  }

  return (
    <div className="app-shell" data-page="public">
      <aside className="sidebar glass">
        <h1 className="brand">MOON STOCK</h1>
        <p className="brand-sub">공개 시장 분석</p>

        <nav className="menu-list">
          {publicMenu.map((m) => (
            <NavLink
              key={m.to}
              to={m.to}
              end={m.end}
              className={({ isActive }) => `menu${isActive ? ' active' : ''}`}
            >
              {m.label}
            </NavLink>
          ))}
        </nav>

        <div className="divider" style={{ marginTop: 16 }}></div>
        <p style={{ fontSize: 12, color: '#94a3b8', margin: '12px 0 8px' }}>{guest.name}님 환영합니다</p>
        <button
          className="btn secondary"
          type="button"
          onClick={() => {
            clearGuest()
            setGuestState(null)
          }}
        >
          나가기
        </button>
      </aside>

      <main className="main-panel">
        <Outlet />
      </main>
    </div>
  )
}
