import { useEffect, useMemo, useState } from 'react'
import { fetchJson } from '../lib/api'
import { formatNumber, formatPercent } from '../lib/format'

type RecommendationItem = {
  rank: number
  name: string
  code: string
  score: number
  price: number
  changeRate: number
}

type RecommendationsResponse = {
  date: string
  items: RecommendationItem[]
  priceError?: string | null
}

type WatchlistResponse = {
  items: Array<{ code: string }>
}

// ─── KING types ───────────────────────────────────────────────────────────────

type KingSector = {
  sector: string
  etf_ticker: string
  alpha_1m: number | null
  alpha_3m: number | null
  rank: number
}

type KingTopStock = {
  code: string
  name: string
  score_total: number
  eligible: boolean
  eps_growth: number | null
  eps_growth_note: string | null
}

type KingResponse = {
  king_sectors: KingSector[]
  top_stocks: KingTopStock[]
  scored_date: string
  note: string
}

// ─── KING Panel ───────────────────────────────────────────────────────────────

function KingPanel() {
  const [data, setData] = useState<KingResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadKing = () => {
    setLoading(true)
    setError(null)
    fetchJson<KingResponse>('/api/recommendations/king')
      .then((r) => setData(r))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }

  const fmtAlpha = (v: number | null) =>
    v == null ? 'N/A' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`

  return (
    <section className="panel glass reveal" style={{ marginBottom: '1rem' }}>
      <div className="panel-head" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3>👑 KING 카테고리 — 섹터 순환 주도주</h3>
        <button className="btn secondary" onClick={loadKing} disabled={loading}>
          {loading ? '분석 중…' : '섹터 분석 실행'}
        </button>
      </div>

      {error && <div className="banner warn" style={{ margin: '0.5rem 1rem' }}>{error}</div>}

      {!data && !loading && (
        <p className="subtle" style={{ padding: '0.8rem 1rem', margin: 0 }}>
          버튼을 눌러 KOSPI 대비 초과수익이 높은 섹터 TOP 2와 대표 ETF를 확인하세요.
        </p>
      )}

      {loading && (
        <p className="subtle" style={{ padding: '0.8rem 1rem', margin: 0 }}>
          yfinance로 섹터 ETF 알파 계산 중… (최대 20초)
        </p>
      )}

      {data && (
        <div style={{ padding: '0.5rem 1rem 1rem' }}>
          {/* 섹터 카드 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '0.7rem', marginBottom: '1rem' }}>
            {data.king_sectors.map((s) => (
              <div key={s.etf_ticker} className="panel glass" style={{ padding: '0.9rem 1rem' }}>
                <p style={{ margin: 0, fontWeight: 700, fontSize: '1.05rem' }}>
                  🏆 #{s.rank} {s.sector}
                </p>
                <p style={{ margin: '0.3rem 0 0', fontSize: '0.82rem', color: 'var(--muted)' }}>ETF: {s.etf_ticker}</p>
                <p style={{ margin: '0.2rem 0 0', fontSize: '0.9rem' }}>
                  1M 초과수익 <span style={{ color: (s.alpha_1m ?? 0) >= 0 ? 'var(--up)' : 'var(--down)' }}>{fmtAlpha(s.alpha_1m)}</span>
                </p>
                <p style={{ margin: '0.1rem 0 0', fontSize: '0.85rem', color: 'var(--muted)' }}>
                  3M {fmtAlpha(s.alpha_3m)}
                </p>
              </div>
            ))}
          </div>

          {/* 최고점수 종목 */}
          {data.top_stocks.length > 0 && (
            <>
              <p style={{ margin: '0 0 0.4rem', fontSize: '0.85rem', color: 'var(--muted)' }}>
                당일 스코어링 TOP 종목 ({data.scored_date})
              </p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>#</th><th>코드</th><th>종목명</th><th>점수</th><th>EPS성장</th><th>추천대상</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.top_stocks.map((s, i) => (
                      <tr key={s.code}>
                        <td>{i + 1}</td>
                        <td>{s.code}</td>
                        <td>{s.name}</td>
                        <td><b>{s.score_total}</b></td>
                        <td className="subtle" title={s.eps_growth_note ?? ''}>
                          {s.eps_growth != null ? `${(s.eps_growth * 100).toFixed(0)}%` : 'N/A'}
                        </td>
                        <td>{s.eligible ? '✅' : '–'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <p className="hint" style={{ marginTop: '0.6rem' }}>{data.note}</p>
        </div>
      )}
    </section>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export function RecommendationsPage() {
  const [data, setData] = useState<RecommendationsResponse | null>(null)
  const [busyCode, setBusyCode] = useState<string | null>(null)
  const [watchCodes, setWatchCodes] = useState<Set<string>>(new Set())
  const [tab, setTab] = useState<'standard' | 'king'>('standard')

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

    const refresh = () => {
      fetchJson<RecommendationsResponse>('/api/recommendations')
        .then((payload) => {
          if (!cancelled) setData(payload)
        })
        .catch(() => {
          if (!cancelled) setData(null)
        })
    }

    refresh()
    refreshWatchlist()
    const intervalId = window.setInterval(refresh, 30_000)
    const watchlistIntervalId = window.setInterval(refreshWatchlist, 30_000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
      window.clearInterval(watchlistIntervalId)
    }
  }, [])

  const items = useMemo(() => data?.items ?? [], [data])

  return (
    <>
      <header className="topbar glass">
        <div>
          <p className="top-label">Recommendations</p>
          <h2>추천 종목</h2>
          <p className="subtle">야간 배치로 계산된 당일 추천 (Top 30~200)</p>
        </div>
        <div className="status-pill">정렬: 종합 점수</div>
      </header>

      {/* 탭 선택 */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.7rem' }}>
        <button
          className={`pill-btn${tab === 'standard' ? ' active' : ''}`}
          onClick={() => setTab('standard')}
        >일반 추천</button>
        <button
          className={`pill-btn${tab === 'king' ? ' active' : ''}`}
          onClick={() => setTab('king')}
        >👑 KING</button>
      </div>

      {tab === 'king' ? (
        <KingPanel />
      ) : (
        <>
          <section className="panel glass reveal">
            <div className="panel-head">
              <h3>필터 / 정렬</h3>
            </div>
            <div className="form-row">
              <label>
                점수 범위
                <select>
                  <option>전체</option>
                  <option>50+</option>
                  <option>60+</option>
                  <option>70+</option>
                  <option>80+</option>
                </select>
              </label>
              <label>
                시가총액
                <select>
                  <option>전체</option>
                  <option>대형주</option>
                  <option>중형주</option>
                  <option>소형주</option>
                </select>
              </label>
              <label>
                업종
                <select>
                  <option>전체</option>
                  <option>반도체</option>
                  <option>자동차</option>
                  <option>금융</option>
                  <option>철강</option>
                </select>
              </label>
            </div>
            <div className="divider"></div>
            <div className="form-row">
              <label>
                날짜 선택
                <input type="date" defaultValue={data?.date ?? '2026-03-16'} />
              </label>
              <label>
                정렬
                <select>
                  <option>종합 점수 내림차순</option>
                  <option>현재가</option>
                  <option>등락률</option>
                </select>
              </label>
              <label>
                액션
                <button className="btn" type="button">
                  적용
                </button>
              </label>
            </div>
            <p className="hint" style={{ marginTop: 10 }}>
              총점 = 섹터(30) + 수급(30) + 성장(20) + 수익(10) + 기술(10)
            </p>
          </section>

          {data?.priceError && (
            <div className="banner warn" style={{ marginBottom: 12 }}>
              ⚠️ KIS 실시간 시세 조회 실패 — 현재가/등락률은 0으로 표시됩니다.
              <span className="hint" style={{ marginLeft: 8 }}>{data.priceError}</span>
            </div>
          )}

          <section className="panel glass reveal">
            <div className="panel-head">
              <h3>추천 목록</h3>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>순위</th>
                    <th>종목명</th>
                    <th>코드</th>
                    <th>점수</th>
                    <th>현재가</th>
                    <th>등락률</th>
                    <th>관심 추가</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => {
                    const alreadyAdded = watchCodes.has(item.code)
                    return (
                    <tr key={`${item.code}-${item.rank}`}>
                      <td>{item.rank}</td>
                      <td>{item.name}</td>
                      <td>{item.code}</td>
                      <td>
                        <b>{item.score}</b>
                      </td>
                      <td>{formatNumber(item.price)}</td>
                      <td className={item.changeRate >= 0 ? 'up' : 'down'}>{formatPercent(item.changeRate)}</td>
                      <td>
                        <button
                          className="btn secondary"
                          type="button"
                          disabled={busyCode === item.code || alreadyAdded}
                          title={alreadyAdded ? '이미 관심종목에 추가됨' : '관심종목에 추가'}
                          onClick={() => {
                            setBusyCode(item.code)
                            fetchJson<{ ok: boolean }>('/api/watchlist', {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({ code: item.code }),
                            })
                              .then(() => {
                                setWatchCodes((prev) => {
                                  const next = new Set(prev)
                                  next.add(item.code)
                                  return next
                                })
                              })
                              .catch(() => {})
                              .finally(() => setBusyCode(null))
                          }}
                        >
                          {alreadyAdded ? '[>]' : '[+]'}
                        </button>
                      </td>
                    </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </>
  )
}

