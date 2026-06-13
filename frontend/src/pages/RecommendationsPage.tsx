import { useEffect, useMemo, useState } from 'react'
import { fetchJson } from '../lib/api'
import { CAUTION_BANNER_STYLE } from '../lib/exclusion'
import type { OkOrCaution } from '../lib/exclusion'
import { formatNumber, formatPercent } from '../lib/format'
import type { WatchlistCodesResponse } from '../lib/types'

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

// ─── 시초가 갭 신호 types ───────────────────────────────────────────────────────

type GapSignalItem = {
  code: string
  name: string
  tier: string | null
  gapPct: number
  price: number | null
  open: number | null
  prevClose: number | null
  volume: number | null
  tradeValueKrw: number | null
  catalyst: string | null
  catalystType: string | null
  catalystVerified: boolean
  catalystSource: string
  headlines: string[]
  priceVerified: boolean
  disclaimer: string
}

type GapSignalResponse = {
  date: string | null
  items: GapSignalItem[]
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

// ─── 시초가 갭 신호 Panel ──────────────────────────────────────────────────────

const TIER_STYLE: Record<string, { bg: string; fg: string }> = {
  A: { bg: 'rgba(34,197,94,0.16)', fg: '#22c55e' },
  B: { bg: 'rgba(251,191,36,0.16)', fg: '#fbbf24' },
  C: { bg: 'rgba(148,163,184,0.16)', fg: '#94a3b8' },
}

function GapSignalPanel() {
  const [data, setData] = useState<GapSignalResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    fetchJson<GapSignalResponse>('/api/recommendations/gap-signal')
      .then((r) => setData(r))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }

  // 초기 로드 — 효과 내 동기 setState 회피(비동기 콜백에서만 갱신)
  useEffect(() => {
    let cancelled = false
    fetchJson<GapSignalResponse>('/api/recommendations/gap-signal')
      .then((r) => { if (!cancelled) setData(r) })
      .catch((e) => { if (!cancelled) setError(String(e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const items = data?.items ?? []
  const fmtValue = (v: number | null) =>
    v == null ? 'N/A' : `${formatNumber(Math.round(v / 1e8))}억`

  return (
    <section className="panel glass reveal">
      <div className="panel-head" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3>📈 시초가 갭 신호 {data?.date ? `(${data.date})` : ''}</h3>
        <button className="btn secondary" onClick={load} disabled={loading}>
          {loading ? '불러오는 중…' : '새로고침'}
        </button>
      </div>

      {/* 프레이밍: 스크리닝 신호이며 매수추천이 아님 */}
      <div style={CAUTION_BANNER_STYLE}>
        <span>⚠️</span>
        <span>
          <b>시초가 갭 신호(스크리닝)</b> — 매수추천이 아닙니다. 촉매는 네이버 뉴스 LLM 요약으로
          <b> 검증되지 않은 참고치</b>이며, 근거 헤드라인과 함께 표시됩니다. 갭·가격은 네이버 siseJson 기준입니다.
        </span>
      </div>

      {error && <div className="banner warn" style={{ margin: '0.5rem 1rem' }}>{error}</div>}

      {!loading && items.length === 0 && (
        <p className="subtle" style={{ padding: '0.8rem 1rem', margin: 0 }}>
          {data?.note ?? '갭 신호 데이터가 없습니다. 장 시작(09:05) 이후 적재됩니다.'}
        </p>
      )}

      {items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>등급</th>
                <th>종목명</th>
                <th>코드</th>
                <th>시초가 갭</th>
                <th>시가</th>
                <th>전일종가</th>
                <th>거래대금</th>
                <th>촉매(미검증)</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => {
                const ts = TIER_STYLE[it.tier ?? 'C'] ?? TIER_STYLE.C
                return (
                  <tr key={it.code}>
                    <td>
                      <span style={{
                        display: 'inline-block', minWidth: 22, textAlign: 'center',
                        padding: '1px 7px', borderRadius: 6, fontWeight: 700,
                        background: ts.bg, color: ts.fg,
                      }}>{it.tier ?? '–'}</span>
                    </td>
                    <td>
                      {it.name}
                      {!it.priceVerified && (
                        <span className="subtle" title="네이버 siseJson 재확인 보류 — 스캐너 값" style={{ marginLeft: 6 }}>⚠︎</span>
                      )}
                    </td>
                    <td>{it.code}</td>
                    <td className={it.gapPct >= 0 ? 'up' : 'down'}><b>{formatPercent(it.gapPct)}</b></td>
                    <td>{it.open != null ? formatNumber(it.open) : 'N/A'}</td>
                    <td>{it.prevClose != null ? formatNumber(it.prevClose) : 'N/A'}</td>
                    <td>{fmtValue(it.tradeValueKrw)}</td>
                    <td style={{ maxWidth: 320 }}>
                      {it.catalyst ? (
                        <span title={it.headlines.join('\n')}>
                          <span style={{
                            fontSize: '0.66rem', fontWeight: 700, color: '#fbbf24',
                            border: '1px solid rgba(251,191,36,0.4)', borderRadius: 5,
                            padding: '0px 5px', marginRight: 6,
                          }}>미검증</span>
                          {it.catalyst}
                        </span>
                      ) : (
                        <span className="subtle">촉매 불명</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {data && (
        <p className="hint" style={{ marginTop: '0.6rem' }}>
          {data.note} · 등급 A/B/C = 갭%·거래대금·촉매유무 결정론 산출 · 종목명에 ⚠︎ 는 siseJson 재확인 보류.
        </p>
      )}
    </section>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export function RecommendationsPage() {
  const [data, setData] = useState<RecommendationsResponse | null>(null)
  const [busyCode, setBusyCode] = useState<string | null>(null)
  const [watchCodes, setWatchCodes] = useState<Set<string>>(new Set())
  const [tab, setTab] = useState<'standard' | 'king' | 'gap'>('standard')

  useEffect(() => {
    let cancelled = false

    const refreshWatchlist = () => {
      fetchJson<WatchlistCodesResponse>('/api/watchlist')
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
        <button
          className={`pill-btn${tab === 'gap' ? ' active' : ''}`}
          onClick={() => setTab('gap')}
        >📈 시초가 갭 신호</button>
      </div>

      {tab === 'king' ? (
        <KingPanel />
      ) : tab === 'gap' ? (
        <GapSignalPanel />
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
                            fetchJson<OkOrCaution>('/api/watchlist', {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({ code: item.code }),
                            })
                              .then((resp) => {
                                if (resp.excluded) {
                                  // 거래 제외 종목 — 등록 대신 '투자 주의' 메시지 발행
                                  window.alert(resp.message ?? '[투자 주의] 거래 제외 종목입니다.')
                                  return
                                }
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
                          {alreadyAdded ? '[v]' : '[+]'}
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

