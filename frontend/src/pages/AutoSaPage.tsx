import { useEffect, useMemo, useState } from 'react'
import { fetchJson } from '../lib/api'
import { formatNumber, formatPercent } from '../lib/format'

type SaTab = 'status' | 'logs' | 'alerts' | 'signals' | 'daily' | 'snapshots'

type SaPositionItem = {
  id: number
  name: string
  code: string
  qty: number
  avgBuy: number
  current: number
  pnlPct: number | null
  openedAt: string | null
  closedAt: string | null
}

type SaPositionsResponse = {
  asOf: string
  items: SaPositionItem[]
}

type SaLogItem = {
  id: number
  at: string | null
  action: string
  name: string
  code: string
  qty: number | null
  price: number | null
  message: string | null
}

type SaLogsResponse = {
  asOf: string
  items: SaLogItem[]
}

type SaConfigResponse = {
  enabled: boolean
  config: unknown
  updatedAt: string | null
}

type SaConfigForm = {
  totalBudget: string
  perStockBudget: string
  maxPositions: number
  minSaScore: number
  cautionMinScore: number
  scanRankRange: number
  weightObv: number
  weightMfi: number
  weightPattern: number
  maxHoldingDays: number
  volatilityAdjust: boolean
}

function formatHm(value: string | null): string {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '-'
  return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function formatSaAction(action: string): string {
  const a = (action || '').toLowerCase()
  if (a === 'buy') return '매수'
  if (a === 'sell') return '매도'
  if (a === 'stoploss') return '손절'
  if (a === 'takeprofit') return '익절'
  return action
}

function isSameLocalDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

export function AutoSaPage() {
  const [activeTab, setActiveTab] = useState<SaTab>('status')
  const [positions, setPositions] = useState<SaPositionItem[] | null>(null)
  const [logs, setLogs] = useState<SaLogItem[] | null>(null)
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)

  const [form, setForm] = useState<SaConfigForm>({
    totalBudget: '',
    perStockBudget: '',
    maxPositions: 5,
    minSaScore: 50,
    cautionMinScore: 55,
    scanRankRange: 200,
    weightObv: 1.0,
    weightMfi: 1.0,
    weightPattern: 1.0,
    maxHoldingDays: 10,
    volatilityAdjust: true,
  })

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const [posRes, logRes] = await Promise.all([
          fetchJson<SaPositionsResponse>('/api/automation/sa/positions'),
          fetchJson<SaLogsResponse>('/api/automation/sa/logs?limit=500'),
        ])
        if (cancelled) return
        setPositions(posRes.items)
        setLogs(logRes.items)
      } catch {
        if (cancelled) return
        setPositions([])
        setLogs([])
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    fetchJson<SaConfigResponse>('/api/automation/sa')
      .then((cfg) => {
        if (cancelled) return
        setEnabled(Boolean(cfg.enabled))

        const cfgObj = cfg.config && typeof cfg.config === 'object' ? (cfg.config as Record<string, unknown>) : null
        if (!cfgObj) return
        setForm((prev) => ({
          ...prev,
          totalBudget: typeof cfgObj.totalBudget === 'string' ? cfgObj.totalBudget : prev.totalBudget,
          perStockBudget: typeof cfgObj.perStockBudget === 'string' ? cfgObj.perStockBudget : prev.perStockBudget,
          maxPositions: typeof cfgObj.maxPositions === 'number' && Number.isFinite(cfgObj.maxPositions) ? cfgObj.maxPositions : prev.maxPositions,
          minSaScore: typeof cfgObj.minSaScore === 'number' && Number.isFinite(cfgObj.minSaScore) ? cfgObj.minSaScore : prev.minSaScore,
          cautionMinScore:
            typeof cfgObj.cautionMinScore === 'number' && Number.isFinite(cfgObj.cautionMinScore)
              ? cfgObj.cautionMinScore
              : prev.cautionMinScore,
          scanRankRange: typeof cfgObj.scanRankRange === 'number' && Number.isFinite(cfgObj.scanRankRange) ? cfgObj.scanRankRange : prev.scanRankRange,
          weightObv: typeof cfgObj.weightObv === 'number' && Number.isFinite(cfgObj.weightObv) ? cfgObj.weightObv : prev.weightObv,
          weightMfi: typeof cfgObj.weightMfi === 'number' && Number.isFinite(cfgObj.weightMfi) ? cfgObj.weightMfi : prev.weightMfi,
          weightPattern:
            typeof cfgObj.weightPattern === 'number' && Number.isFinite(cfgObj.weightPattern) ? cfgObj.weightPattern : prev.weightPattern,
          maxHoldingDays:
            typeof cfgObj.maxHoldingDays === 'number' && Number.isFinite(cfgObj.maxHoldingDays) ? cfgObj.maxHoldingDays : prev.maxHoldingDays,
          volatilityAdjust: typeof cfgObj.volatilityAdjust === 'boolean' ? cfgObj.volatilityAdjust : prev.volatilityAdjust,
        }))
      })
      .catch(() => {
        if (!cancelled) setEnabled(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const save = () => {
    if (busy) return
    setBusy(true)

    const payload = {
      enabled: Boolean(enabled),
      config: {
        totalBudget: form.totalBudget,
        perStockBudget: form.perStockBudget,
        maxPositions: form.maxPositions,
        minSaScore: form.minSaScore,
        cautionMinScore: form.cautionMinScore,
        scanRankRange: form.scanRankRange,
        weightObv: form.weightObv,
        weightMfi: form.weightMfi,
        weightPattern: form.weightPattern,
        maxHoldingDays: form.maxHoldingDays,
        volatilityAdjust: form.volatilityAdjust,
      },
    }

    fetchJson<{ ok: boolean }>('/api/automation/sa', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .catch(() => {
        // Keep UX minimal: no extra modals/toasts.
      })
      .finally(() => setBusy(false))
  }

  const positionRows = useMemo(() => positions ?? [], [positions])
  const logRows = useMemo(() => logs ?? [], [logs])
  const todayTradeCount = useMemo(() => {
    if (!logs) return null
    const now = new Date()
    let count = 0
    for (const row of logs) {
      if (!row.at) continue
      const d = new Date(row.at)
      if (Number.isNaN(d.getTime())) continue
      if (isSameLocalDay(d, now)) count += 1
    }
    return count
  }, [logs])

  return (
    <>
      <header className="topbar glass">
        <div>
          <p className="top-label">Smart Agent</p>
          <h2>SA 자동매매</h2>
          <p className="subtle">골든크로스 예측 + OBV/MFI/매집패턴 가중치 기반</p>
        </div>
        <div className="status-pill">모니터링 1분</div>
      </header>

      <section className="panel glass reveal">
        <div className="panel-head">
          <h3>설정</h3>
        </div>
        <div className="settings-grid">
          <label>
            상태
            <select
              value={enabled ? 'On' : 'Off'}
              onChange={(e) => {
                const v = e.target.value
                setEnabled(v === 'On')
              }}
            >
              <option value="Off">Off</option>
              <option value="On">On</option>
            </select>
          </label>
          <label>
            총 예산
            <input
              placeholder="예: 10000000"
              inputMode="numeric"
              value={form.totalBudget}
              onChange={(e) => setForm((p) => ({ ...p, totalBudget: e.target.value.replace(/,/g, '') }))}
            />
          </label>
          <label>
            종목당 예산
            <input
              placeholder="예: 2000000"
              inputMode="numeric"
              value={form.perStockBudget}
              onChange={(e) => setForm((p) => ({ ...p, perStockBudget: e.target.value.replace(/,/g, '') }))}
            />
          </label>
          <label>
            최대 종목 수
            <input type="number" value={form.maxPositions} onChange={(e) => setForm((p) => ({ ...p, maxPositions: Number(e.target.value) }))} />
          </label>
          <label>
            최소 SA 점수
            <input type="number" value={form.minSaScore} onChange={(e) => setForm((p) => ({ ...p, minSaScore: Number(e.target.value) }))} />
          </label>
          <label>
            주의 모드 최소 점수
            <input
              type="number"
              value={form.cautionMinScore}
              onChange={(e) => setForm((p) => ({ ...p, cautionMinScore: Number(e.target.value) }))}
            />
          </label>
          <label>
            탐색 순위 범위
            <input type="number" value={form.scanRankRange} onChange={(e) => setForm((p) => ({ ...p, scanRankRange: Number(e.target.value) }))} />
          </label>
          <label>
            OBV 가중치
            <input
              type="number"
              step={0.1}
              value={form.weightObv}
              onChange={(e) => setForm((p) => ({ ...p, weightObv: Number(e.target.value) }))}
            />
          </label>
          <label>
            MFI 가중치
            <input
              type="number"
              step={0.1}
              value={form.weightMfi}
              onChange={(e) => setForm((p) => ({ ...p, weightMfi: Number(e.target.value) }))}
            />
          </label>
          <label>
            패턴 가중치
            <input
              type="number"
              step={0.1}
              value={form.weightPattern}
              onChange={(e) => setForm((p) => ({ ...p, weightPattern: Number(e.target.value) }))}
            />
          </label>
          <label>
            최대 보유일
            <input
              type="number"
              value={form.maxHoldingDays}
              onChange={(e) => setForm((p) => ({ ...p, maxHoldingDays: Number(e.target.value) }))}
            />
          </label>
          <label>
            변동성 조정
            <select
              value={form.volatilityAdjust ? 'On' : 'Off'}
              onChange={(e) => setForm((p) => ({ ...p, volatilityAdjust: e.target.value === 'On' }))}
            >
              <option value="On">On</option>
              <option value="Off">Off</option>
            </select>
          </label>
        </div>
        <div className="divider"></div>
        <button className="btn" type="button" disabled={busy} onClick={save}>
          저장
        </button>
        <p className="hint" style={{ marginTop: 10 }}>
          금요일 15:15 이후 자동 청산 / 매일 15:20 마감 청산
        </p>
      </section>

      <section className="panel glass reveal">
        <div className="panel-head">
          <h3>탭</h3>
        </div>
        <div className="tabs" data-tabs="sa">
          <button className={`tab${activeTab === 'status' ? ' active' : ''}`} type="button" data-tab="status" onClick={() => setActiveTab('status')}>
            현황
          </button>
          <button className={`tab${activeTab === 'logs' ? ' active' : ''}`} type="button" data-tab="logs" onClick={() => setActiveTab('logs')}>
            매매 로그
          </button>
          <button className={`tab${activeTab === 'alerts' ? ' active' : ''}`} type="button" data-tab="alerts" onClick={() => setActiveTab('alerts')}>
            알림
          </button>
          <button className={`tab${activeTab === 'signals' ? ' active' : ''}`} type="button" data-tab="signals" onClick={() => setActiveTab('signals')}>
            시그널
          </button>
          <button className={`tab${activeTab === 'daily' ? ' active' : ''}`} type="button" data-tab="daily" onClick={() => setActiveTab('daily')}>
            일별 성과
          </button>
          <button className={`tab${activeTab === 'snapshots' ? ' active' : ''}`} type="button" data-tab="snapshots" onClick={() => setActiveTab('snapshots')}>
            계좌 스냅샷
          </button>
        </div>

        <div className="tab-panels" data-tab-panels="sa">
          <div className={`tab-panel${activeTab === 'status' ? ' active' : ''}`} data-tab-panel="status">
            <div className="two-col" style={{ gridTemplateColumns: '1.2fr 0.8fr' }}>
              <article className="panel glass" style={{ boxShadow: 'none' }}>
                <div className="panel-head">
                  <h3>보유 포지션</h3>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>종목명</th>
                        <th>수량</th>
                        <th>매수가</th>
                        <th>현재가</th>
                        <th>수익률</th>
                        <th>골든크로스</th>
                      </tr>
                    </thead>
                    <tbody>
                      {positions === null ? (
                        <tr>
                          <td colSpan={6} className="subtle">
                            불러오는 중…
                          </td>
                        </tr>
                      ) : positionRows.length === 0 ? (
                        <tr>
                          <td colSpan={6} className="subtle">
                            보유 포지션이 없습니다.
                          </td>
                        </tr>
                      ) : (
                        positionRows.map((row) => (
                          <tr key={row.id}>
                            <td>{row.name}</td>
                            <td>{formatNumber(row.qty)}</td>
                            <td>{row.avgBuy ? formatNumber(row.avgBuy) : '-'}</td>
                            <td>{row.current ? formatNumber(row.current) : '-'}</td>
                            <td className={row.pnlPct != null && row.pnlPct >= 0 ? 'up' : 'down'}>
                              {row.pnlPct == null ? '-' : formatPercent(row.pnlPct)}
                            </td>
                            <td>-</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </article>
              <article className="panel glass" style={{ boxShadow: 'none' }}>
                <div className="panel-head">
                  <h3>요약</h3>
                </div>
                <ul className="engine-list">
                  <li>
                    <span>엔진</span>
                    <span className={`chip ${enabled ? 'on' : 'off'}`}>{enabled ? 'ON' : 'OFF'}</span>
                  </li>
                  <li>
                    <span>오늘 거래</span>
                    <b>{todayTradeCount == null ? '-' : formatNumber(todayTradeCount)}</b>
                  </li>
                  <li>
                    <span>손절</span>
                    <b>-5.0%</b>
                  </li>
                  <li>
                    <span>익절</span>
                    <b>+5%/+10%</b>
                  </li>
                </ul>
              </article>
            </div>
          </div>

          <div className={`tab-panel${activeTab === 'logs' ? ' active' : ''}`} data-tab-panel="logs">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>시각</th>
                    <th>유형</th>
                    <th>종목</th>
                    <th>수량</th>
                    <th>가격</th>
                    <th>사유</th>
                    <th>손익</th>
                  </tr>
                </thead>
                <tbody>
                  {logs === null ? (
                    <tr>
                      <td colSpan={7} className="subtle">
                        불러오는 중…
                      </td>
                    </tr>
                  ) : logRows.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="subtle">
                        매매 로그가 없습니다.
                      </td>
                    </tr>
                  ) : (
                    logRows.map((row) => (
                      <tr key={row.id}>
                        <td>{formatHm(row.at)}</td>
                        <td>{formatSaAction(row.action)}</td>
                        <td>{row.name}</td>
                        <td>{row.qty == null ? '-' : formatNumber(row.qty)}</td>
                        <td>{row.price == null ? '-' : formatNumber(row.price)}</td>
                        <td>{row.message || '-'}</td>
                        <td>-</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className={`tab-panel${activeTab === 'alerts' ? ' active' : ''}`} data-tab-panel="alerts">
            <ul className="engine-list"></ul>
            <p className="hint" style={{ marginTop: 10 }}>
              이벤트: 매수 실패, 손절, 킬스위치 등
            </p>
          </div>

          <div className={`tab-panel${activeTab === 'signals' ? ' active' : ''}`} data-tab-panel="signals">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>시각</th>
                    <th>종목</th>
                    <th>시그널</th>
                    <th>실행</th>
                    <th>실패 사유</th>
                  </tr>
                </thead>
                <tbody>
                </tbody>
              </table>
            </div>
          </div>

          <div className={`tab-panel${activeTab === 'daily' ? ' active' : ''}`} data-tab-panel="daily">
            <div className="chart-placeholder">일별 수익금/수익률 + 누적 손익 Placeholder</div>
            <p className="hint" style={{ marginTop: 10 }}>
              월별/연간 수익률, 승/패 통계는 확장 구현
            </p>
          </div>

          <div className={`tab-panel${activeTab === 'snapshots' ? ' active' : ''}`} data-tab-panel="snapshots">
            <div className="chart-placeholder">시간대별 계좌 현황 Placeholder</div>
          </div>
        </div>
      </section>
    </>
  )
}
