import { NavLink, Outlet, useLocation } from 'react-router-dom'

const menuItems = [
  { to: '/', slug: 'dashboard', label: '대시보드' },
  { to: '/portfolio', slug: 'portfolio', label: '포트폴리오' },
  { to: '/stock-search', slug: 'stock-search', label: '종목 탐색' },
  { to: '/recommendations', slug: 'recommendations', label: '추천 종목' },
  { to: '/watchlist', slug: 'watchlist', label: '관심 종목' },
  { to: '/auto-basic', slug: 'auto-basic', label: '일반 자동매매' },
  { to: '/auto-sa', slug: 'auto-sa', label: 'SA 자동매매' },
  { to: '/auto-plus', slug: 'auto-plus', label: 'Plus 자동매매' },
  { to: '/sv-agent', slug: 'sv-agent', label: 'SV Agent' },
  { to: '/admin', slug: 'admin', label: '관리자' },
] as const

function getPageSlug(pathname: string): string {
  if (pathname === '/' || pathname === '') return 'dashboard'
  return pathname.replace(/^\//, '')
}

export function AppShell() {
  const location = useLocation()
  const page = getPageSlug(location.pathname)

  return (
    <div className="app-shell" data-page={page}>
      <aside className="sidebar glass">
        <h1 className="brand">APOLLO</h1>
        <p className="brand-sub">Jeminai UI for SongStock2</p>

        <nav className="menu-list">
          {menuItems.map((item) => (
            <NavLink
              key={item.slug}
              className={({ isActive }) => `menu${isActive ? ' active' : ''}`}
              data-route={item.slug}
              to={item.to}
              end={item.to === '/'}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <main className="main-panel">
        <Outlet />
      </main>
    </div>
  )
}
