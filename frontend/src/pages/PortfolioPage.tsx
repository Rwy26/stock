import { useEffect, useMemo, useState } from 'react'
import { fetchJson } from '../lib/api'
import { formatNumber, formatKRW, formatPercent } from '../lib/format'

type PortfolioPosition = {
  name: string
  code: string
  qty: number
  avgBuy: number
  current: number
  buyDate: string
}

type PortfolioResponse = {
  asOf: string
  positions: PortfolioPosition[]
}

export function PortfolioPage() {
  const [data, setData] = useState<PortfolioResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchJson<PortfolioResponse>('/api/portfolio')
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

  const positions = data?.positions

  const summary = useMemo(() => {
    if (!positions || positions.length === 0) return null
    const invested = positions.reduce((acc, p) => acc + p.qty * p.avgBuy, 0)
    const evaluated = positions.reduce((acc, p) => acc + p.qty * p.current, 0)
    const pnl = evaluated - invested
    const rate = invested === 0 ? 0 : (pnl / invested) * 100
    return { invested, evaluated, pnl, rate }
  }, [positions])

  return (
    <>
      <header className="topbar glass">
        <div>
          <p className="top-label">Portfolio</p>
          <h2>포트폴리오</h2>
          <p className="subtle">현재가는 반드시 KIS 실시간 API 기준</p>
        </div>
        <div className="auth-actions">
          <button className="btn secondary" type="button">
            새로고침
          </button>
          <div className="status-pill">동기화 준비</div>
        </div>
      </header>

      <section className="panel glass reveal">
        <div className="panel-head">
          <h3>보유 종목</h3>
          <p className="subtle">포트폴리오 화면 새로고침 시 KIS 계좌와 동기화</p>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>종목명</th>
                <th>수량</th>
                <th>평균 매수가</th>
                <th>현재가</th>
                <th>평가금액</th>
                <th>손익금</th>
                <th>수익률</th>
                <th>매수일</th>
              </tr>
            </thead>
            <tbody>
              {(positions ?? [])
                .slice(0, 50)
                .map((p) => {
                  const evaluated = p.qty * p.current
                  const pnl = (p.current - p.avgBuy) * p.qty
                  const rate = p.avgBuy === 0 ? 0 : ((p.current - p.avgBuy) / p.avgBuy) * 100
                  const pnlClass = pnl >= 0 ? 'up' : 'down'
                  const rateClass = rate >= 0 ? 'up' : 'down'
                  return (
                    <tr key={p.code}>
                      <td>{p.name}</td>
                      <td>{formatNumber(p.qty)}</td>
                      <td>{formatNumber(p.avgBuy)}</td>
                      <td>{formatNumber(p.current)}</td>
                      <td>{formatNumber(evaluated)}</td>
                      <td className={pnlClass}>{`${pnl >= 0 ? '+' : ''}${formatNumber(pnl)}`}</td>
                      <td className={rateClass}>{formatPercent(rate)}</td>
                      <td>{p.buyDate}</td>
                    </tr>
                  )
                })}
            </tbody>
          </table>
        </div>
        <div className="divider"></div>
        <p className="hint">주의: DB 일봉(daily_prices) 종가로 현재가를 대체하지 않습니다.</p>
      </section>

      <section className="two-col">
        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>자산 요약</h3>
          </div>
          <ul className="engine-list">
            <li>
              <span>총 평가금액</span>
              <b>{summary ? formatKRW(summary.evaluated) : '₩184,380,000'}</b>
            </li>
            <li>
              <span>총 투자금액</span>
              <b>{summary ? formatKRW(summary.invested) : '₩161,000,000'}</b>
            </li>
            <li>
              <span>평가손익</span>
              <b className={summary && summary.pnl < 0 ? 'down' : 'up'}>
                {summary ? `${summary.pnl >= 0 ? '+' : ''}${formatKRW(summary.pnl)}` : '+₩23,380,000'}
              </b>
            </li>
            <li>
              <span>예수금</span>
              <b>₩39,640,000</b>
            </li>
          </ul>
        </article>
        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>자산 추이 (30일)</h3>
          </div>
          <div className="chart-placeholder">Chart Placeholder</div>
          <p className="hint">Hover 시 상세 금액 표시 (실데이터 연동 예정)</p>
        </article>
      </section>
    </>
  )
}
