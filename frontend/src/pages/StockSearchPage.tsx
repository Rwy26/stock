import { useEffect, useState } from 'react'
import { fetchJson } from '../lib/api'
import { formatNumber, formatPercent } from '../lib/format'

type StockRow = {
  name: string
  code: string
  price: number
  changeRate: number
  score: number
}

type SearchResponse = {
  items: StockRow[]
}

type WatchlistResponse = {
  items: Array<{ code: string }>
}

type StockDetail = StockRow & {
  indicators: {
    value: number
    flow: number
    profit: number
    growth: number
    tech: number
  }
}

type ScreenKey = '' | 'leading' | 'big_buy' | 'bottom_escape' | 'crash_risk'

interface ScreenDef {
  key: ScreenKey
  label: string
  icon: string
  color: string       // accent color
  border: string      // border rgba
  bg: string          // tile bg
  desc: string
  tags: string[]
}

const SCREENS: ScreenDef[] = [
  {
    key: 'leading',
    label: '주도 섹터',
    icon: '🚀',
    color: '#34d399',
    border: 'rgba(52,211,153,0.35)',
    bg: 'rgba(52,211,153,0.07)',
    desc: '이평선 정배열 · 신고가 · 수급 강세 · 거래대금 상위 · 실적 성장',
    tags: ['정배열', '신고가', 'RSI우위', '거래대금上', '주도수급', '거래량폭발', '이익성장', '대장주', '유동성'],
  },
  {
    key: 'big_buy',
    label: '대량 매수',
    icon: '💥',
    color: '#fbbf24',
    border: 'rgba(251,191,36,0.35)',
    bg: 'rgba(251,191,36,0.07)',
    desc: '체결강도 200% · 거래대금 급증 · 대형 단일 체결 포착',
    tags: ['체결강도≥200%', '거래대금급증', '대형체결'],
  },
  {
    key: 'bottom_escape',
    label: '바닥 탈출',
    icon: '📈',
    color: '#60a5fa',
    border: 'rgba(96,165,250,0.35)',
    bg: 'rgba(96,165,250,0.07)',
    desc: '골든크로스 · 볼린저 하단 돌파 반등 · Bullish Divergence · 실적 턴어라운드',
    tags: ['골든크로스', 'BB하단반등', '거래량300%+', 'RSI다이버전스', '실적턴어라운드', '기관+외국인매집'],
  },
  {
    key: 'crash_risk',
    label: '급락 위험',
    icon: '⚠️',
    color: '#f87171',
    border: 'rgba(248,113,113,0.35)',
    bg: 'rgba(248,113,113,0.07)',
    desc: '매수세 소진 · 공매도 급증 · Bearish Divergence · 섹터 Peak-out',
    tags: ['거래량소진', '공매도급증', 'Bearish다이버전스', '장대음봉', '이익률하락', '과열162%+', '섹터Peak-out'],
  },
]

export function StockSearchPage() {
  const [q, setQ] = useState('')
  const [market, setMarket] = useState('KOSPI')
  const [sort, setSort] = useState('관련도')
  const [screen, setScreen] = useState<ScreenKey>('')
  const [rows, setRows] = useState<StockRow[]>([])
  const [selected, setSelected] = useState<StockDetail | null>(null)
  const [watchlistBusy, setWatchlistBusy] = useState(false)
  const [watchCodes, setWatchCodes] = useState<Set<string>>(new Set())

  const activeScreen = SCREENS.find(s => s.key === screen) ?? null

  useEffect(() => {
    let cancelled = false
    fetchJson<SearchResponse>(`/api/stocks/search?q=${encodeURIComponent(q)}&market=${encodeURIComponent(market)}&sort=${encodeURIComponent(sort)}&screen=${encodeURIComponent(screen)}`)
      .then((payload) => {
        if (cancelled) return
        setRows(payload.items)
        if (!selected && payload.items.length > 0) {
          // Default to first item for the detail panel.
          void fetchJson<StockDetail>(`/api/stocks/${encodeURIComponent(payload.items[0].code)}`).then((detail) => {
            if (!cancelled) setSelected(detail)
          })
        }
      })
      .catch(() => {
        if (!cancelled) setRows([])
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const handle = window.setTimeout(() => {
      fetchJson<SearchResponse>(`/api/stocks/search?q=${encodeURIComponent(q)}&market=${encodeURIComponent(market)}&sort=${encodeURIComponent(sort)}&screen=${encodeURIComponent(screen)}`)
        .then((payload) => setRows(payload.items))
        .catch(() => setRows([]))
    }, 200)
    return () => window.clearTimeout(handle)
  }, [q, market, sort, screen])

  useEffect(() => {
    let cancelled = false

    const refreshWatchlist = () => {
      fetchJson<WatchlistResponse>('/api/watchlist')
        .then((payload) => {
          if (!cancelled) {
            setWatchCodes(new Set(payload.items.map((item) => item.code)))
          }
        })
        .catch(() => {
          if (!cancelled) {
            setWatchCodes(new Set())
          }
        })
    }

    refreshWatchlist()
    const id = window.setInterval(refreshWatchlist, 30_000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  const detailIndicators = selected?.indicators
  const selectedAlreadyAdded = selected ? watchCodes.has(selected.code) : false

  return (
    <>
      <header className="topbar glass">
        <div>
          <p className="top-label">Stock Search</p>
          <h2>종목 탐색</h2>
          <p className="subtle">종목명 또는 종목코드 검색 (자동완성)</p>
        </div>
        <div className="status-pill">실시간 조회 준비</div>
      </header>

      {/* ── 스크린 버튼 패널 ── */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 10,
        marginBottom: 16,
      }}>
        {SCREENS.map(s => {
          const active = screen === s.key
          return (
            <button
              key={s.key}
              type="button"
              onClick={() => setScreen(active ? '' : s.key)}
              style={{
                background: active ? s.bg : 'rgba(255,255,255,0.03)',
                border: `1px solid ${active ? s.border : 'rgba(255,255,255,0.08)'}`,
                borderRadius: 12,
                padding: '12px 14px',
                cursor: 'pointer',
                textAlign: 'left',
                transition: 'all 0.18s',
                outline: 'none',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 5 }}>
                <span style={{ fontSize: 18, lineHeight: 1 }}>{s.icon}</span>
                <span style={{
                  fontSize: 13, fontWeight: 700,
                  color: active ? s.color : '#f1f5f9',
                }}>{s.label}</span>
              </div>
              <p style={{
                fontSize: 10, color: 'rgba(255,255,255,0.38)',
                lineHeight: 1.45, margin: 0,
              }}>{s.desc}</p>
            </button>
          )
        })}
      </div>

      {/* 활성 스크린 조건 태그 */}
      {activeScreen && (
        <div style={{
          display: 'flex', flexWrap: 'wrap', gap: 6,
          marginBottom: 14, padding: '10px 14px',
          background: activeScreen.bg,
          border: `1px solid ${activeScreen.border}`,
          borderRadius: 10,
        }}>
          <span style={{ fontSize: 11, color: activeScreen.color, fontWeight: 700, marginRight: 4 }}>
            {activeScreen.icon} {activeScreen.label} 조건:
          </span>
          {activeScreen.tags.map(tag => (
            <span key={tag} style={{
              fontSize: 10, padding: '2px 8px', borderRadius: 99,
              background: activeScreen.color + '18',
              border: `1px solid ${activeScreen.color}44`,
              color: activeScreen.color,
              fontWeight: 600,
            }}>{tag}</span>
          ))}
        </div>
      )}

      <section className="two-col">
        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>검색</h3>
          </div>
          <div className="form-row">
            <label>
              검색어
              <input placeholder="예: 삼성전자 / 005930" value={q} onChange={(e) => setQ(e.target.value)} />
            </label>
            <label>
              시장
              <select value={market} onChange={(e) => setMarket(e.target.value)}>
                <option>KOSPI</option>
                <option>KOSDAQ</option>
                <option>ALL</option>
              </select>
            </label>
            <label>
              정렬
              <select value={sort} onChange={(e) => setSort(e.target.value)}>
                <option>관련도</option>
                <option>거래대금</option>
                <option>등락률</option>
              </select>
            </label>
          </div>
          <div className="divider"></div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>종목명</th>
                  <th>코드</th>
                  <th>현재가</th>
                  <th>등락률</th>
                  <th>상세</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.code}>
                    <td>{row.name}</td>
                    <td>{row.code}</td>
                    <td>{formatNumber(row.price)}</td>
                    <td className={row.changeRate >= 0 ? 'up' : 'down'}>{formatPercent(row.changeRate)}</td>
                    <td>
                      <button
                        className="btn secondary"
                        type="button"
                        onClick={() => {
                          fetchJson<StockDetail>(`/api/stocks/${encodeURIComponent(row.code)}`)
                            .then((detail) => setSelected(detail))
                            .catch(() => setSelected(null))
                        }}
                      >
                        보기
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>종목 상세</h3>
            <p className="subtle">현재가/등락률, 일봉 차트, 14개 지표 점수</p>
          </div>
          <ul className="engine-list">
            <li>
              <span>종목</span>
              <b>{selected ? `${selected.name} (${selected.code})` : '—'}</b>
            </li>
            <li>
              <span>현재가</span>
              <b>{selected ? formatNumber(selected.price) : '—'}</b>
            </li>
            <li>
              <span>등락률</span>
              <b className={selected && selected.changeRate < 0 ? 'down' : 'up'}>
                {selected ? formatPercent(selected.changeRate) : '—'}
              </b>
            </li>
            <li>
              <span>종합 점수</span>
              <b>{selected ? `${selected.score}점` : '—'}</b>
            </li>
          </ul>
          <div className="divider"></div>
          <div className="chart-placeholder">일봉 OHLCV Chart Placeholder</div>
          <div className="divider"></div>
          <div className="two-col" style={{ gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <article className="panel" style={{ padding: 0, border: 0, background: 'transparent', boxShadow: 'none' }}>
              <h3 style={{ fontSize: '1rem' }}>지표 점수</h3>
              <ul className="engine-list" style={{ marginTop: 8 }}>
                <li>
                  <span>가치(29)</span>
                  <b>{detailIndicators ? detailIndicators.value : '—'}</b>
                </li>
                <li>
                  <span>수급(26)</span>
                  <b>{detailIndicators ? detailIndicators.flow : '—'}</b>
                </li>
                <li>
                  <span>수익(21)</span>
                  <b>{detailIndicators ? detailIndicators.profit : '—'}</b>
                </li>
                <li>
                  <span>성장(6)</span>
                  <b>{detailIndicators ? detailIndicators.growth : '—'}</b>
                </li>
                <li>
                  <span>기술(18)</span>
                  <b>{detailIndicators ? detailIndicators.tech : '—'}</b>
                </li>
              </ul>
            </article>
            <article className="panel" style={{ padding: 0, border: 0, background: 'transparent', boxShadow: 'none' }}>
              <h3 style={{ fontSize: '1rem' }}>액션</h3>
              <p className="hint" style={{ marginTop: 8 }}>
                관심 종목 추가
              </p>
              <button
                className="btn"
                type="button"
                style={{ width: '100%' }}
                disabled={!selected || watchlistBusy || selectedAlreadyAdded}
                title={selectedAlreadyAdded ? '이미 관심종목에 추가됨' : '관심종목에 추가'}
                onClick={() => {
                  if (!selected) return
                  setWatchlistBusy(true)
                  fetchJson<{ ok: boolean }>('/api/watchlist', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code: selected.code }),
                  })
                    .then(() => {
                      setWatchCodes((prev) => {
                        const next = new Set(prev)
                        next.add(selected.code)
                        return next
                      })
                    })
                    .catch(() => {
                      // Keep UX minimal: no extra modals/toasts; button simply re-enables.
                    })
                    .finally(() => setWatchlistBusy(false))
                }}
              >
                {selectedAlreadyAdded ? 'v 관심 추가됨' : '☆ 관심 추가'}
              </button>
              <p className="hint" style={{ marginTop: 10 }}>
                점수 상세는 지표별로 확장 예정
              </p>
            </article>
          </div>
        </article>
      </section>
    </>
  )
}
