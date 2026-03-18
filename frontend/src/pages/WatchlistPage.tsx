import { useEffect, useMemo, useState } from 'react'
import { fetchJson } from '../lib/api'
import { formatNumber, formatPercent } from '../lib/format'

type WatchItem = {
  name: string
  code: string
  price: number
  changeRate: number
  score: number
}

type WatchlistResponse = {
  items: WatchItem[]
}

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

export function WatchlistPage() {
  const [data, setData] = useState<WatchlistResponse | null>(null)
  const [busyCode, setBusyCode] = useState<string | null>(null)
  const [selectedCode, setSelectedCode] = useState<string | null>(null)

  const [q, setQ] = useState('')
  const [searchRows, setSearchRows] = useState<StockRow[]>([])
  const [addBusyCode, setAddBusyCode] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const refresh = () => {
      fetchJson<WatchlistResponse>('/api/watchlist')
        .then((payload) => {
          if (!cancelled) setData(payload)
        })
        .catch(() => {
          if (!cancelled) setData(null)
        })
    }

    refresh()
    const intervalId = window.setInterval(refresh, 30_000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [])

  const refresh = () => {
    fetchJson<WatchlistResponse>('/api/watchlist')
      .then((payload) => setData(payload))
      .catch(() => setData(null))
  }

  useEffect(() => {
    if (!q.trim()) {
      setSearchRows([])
      return
    }
    const handle = window.setTimeout(() => {
      fetchJson<SearchResponse>(
        `/api/stocks/search?q=${encodeURIComponent(q)}&market=${encodeURIComponent('ALL')}&sort=${encodeURIComponent('관련도')}`
      )
        .then((payload) => setSearchRows(payload.items.slice(0, 10)))
        .catch(() => setSearchRows([]))
    }, 200)
    return () => window.clearTimeout(handle)
  }, [q])

  const items = useMemo(() => data?.items ?? [], [data])
  const itemCodes = useMemo(() => new Set(items.map((x) => x.code)), [items])

  useEffect(() => {
    if (selectedCode) return
    if (items.length > 0) setSelectedCode(items[0].code)
  }, [items, selectedCode])

  const chartUrlForCode = (code: string) => {
    // TradingView KR stocks are generally available under the KRX: prefix.
    // Use the chart route so the user lands directly on an interactive chart.
    return `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(`KRX:${code}`)}`
  }

  const selectedItem = useMemo(() => {
    if (!selectedCode) return null
    return items.find((x) => x.code === selectedCode) ?? null
  }, [items, selectedCode])

  return (
    <>
      <header className="topbar glass">
        <div>
          <p className="top-label">Watchlist</p>
          <h2>관심 종목</h2>
          <p className="subtle">등록 종목의 현재가/등락률/점수 일괄 표시</p>
        </div>
        <div className="status-pill">총 {items.length}개</div>
      </header>

      <section className="watchlist-layout">
        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>관심 종목</h3>
          </div>

          <div className="form-row is-1col">
            <label>
              종목 검색 후 추가
              <input placeholder="예: 삼성전자 / 005930" value={q} onChange={(e) => setQ(e.target.value)} />
            </label>
          </div>

          {searchRows.length > 0 && (
            <div className="table-wrap watchlist-search-results">
              <table>
                <thead>
                  <tr>
                    <th>검색 결과</th>
                    <th className="watchlist-col-add">추가</th>
                  </tr>
                </thead>
                <tbody>
                  {searchRows.map((row) => {
                    const already = itemCodes.has(row.code)
                    return (
                      <tr key={`search-${row.code}`}>
                        <td>
                          <div>
                            <b>{row.name}</b>
                          </div>
                          <div className="subtle">
                            {row.code}
                          </div>
                        </td>
                        <td>
                          <button
                            className="btn"
                            type="button"
                            disabled={already || addBusyCode === row.code}
                            onClick={() => {
                              setAddBusyCode(row.code)
                              fetchJson<{ ok: boolean }>('/api/watchlist', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ code: row.code }),
                              })
                                .then(() => refresh())
                                .catch(() => {
                                  // Keep UX minimal: no extra toast.
                                })
                                .finally(() => setAddBusyCode(null))
                            }}
                          >
                            {already ? '추가됨' : '추가'}
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          <div className="divider"></div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>종목</th>
                  <th className="watchlist-col-price">현재가</th>
                  <th className="watchlist-col-change">등락률</th>
                  <th className="watchlist-col-delete">삭제</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.code}>
                    <td>
                      <a
                        href={chartUrlForCode(item.code)}
                        target="_blank"
                        rel="noreferrer"
                        onClick={() => setSelectedCode(item.code)}
                        className="watchlist-stock-link"
                        title="새 창으로 차트 열기"
                      >
                        <div>
                          <b>{item.name}</b>
                        </div>
                        <div className="subtle">
                          {item.code}
                        </div>
                      </a>
                    </td>
                    <td>{formatNumber(item.price)}</td>
                    <td className={item.changeRate >= 0 ? 'up' : 'down'}>{formatPercent(item.changeRate)}</td>
                    <td>
                      <button
                        className="btn secondary"
                        type="button"
                        disabled={busyCode === item.code}
                        onClick={() => {
                          setBusyCode(item.code)
                          fetchJson<{ ok: boolean }>(`/api/watchlist/${encodeURIComponent(item.code)}`, {
                            method: 'DELETE',
                          })
                            .then(() => refresh())
                            .catch(() => {
                              // Keep UX minimal: no extra toast; just re-enable.
                            })
                            .finally(() => setBusyCode(null))
                        }}
                      >
                        삭제
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="hint watchlist-hint">
            종목명 클릭 시 새 창으로 차트가 열립니다.
          </p>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>차트</h3>
            <p className="subtle">이 화면에서는 요약만 표시합니다</p>
          </div>

          <ul className="engine-list">
            <li>
              <span>선택 종목</span>
              <b>{selectedItem ? `${selectedItem.name} (${selectedItem.code})` : '—'}</b>
            </li>
            <li>
              <span>현재가</span>
              <b>{selectedItem ? formatNumber(selectedItem.price) : '—'}</b>
            </li>
            <li>
              <span>등락률</span>
              <b className={selectedItem && selectedItem.changeRate < 0 ? 'down' : 'up'}>
                {selectedItem ? formatPercent(selectedItem.changeRate) : '—'}
              </b>
            </li>
            <li>
              <span>점수</span>
              <b>{selectedItem ? `${selectedItem.score}` : '—'}</b>
            </li>
          </ul>

          <div className="divider"></div>

          <div className="chart-placeholder watchlist-chart-placeholder">
            Chart Placeholder
            <div className="subtle">종목명을 클릭하면 TradingView 차트가 새 창으로 열립니다.</div>
          </div>

          {selectedItem && (
            <div className="auth-actions">
              <a className="btn" href={chartUrlForCode(selectedItem.code)} target="_blank" rel="noreferrer">
                새 창으로 차트 열기
              </a>
            </div>
          )}
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>설정</h3>
            <p className="subtle">설정 내용은 추후 정리</p>
          </div>

          <div className="watchlist-settings-tabs">
            <button className="btn secondary" type="button">
              추천 전략
            </button>
            <button className="btn secondary" type="button">
              간편설정
            </button>
            <button className="btn secondary" type="button">
              상세설정
            </button>
          </div>

          <div className="divider"></div>

          <section className="panel watchlist-settings-card">
            <h3 className="watchlist-settings-title">DCA 자동매매 봇 설정창</h3>
            <p className="hint">(내용은 추후 정리)</p>
            <div className="divider"></div>
            <div className="form-row is-2col">
              <label>
                선택 종목
                <input value={selectedItem ? selectedItem.code : ''} placeholder="—" readOnly />
              </label>
              <label>
                방향
                <input value={selectedItem ? 'LONG' : ''} placeholder="—" readOnly />
              </label>
            </div>
            <button className="btn watchlist-settings-submit" type="button" disabled>
              선택하기
            </button>
          </section>
        </article>
      </section>
    </>
  )
}
