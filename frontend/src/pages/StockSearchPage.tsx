import { useEffect, useMemo, useState } from 'react'
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

type StockDetail = StockRow & {
  indicators: {
    value: number
    flow: number
    profit: number
    growth: number
    tech: number
  }
}

export function StockSearchPage() {
  const [q, setQ] = useState('')
  const [market, setMarket] = useState('KOSPI')
  const [sort, setSort] = useState('관련도')
  const [rows, setRows] = useState<StockRow[]>([])
  const [selected, setSelected] = useState<StockDetail | null>(null)
  const [watchlistBusy, setWatchlistBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetchJson<SearchResponse>(`/api/stocks/search?q=${encodeURIComponent(q)}&market=${encodeURIComponent(market)}&sort=${encodeURIComponent(sort)}`)
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
      fetchJson<SearchResponse>(`/api/stocks/search?q=${encodeURIComponent(q)}&market=${encodeURIComponent(market)}&sort=${encodeURIComponent(sort)}`)
        .then((payload) => setRows(payload.items))
        .catch(() => setRows([]))
    }, 200)
    return () => window.clearTimeout(handle)
  }, [q, market, sort])

  const detailIndicators = useMemo(() => {
    return (
      selected?.indicators ?? {
        value: 24,
        flow: 22,
        profit: 19,
        growth: 5,
        tech: 17,
      }
    )
  }, [selected])

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
              <b>{selected ? `${selected.name} (${selected.code})` : '삼성전자 (005930)'}</b>
            </li>
            <li>
              <span>현재가</span>
              <b>{selected ? formatNumber(selected.price) : '72,100'}</b>
            </li>
            <li>
              <span>등락률</span>
              <b className={selected && selected.changeRate < 0 ? 'down' : 'up'}>
                {selected ? formatPercent(selected.changeRate) : '+1.02%'}
              </b>
            </li>
            <li>
              <span>종합 점수</span>
              <b>{selected ? `${selected.score}점` : '91점'}</b>
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
                  <b>{detailIndicators.value}</b>
                </li>
                <li>
                  <span>수급(26)</span>
                  <b>{detailIndicators.flow}</b>
                </li>
                <li>
                  <span>수익(21)</span>
                  <b>{detailIndicators.profit}</b>
                </li>
                <li>
                  <span>성장(6)</span>
                  <b>{detailIndicators.growth}</b>
                </li>
                <li>
                  <span>기술(18)</span>
                  <b>{detailIndicators.tech}</b>
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
                disabled={!selected || watchlistBusy}
                onClick={() => {
                  if (!selected) return
                  setWatchlistBusy(true)
                  fetchJson<{ ok: boolean }>('/api/watchlist', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code: selected.code }),
                  })
                    .catch(() => {
                      // Keep UX minimal: no extra modals/toasts; button simply re-enables.
                    })
                    .finally(() => setWatchlistBusy(false))
                }}
              >
                ☆ 관심 추가
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
