import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchJson } from '../lib/api'
import { CompassReport } from '../components/CompassReport'

// ─── Types ───────────────────────────────────────────────────────────────────

interface CacheItem {
  stock_code: string
  stock_name?: string | null
  analyzed_at?: string | null
  signal?: string | null
  confidence?: number | null
  upside_probability?: number | null
  summary?: string | null
  target_price?: string | null
  stop_loss?: string | null
  entry_price?: string | null
  image_hashes?: string[] | null
}

interface CacheDetailResult {
  stock_code: string
  stock_name?: string | null
  analyzed_at?: string | null
  signal?: string | null
  confidence?: number | null
  upside_probability?: number | null
  image_hashes?: string[] | null
  result_json?: Record<string, unknown> | null
}

interface CacheResponse {
  items: CacheItem[]
  total: number
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const SIGNAL_LABELS: Record<string, string> = {
  STRONG_BUY: '🚀 강력 매수',
  BUY:        '📈 매수',
  HOLD:       '🔄 관망',
  SELL:       '📉 매도',
  STRONG_SELL:'🔻 강력 매도',
}

const SIGNAL_CLASSES: Record<string, string> = {
  STRONG_BUY: 'signal-tag strong-buy',
  BUY:        'signal-tag buy',
  HOLD:       'signal-tag hold',
  SELL:       'signal-tag sell',
  STRONG_SELL:'signal-tag strong-sell',
}

function formatAt(iso?: string | null) {
  if (!iso) return '–'
  try {
    // analyzed_at는 UTC(naive)로 저장됨 — 타임존 표기 없으면 'Z'를 붙여 UTC로 해석 후 KST 변환
    const hasTz = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso)
    const d = new Date(hasTz ? iso : iso + 'Z')
    return d.toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch { return iso }
}

// ─── Component ───────────────────────────────────────────────────────────────

export function AiCachePage() {
  const [items, setItems] = useState<CacheItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<CacheDetailResult | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [filterSignal, setFilterSignal] = useState<string>('ALL')
  const [query, setQuery] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    fetchJson<CacheResponse>('/api/ai/analysis-cache')
      .then((r) => { setItems(r.items); setError(null) })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => void load(), [])

  const openDetail = (code: string) => {
    setDetailLoading(true)
    fetchJson<CacheDetailResult>(`/api/ai/analysis-cache/${code}`)
      .then((r) => setSelected(r))
      .catch(() => setSelected(null))
      .finally(() => setDetailLoading(false))
  }

  // 시그널 필터만 목록을 좁힘. 검색어는 행을 숨기지 않고 '매칭 행 강조+스크롤'로만 동작.
  const filtered = filterSignal === 'ALL' ? items : items.filter((i) => i.signal === filterSignal)
  const q = query.trim().toLowerCase()
  const isMatch = (i: CacheItem) =>
    !!q && (String(i.stock_code).toLowerCase().includes(q) || String(i.stock_name ?? '').toLowerCase().includes(q))
  const rowRefs = useRef<Record<string, HTMLTableRowElement | null>>({})

  // 검색어 변경 → 첫 매칭 행으로 스크롤 (클릭은 사용자가 직접)
  useEffect(() => {
    if (!q) return
    const first = filtered.find(isMatch)
    if (first) {
      const el = rowRefs.current[first.stock_code]
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, filterSignal])

  return (
    <>
      <style>{`
        @keyframes searchBlink {
          0%, 100% { background: rgba(96,165,250,0.04); box-shadow: inset 3px 0 0 rgba(96,165,250,0); }
          50%      { background: rgba(96,165,250,0.28); box-shadow: inset 3px 0 0 #60a5fa; }
        }
        tr.search-blink { animation: searchBlink 1s ease-in-out infinite; }
      `}</style>
      <header className="topbar glass">
        <div>
          <p className="top-label">AI Analysis History</p>
          <h2>AI 분석 이력</h2>
          <p className="subtle">분석 완료된 종목 — signal 강도 순 정렬 (STRONG_BUY 우선)</p>
        </div>
        <div className="status-pill">{items.length}개 종목</div>
      </header>

      {/* 검색 + 필터 */}
      <section className="panel glass reveal" style={{ marginBottom: '0.8rem' }}>
        <div className="panel-head"><h3>종목 검색 · Signal 필터</h3></div>
        <div style={{ padding: '0.6rem 1rem 0' }}>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="🔍 종목명 또는 코드 검색 (예: 삼성전자, 005930)"
            style={{
              width: '100%', boxSizing: 'border-box', padding: '9px 12px', borderRadius: 8,
              border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.05)', color: '#f1f5f9',
            }}
          />
        </div>
        <div className="filter-row" style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center', padding: '0.6rem 1rem' }}>
          {['ALL', 'STRONG_BUY', 'BUY', 'HOLD', 'SELL', 'STRONG_SELL'].map((s) => (
            <button
              key={s}
              className={`pill-btn${filterSignal === s ? ' active' : ''}`}
              onClick={() => setFilterSignal(s)}
            >
              {s === 'ALL' ? '전체' : SIGNAL_LABELS[s] ?? s}
            </button>
          ))}
          <span style={{ marginLeft: 'auto', fontSize: '0.8rem', color: 'var(--muted)' }}>{filtered.length}건</span>
        </div>
      </section>

      {/* 에러 / 로딩 */}
      {error && <div className="banner warn">{error}</div>}

      {loading ? (
        <div className="panel glass" style={{ padding: '2rem', textAlign: 'center', color: 'var(--muted)' }}>
          AI 분석 이력 불러오는 중…
        </div>
      ) : filtered.length === 0 ? (
        <div className="panel glass" style={{ padding: '2rem', textAlign: 'center', color: 'var(--muted)' }}>
          분석 이력이 없습니다.{' '}
          <a href="/ai-chart" style={{ color: 'var(--accent)' }}>AI 종목 분석</a>에서 차트 이미지를 업로드하면 자동 저장됩니다.
        </div>
      ) : (
        <div className="rec-table-wrap reveal">
          <table className="rec-table">
            <thead>
              <tr>
                <th>#</th>
                <th>코드</th>
                <th>종목명</th>
                <th>Signal</th>
                <th>신뢰도</th>
                <th>상승확률</th>
                <th>목표가</th>
                <th>손절가</th>
                <th>요약</th>
                <th>분석일시</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item, idx) => {
                const matched = isMatch(item)
                return (
                <tr
                  key={item.stock_code}
                  ref={(el) => { rowRefs.current[item.stock_code] = el }}
                  className={`rec-row clickable${matched ? ' search-blink' : ''}`}
                  style={{ cursor: 'pointer' }}
                  onClick={() => openDetail(item.stock_code)}
                >
                  <td className="rank-cell">{idx + 1}</td>
                  <td className="code-cell">{item.stock_code}</td>
                  <td>{item.stock_name ?? '–'}</td>
                  <td>
                    <span className={SIGNAL_CLASSES[item.signal ?? ''] ?? 'signal-tag'}>
                      {SIGNAL_LABELS[item.signal ?? ''] ?? item.signal ?? '–'}
                    </span>
                  </td>
                  <td>{item.confidence != null ? `${item.confidence.toFixed(0)}%` : '–'}</td>
                  <td>{item.upside_probability != null ? `${item.upside_probability.toFixed(0)}%` : '–'}</td>
                  <td>{item.target_price ?? '–'}</td>
                  <td>{item.stop_loss ?? '–'}</td>
                  <td className="summary-cell" style={{ maxWidth: 220, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {item.summary ?? '–'}
                  </td>
                  <td className="subtle">{formatAt(item.analyzed_at)}</td>
                </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 상세 모달 */}
      {(selected || detailLoading) && (
        <div
          className="modal-backdrop"
          onClick={() => setSelected(null)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <div
            className="panel glass"
            style={{ maxWidth: 700, width: '94%', maxHeight: '85vh', overflowY: 'auto', padding: '1.5rem', position: 'relative' }}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              style={{ position: 'absolute', top: 12, right: 14, background: 'none', border: 'none', color: 'var(--muted)', fontSize: '1.3rem', cursor: 'pointer' }}
              onClick={() => setSelected(null)}
            >×</button>

            {detailLoading ? (
              <p style={{ textAlign: 'center', color: 'var(--muted)' }}>상세 불러오는 중…</p>
            ) : selected ? (
              selected.result_json && (selected.result_json as Record<string, unknown>).source === 'market-compass-12stage' ? (
                /* 시장 나침반 12단계 → 뉴스레터 스타일 리포트 */
                <CompassReport data={selected.result_json as Record<string, never>} />
              ) : (
                <>
                  <h3 style={{ marginBottom: '0.8rem' }}>
                    {selected.stock_name ?? selected.stock_code}&nbsp;
                    <span style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>({selected.stock_code})</span>
                  </h3>
                  <p style={{ marginBottom: '0.3rem' }}>
                    <span className={SIGNAL_CLASSES[selected.signal ?? ''] ?? 'signal-tag'}>
                      {SIGNAL_LABELS[selected.signal ?? ''] ?? selected.signal ?? '–'}
                    </span>
                    {selected.confidence != null && (
                      <span style={{ marginLeft: 8, color: 'var(--muted)', fontSize: '0.85rem' }}>신뢰도 {selected.confidence.toFixed(0)}%</span>
                    )}
                  </p>
                  <p className="subtle" style={{ marginBottom: '1rem' }}>분석일시: {formatAt(selected.analyzed_at)}</p>

                  {selected.result_json && (
                    <pre style={{ background: 'var(--surface)', padding: '1rem', borderRadius: 8, fontSize: '0.78rem', overflowX: 'auto', whiteSpace: 'pre-wrap' }}>
                      {JSON.stringify(selected.result_json, null, 2)}
                    </pre>
                  )}
                </>
              )
            ) : null}
          </div>
        </div>
      )}
    </>
  )
}
