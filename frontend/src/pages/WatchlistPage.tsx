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

  const chartUrlForCode = (code: string) => {
    const safe = encodeURIComponent(code)
    return `https://finance.naver.com/item/main.naver?code=${safe}`
  }

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

      <section className="panel glass reveal">
        <div className="panel-head">
          <h3>목록</h3>
        </div>

        <div className="form-row" style={{ gridTemplateColumns: '1fr' }}>
          <label>
            종목 검색 후 추가
            <input placeholder="예: 삼성전자 / 005930" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
        </div>

        {searchRows.length > 0 && (
          <div className="table-wrap" style={{ marginTop: 10 }}>
            <table>
              <thead>
                <tr>
                  <th>검색 결과</th>
                  <th>현재가</th>
                  <th>등락률</th>
                  <th>추가</th>
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
                        <div className="subtle" style={{ marginTop: 2 }}>
                          {row.code}
                        </div>
                      </td>
                      <td>{formatNumber(row.price)}</td>
                      <td className={row.changeRate >= 0 ? 'up' : 'down'}>{formatPercent(row.changeRate)}</td>
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

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>종목명</th>
                <th>현재가</th>
                <th>등락률</th>
                <th>점수</th>
                <th>차트</th>
                <th>삭제</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.code}>
                  <td>
                    <div>
                      <b>{item.name}</b>
                    </div>
                    <div className="subtle" style={{ marginTop: 2 }}>
                      {item.code}
                    </div>
                  </td>
                  <td>{formatNumber(item.price)}</td>
                  <td className={item.changeRate >= 0 ? 'up' : 'down'}>{formatPercent(item.changeRate)}</td>
                  <td>
                    <b>{item.score}</b>
                  </td>
                  <td>
                    <a className="btn secondary" href={chartUrlForCode(item.code)} target="_blank" rel="noreferrer">
                      차트
                    </a>
                  </td>
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
        <p className="hint" style={{ marginTop: 10 }}>
          종목 클릭 시 상세 화면으로 이동 (연동 예정)
        </p>
      </section>
    </>
  )
}
