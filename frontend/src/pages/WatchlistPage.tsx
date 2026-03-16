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

const fallbackItems: WatchItem[] = [
  { name: '삼성전자', code: '005930', price: 72100, changeRate: 1.02, score: 91 },
  { name: 'SK하이닉스', code: '000660', price: 210500, changeRate: 2.12, score: 88 },
  { name: '현대차', code: '005380', price: 221500, changeRate: -0.35, score: 85 },
]

export function WatchlistPage() {
  const [data, setData] = useState<WatchlistResponse | null>(null)
  const [busyCode, setBusyCode] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchJson<WatchlistResponse>('/api/watchlist')
      .then((payload) => {
        if (!cancelled) setData(payload)
      })
      .catch(() => {
        if (!cancelled) setData(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const refresh = () => {
    fetchJson<WatchlistResponse>('/api/watchlist')
      .then((payload) => setData(payload))
      .catch(() => setData(null))
  }

  const items = useMemo(() => data?.items ?? fallbackItems, [data])

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
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>종목명</th>
                <th>코드</th>
                <th>현재가</th>
                <th>등락률</th>
                <th>점수</th>
                <th>삭제</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.code}>
                  <td>{item.name}</td>
                  <td>{item.code}</td>
                  <td>{formatNumber(item.price)}</td>
                  <td className={item.changeRate >= 0 ? 'up' : 'down'}>{formatPercent(item.changeRate)}</td>
                  <td>
                    <b>{item.score}</b>
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
