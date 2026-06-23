import { useEffect, useState } from 'react'
import { fetchJson, fetchSnapshot } from '../lib/api'
import { formatKRW, formatNumber, formatPercent } from '../lib/format'
import type { PortfolioResponse } from '../lib/types'
import { StatusChip } from '../components/StatusChip'
import { UsBondsChart } from '../components/UsBondsChart'
import { DxyChart } from '../components/DxyChart'
import { DevMonitor } from '../components/DevMonitor'

type DashboardResponse = {
  kpis: {
    totalValue: { amount: number; deltaPct: number }
    totalInvested: { amount: number; deltaPct: number }
    pnl: { amount: number; deltaPct: number }
    cash: { amount: number; label: string }
  }
  topRecommendations: Array<{ name: string; code: string; score: number }>
  automation?: {
    basic?: { on: boolean; label: string }
    sa?: { on: boolean; label: string }
    plus?: { on: boolean; label: string }
    svAgent?: { on: boolean; label: string }
  }
  kis?: { connected: boolean; label: string }
}

type RecommendationsSnapshot = {
  date: string
  items: Array<{ rank: number; name: string; code: string; score: number }>
}

type KisTokenStatusResponse = {
  ok: boolean
  hasProfile: boolean
  tradeType: '실계좌' | string
  expiresIn: number | null
  asOf: string
  error?: string
}


export function DashboardPage() {
  const [data, setData] = useState<DashboardResponse | null>(null)
  const [kisTokenLine, setKisTokenLine] = useState<string>('KIS 토큰: -')
  const [portfolio, setPortfolio] = useState<PortfolioResponse | null>(null)
  const [topRecs, setTopRecs] = useState<Array<{ name: string; code: string; score: number }>>([])

  useEffect(() => {
    let cancelled = false

    const refresh = () => {
      Promise.allSettled([
        fetchJson<DashboardResponse>('/api/dashboard'),
        fetchJson<KisTokenStatusResponse>('/api/kis/token-status'),
        fetchJson<PortfolioResponse>('/api/portfolio'),
      ]).then(([dashRes, tokenRes, pfRes]) => {
        if (cancelled) return

        if (dashRes.status === 'fulfilled') {
          setData(dashRes.value)
        } else {
          setData(null)
        }

        if (tokenRes.status === 'fulfilled') {
          const tokenStatus = tokenRes.value
          if (!tokenStatus.hasProfile) {
            setKisTokenLine('KIS 토큰: 설정 필요')
          } else if (tokenStatus.ok && typeof tokenStatus.expiresIn === 'number') {
            setKisTokenLine(tokenStatus.expiresIn <= 60 * 60 ? 'KIS 토큰: 만료 임박' : 'KIS 토큰: 정상')
          } else {
            setKisTokenLine('KIS 토큰: 오류')
          }
        } else {
          setKisTokenLine('KIS 토큰: -')
        }

        if (pfRes.status === 'fulfilled') {
          setPortfolio(pfRes.value)
        } else {
          setPortfolio(null)
        }
      })
    }

    refresh()
    const intervalId = window.setInterval(refresh, 30_000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [])

  // Top 추천: 정적 스냅샷(배치 생성) 차등 폴링 — 저빈도(일배치)이므로 30분.
  // 스냅샷 미존재/실패 시 fetchSnapshot 이 /api/public/recommendations 로 폴백.
  useEffect(() => {
    let cancelled = false
    const loadRecs = () => {
      fetchSnapshot<RecommendationsSnapshot>('dashboard-top-recommendations.json', '/api/public/recommendations')
        .then((d) => {
          if (cancelled) return
          setTopRecs((d.items ?? []).slice(0, 5).map((it) => ({ name: it.name, code: it.code, score: it.score })))
        })
        .catch(() => { /* silent — 패널은 빈 상태 유지 */ })
    }
    loadRecs()
    const id = window.setInterval(loadRecs, 30 * 60 * 1000)
    return () => { cancelled = true; window.clearInterval(id) }
  }, [])

  const kpis = data?.kpis
  const top = topRecs
  const automation = data?.automation
  const kisLabel = data?.kis?.label ?? 'KIS 연결 필요'
  const positions = portfolio?.positions ?? []

  return (
    <>
      <header className="topbar glass">
        <div>
          <p className="top-label">Production v1.0+</p>
          <h2>MOON STOCK AI 주식 분석 시스템</h2>
        </div>
        <div style={{ display: 'grid', justifyItems: 'end', gap: 6 }}>
          <div className="status-pill">{kisLabel}</div>
          <p className="hint" style={{ margin: 0 }}>
            {kisTokenLine}
          </p>
        </div>
      </header>

      <section className="dashboard-grid">
        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>자산 요약 (Asset Summary)</h3>
          </div>
          <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
            <div className="card gradient-a" style={{ boxShadow: 'none' }}>
              <h3>총 평가금액</h3>
              <p className="value">{kpis ? formatKRW(kpis.totalValue.amount) : '—'}</p>
              <span className={kpis && kpis.totalValue.deltaPct < 0 ? 'delta down' : 'delta up'}>
                {kpis ? formatPercent(kpis.totalValue.deltaPct) : '—'}
              </span>
            </div>
            <div className="card gradient-b" style={{ boxShadow: 'none' }}>
              <h3>총 투자금액</h3>
              <p className="value">{kpis ? formatKRW(kpis.totalInvested.amount) : '—'}</p>
              <span className={kpis && kpis.totalInvested.deltaPct < 0 ? 'delta down' : 'delta up'}>
                {kpis ? formatPercent(kpis.totalInvested.deltaPct) : '—'}
              </span>
            </div>
            <div className="card gradient-c" style={{ boxShadow: 'none' }}>
              <h3>수익금</h3>
              <p className="value">{kpis ? formatKRW(kpis.pnl.amount) : '—'}</p>
              <span className={kpis && kpis.pnl.deltaPct < 0 ? 'delta down' : 'delta up'}>
                {kpis ? formatPercent(kpis.pnl.deltaPct) : '—'}
              </span>
            </div>
            <div className="card gradient-d" style={{ boxShadow: 'none' }}>
              <h3>예수금</h3>
              <p className="value">{kpis ? formatKRW(kpis.cash.amount) : '—'}</p>
              <span className="delta">{kpis ? kpis.cash.label : '—'}</span>
            </div>
          </div>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>자산 추이 차트 (30일)</h3>
          </div>
          <div className="chart-placeholder">Asset Trend Chart Placeholder</div>
          <p className="hint" style={{ marginTop: 10 }}>
            날짜 hover 시 상세 금액 표시
          </p>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>자동매매 상태</h3>
          </div>
          <ul className="engine-list">
            <li>
              <span>일반 자동매매</span>
              <StatusChip on={!!automation?.basic?.on}>{automation?.basic?.label ?? '—'}</StatusChip>
            </li>
            <li>
              <span>SA 자동매매</span>
              <StatusChip on={!!automation?.sa?.on}>{automation?.sa?.label ?? '—'}</StatusChip>
            </li>
            <li>
              <span>Plus 자동매매</span>
              <StatusChip on={!!automation?.plus?.on}>{automation?.plus?.label ?? '—'}</StatusChip>
            </li>
            <li>
              <span>SV Agent</span>
              <StatusChip on={!!automation?.svAgent?.on}>{automation?.svAgent?.label ?? '—'}</StatusChip>
            </li>
          </ul>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>Top 추천 종목</h3>
          </div>
          <ol className="ranking">
            {(top ?? []).map((item) => (
              <li key={item.code}>
                <span>{item.name}</span>
                <b>{item.score}점</b>
              </li>
            ))}
          </ol>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>일봉 캔들 차트</h3>
            <p className="subtle">선택 종목: —</p>
          </div>
          <div className="chart-placeholder">Daily Candle Chart Placeholder</div>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>시장 지수 차트</h3>
            <p className="subtle">KOSPI / KOSDAQ 당일 분봉</p>
          </div>
          <div className="chart-placeholder">Market Index Chart Placeholder</div>
        </article>

        <article className="panel glass reveal" style={{ gridColumn: 'span 2' }}>
          <div className="panel-head">
            <h3>미 국채 금리</h3>
            <p className="subtle">10년물(파랑) · 30년물(주황) · 도미넌스 10Y/30Y(초록) — 일봉 72일</p>
          </div>
          <UsBondsChart />
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>달러 인덱스 (DXY)</h3>
            <p className="subtle">USD Index 일봉 72일</p>
          </div>
          <DxyChart />
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>보유 종목</h3>
            <p className="subtle">총 {formatNumber(positions.length)}종목</p>
          </div>

          {positions.length === 0 ? (
            <p className="subtle" style={{ marginTop: 10 }}>
              —
            </p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>종목</th>
                    <th>수량</th>
                    <th>평단</th>
                    <th>현재가</th>
                    <th>평가금액</th>
                    <th>손익금</th>
                    <th>수익률</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => {
                    const avg = Number(p.avgBuy || 0)
                    const cur = Number(p.current || 0)
                    const qty = Number(p.qty || 0)
                    const marketValue = cur > 0 && qty > 0 ? cur * qty : null
                    const costValue = avg > 0 && qty > 0 ? avg * qty : null
                    const pnlAmt = marketValue != null && costValue != null ? marketValue - costValue : null
                    const pnlPct = avg > 0 && cur > 0 ? ((cur - avg) / avg) * 100 : null
                    return (
                      <tr key={p.code}>
                        <td>{p.name}</td>
                        <td>{formatNumber(p.qty)}</td>
                        <td>{avg > 0 ? formatKRW(avg) : '—'}</td>
                        <td>{cur > 0 ? formatKRW(cur) : '—'}</td>
                        <td>{marketValue == null ? '—' : formatKRW(marketValue)}</td>
                        <td className={pnlAmt != null && pnlAmt < 0 ? 'down' : 'up'}>
                          {pnlAmt == null ? '—' : formatKRW(pnlAmt)}
                        </td>
                        <td className={pnlPct != null && pnlPct < 0 ? 'down' : 'up'}>
                          {pnlPct == null ? '—' : formatPercent(pnlPct)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </article>
        <DevMonitor />
      </section>
    </>
  )
}
