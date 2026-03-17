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
}

export function RecommendationsPage() {
  const [data, setData] = useState<RecommendationsResponse | null>(null)
  const [busyCode, setBusyCode] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

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
    const intervalId = window.setInterval(refresh, 30_000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
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
          총점 = 가치(29) + 수급(26) + 수익(21) + 성장(6) + 기술(18)
        </p>
      </section>

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
              {items.map((item) => (
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
                      disabled={busyCode === item.code}
                      onClick={() => {
                        setBusyCode(item.code)
                        fetchJson<{ ok: boolean }>('/api/watchlist', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ code: item.code }),
                        })
                          .catch(() => {
                            // Keep UX minimal: no extra toast.
                          })
                          .finally(() => setBusyCode(null))
                      }}
                    >
                      [+]
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}
