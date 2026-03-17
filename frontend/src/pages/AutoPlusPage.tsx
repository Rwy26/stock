import { useEffect, useMemo, useState } from 'react'
import { fetchJson } from '../lib/api'
import { formatNumber, formatPercent } from '../lib/format'

type PlusTab = 'status' | 'logs' | 'rotation' | 'performance'

type PlusPositionItem = {
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

type PlusPositionsResponse = {
  asOf: string
  items: PlusPositionItem[]
}

type PlusLogItem = {
  id: number
  at: string | null
  action: string
  name: string
  code: string
  qty: number | null
  price: number | null
  message: string | null
}

type PlusLogsResponse = {
  asOf: string
  items: PlusLogItem[]
}

type PlusConfigResponse = {
  enabled: boolean
  config: unknown
  updatedAt: string | null
}

type PlusConfigForm = {
  totalBudget: string
  perStockBudget: string
  maxPositions: number
  scanStartRank: number
  scanEndRank: number
  requireUptrend: boolean
  minSaScore: number
  stopLossPct: number
  takeProfitPct: number
  trailingStopPct: string
  crashSellPct: string
  minHoldMinutes: string
  rotationCheckMinutes: string
}

function formatHm(value: string | null): string {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '-'
  return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function formatPlusAction(action: string): string {
  const a = (action || '').toLowerCase()
  if (a === 'buy') return '매수'
  if (a === 'sell') return '매도'
  return action
}

export function AutoPlusPage() {
  const [activeTab, setActiveTab] = useState<PlusTab>('status')
  const [positions, setPositions] = useState<PlusPositionItem[] | null>(null)
  const [logs, setLogs] = useState<PlusLogItem[] | null>(null)
  const [config, setConfig] = useState<PlusConfigResponse | null>(null)
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)

  const [form, setForm] = useState<PlusConfigForm>({
    totalBudget: '',
    perStockBudget: '',
    maxPositions: 5,
    scanStartRank: 1,
    scanEndRank: 100,
    requireUptrend: false,
    minSaScore: 50,
    stopLossPct: -5,
    takeProfitPct: 10,
    trailingStopPct: '',
    crashSellPct: '',
    minHoldMinutes: '',
    rotationCheckMinutes: '',
  })

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const [posRes, logRes] = await Promise.all([
          fetchJson<PlusPositionsResponse>('/api/automation/plus/positions'),
          fetchJson<PlusLogsResponse>('/api/automation/plus/logs?limit=200'),
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
    fetchJson<PlusConfigResponse>('/api/automation/plus')
      .then((cfg) => {
        if (cancelled) return
        setConfig(cfg)
        setEnabled(Boolean(cfg.enabled))

        const cfgObj = cfg.config && typeof cfg.config === 'object' ? (cfg.config as Record<string, unknown>) : null
        if (!cfgObj) return
        setForm((prev) => ({
          ...prev,
          totalBudget: typeof cfgObj.totalBudget === 'string' ? cfgObj.totalBudget : prev.totalBudget,
          perStockBudget: typeof cfgObj.perStockBudget === 'string' ? cfgObj.perStockBudget : prev.perStockBudget,
          maxPositions: typeof cfgObj.maxPositions === 'number' && Number.isFinite(cfgObj.maxPositions) ? cfgObj.maxPositions : prev.maxPositions,
          scanStartRank: typeof cfgObj.scanStartRank === 'number' && Number.isFinite(cfgObj.scanStartRank) ? cfgObj.scanStartRank : prev.scanStartRank,
          scanEndRank: typeof cfgObj.scanEndRank === 'number' && Number.isFinite(cfgObj.scanEndRank) ? cfgObj.scanEndRank : prev.scanEndRank,
          requireUptrend: typeof cfgObj.requireUptrend === 'boolean' ? cfgObj.requireUptrend : prev.requireUptrend,
          minSaScore: typeof cfgObj.minSaScore === 'number' && Number.isFinite(cfgObj.minSaScore) ? cfgObj.minSaScore : prev.minSaScore,
          stopLossPct: typeof cfgObj.stopLossPct === 'number' && Number.isFinite(cfgObj.stopLossPct) ? cfgObj.stopLossPct : prev.stopLossPct,
          takeProfitPct:
            typeof cfgObj.takeProfitPct === 'number' && Number.isFinite(cfgObj.takeProfitPct) ? cfgObj.takeProfitPct : prev.takeProfitPct,
          trailingStopPct: typeof cfgObj.trailingStopPct === 'string' ? cfgObj.trailingStopPct : prev.trailingStopPct,
          crashSellPct: typeof cfgObj.crashSellPct === 'string' ? cfgObj.crashSellPct : prev.crashSellPct,
          minHoldMinutes: typeof cfgObj.minHoldMinutes === 'string' ? cfgObj.minHoldMinutes : prev.minHoldMinutes,
          rotationCheckMinutes:
            typeof cfgObj.rotationCheckMinutes === 'string' ? cfgObj.rotationCheckMinutes : prev.rotationCheckMinutes,
        }))
      })
      .catch(() => {
        if (!cancelled) {
          setConfig({ enabled: false, config: null, updatedAt: null })
          setEnabled(false)
        }
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
        scanStartRank: form.scanStartRank,
        scanEndRank: form.scanEndRank,
        requireUptrend: form.requireUptrend,
        minSaScore: form.minSaScore,
        stopLossPct: form.stopLossPct,
        takeProfitPct: form.takeProfitPct,
        trailingStopPct: form.trailingStopPct,
        crashSellPct: form.crashSellPct,
        minHoldMinutes: form.minHoldMinutes,
        rotationCheckMinutes: form.rotationCheckMinutes,
      },
    }

    fetchJson<{ ok: boolean }>('/api/automation/plus', {
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

  const stats = useMemo(() => {
    if (!positions) return null
    const invested = positions.reduce((acc, p) => acc + (p.qty || 0) * (p.avgBuy || 0), 0)
    const evaluated = positions.reduce((acc, p) => acc + (p.qty || 0) * (p.current || 0), 0)
    const avgReturnPct = invested > 0 ? ((evaluated - invested) / invested) * 100.0 : null

    let maxPositions: number | null = null
    const cfg = config?.config
    if (cfg && typeof cfg === 'object') {
      const obj = cfg as Record<string, unknown>
      const candidates = [obj.maxPositions, obj.maxSymbols, obj.maxStocks, obj.maxCount]
      for (const c of candidates) {
        if (typeof c === 'number' && Number.isFinite(c) && c > 0) {
          maxPositions = Math.floor(c)
          break
        }
      }
    }

    const freeSlots = maxPositions == null ? null : Math.max(0, maxPositions - positions.length)
    return { evaluated, avgReturnPct, freeSlots }
  }, [config?.config, positions])

  return (
    <>
      <header className="topbar glass">
        <div>
          <p className="top-label">Plus Auto Trading</p>
          <h2>Plus 자동매매</h2>
          <p className="subtle">포트폴리오 순환 매매(언더퍼포머 자동 교체)</p>
        </div>
        <div className="status-pill">순환 체크 주기 설정</div>
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
            탐색 시작 순위
            <input type="number" value={form.scanStartRank} onChange={(e) => setForm((p) => ({ ...p, scanStartRank: Number(e.target.value) }))} />
          </label>
          <label>
            탐색 종료 순위
            <input type="number" value={form.scanEndRank} onChange={(e) => setForm((p) => ({ ...p, scanEndRank: Number(e.target.value) }))} />
          </label>
          <label>
            상승 요구
            <select
              value={form.requireUptrend ? 'On' : 'Off'}
              onChange={(e) => setForm((p) => ({ ...p, requireUptrend: e.target.value === 'On' }))}
            >
              <option value="Off">Off</option>
              <option value="On">On</option>
            </select>
          </label>
          <label>
            최소 SA 점수
            <input type="number" value={form.minSaScore} onChange={(e) => setForm((p) => ({ ...p, minSaScore: Number(e.target.value) }))} />
          </label>
          <label>
            손절률(%)
            <input type="number" value={form.stopLossPct} onChange={(e) => setForm((p) => ({ ...p, stopLossPct: Number(e.target.value) }))} />
          </label>
          <label>
            익절률(%)
            <input type="number" value={form.takeProfitPct} onChange={(e) => setForm((p) => ({ ...p, takeProfitPct: Number(e.target.value) }))} />
          </label>
          <label>
            트레일링 스탑률
            <input placeholder="선택" value={form.trailingStopPct} onChange={(e) => setForm((p) => ({ ...p, trailingStopPct: e.target.value }))} />
          </label>
          <label>
            급락 매도률
            <input placeholder="선택" value={form.crashSellPct} onChange={(e) => setForm((p) => ({ ...p, crashSellPct: e.target.value }))} />
          </label>
          <label>
            최소 보유 시간(분)
            <input placeholder="선택" value={form.minHoldMinutes} onChange={(e) => setForm((p) => ({ ...p, minHoldMinutes: e.target.value }))} />
          </label>
          <label>
            순환 체크 주기(분)
            <input
              placeholder="선택"
              value={form.rotationCheckMinutes}
              onChange={(e) => setForm((p) => ({ ...p, rotationCheckMinutes: e.target.value }))}
            />
          </label>
        </div>
        <div className="divider"></div>
        <button className="btn" type="button" disabled={busy} onClick={save}>
          저장
        </button>
      </section>

      <section className="panel glass reveal">
        <div className="panel-head">
          <h3>탭</h3>
        </div>
        <div className="tabs" data-tabs="plus">
          <button className={`tab${activeTab === 'status' ? ' active' : ''}`} type="button" data-tab="status" onClick={() => setActiveTab('status')}>
            현황
          </button>
          <button className={`tab${activeTab === 'logs' ? ' active' : ''}`} type="button" data-tab="logs" onClick={() => setActiveTab('logs')}>
            매매 로그
          </button>
          <button className={`tab${activeTab === 'rotation' ? ' active' : ''}`} type="button" data-tab="rotation" onClick={() => setActiveTab('rotation')}>
            순환 이력
          </button>
          <button className={`tab${activeTab === 'performance' ? ' active' : ''}`} type="button" data-tab="performance" onClick={() => setActiveTab('performance')}>
            성과 차트
          </button>
        </div>

        <div className="tab-panels" data-tab-panels="plus">
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
                        <th>매수가</th>
                        <th>현재가</th>
                        <th>매수 랭킹</th>
                        <th>수익률</th>
                      </tr>
                    </thead>
                    <tbody>
                      {positions === null ? (
                        <tr>
                          <td colSpan={5} className="subtle">
                            불러오는 중…
                          </td>
                        </tr>
                      ) : positionRows.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="subtle">
                            보유 포지션이 없습니다.
                          </td>
                        </tr>
                      ) : (
                        positionRows.map((row) => (
                          <tr key={row.id}>
                            <td>{row.name}</td>
                            <td>{row.avgBuy ? formatNumber(row.avgBuy) : '-'}</td>
                            <td>{row.current ? formatNumber(row.current) : '-'}</td>
                            <td>-</td>
                            <td className={row.pnlPct != null && row.pnlPct >= 0 ? 'up' : 'down'}>
                              {row.pnlPct == null ? '-' : formatPercent(row.pnlPct)}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </article>
              <article className="panel glass" style={{ boxShadow: 'none' }}>
                <div className="panel-head">
                  <h3>통계</h3>
                </div>
                <ul className="engine-list">
                  <li>
                    <span>총 평가액</span>
                    <b>{stats ? `₩${formatNumber(Math.round(stats.evaluated))}` : '₩-'}</b>
                  </li>
                  <li>
                    <span>평균 수익률</span>
                    <b className={(stats?.avgReturnPct ?? 0) >= 0 ? 'up' : 'down'}>
                      {stats?.avgReturnPct == null ? '-' : formatPercent(stats.avgReturnPct)}
                    </b>
                  </li>
                  <li>
                    <span>여유 슬롯</span>
                    <b>{stats?.freeSlots == null ? '-' : formatNumber(stats.freeSlots)}</b>
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
                    <th>가격</th>
                    <th>수량</th>
                    <th>랭킹</th>
                    <th>사유</th>
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
                        <td>{formatPlusAction(row.action)}</td>
                        <td>{row.name}</td>
                        <td>{row.price == null ? '-' : formatNumber(row.price)}</td>
                        <td>{row.qty == null ? '-' : formatNumber(row.qty)}</td>
                        <td>-</td>
                        <td>{row.message || '-'}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className={`tab-panel${activeTab === 'rotation' ? ' active' : ''}`} data-tab-panel="rotation">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>시각</th>
                    <th>퇴출 종목</th>
                    <th>퇴출 수익률</th>
                    <th>편입 종목</th>
                    <th>편입 랭킹</th>
                  </tr>
                </thead>
                <tbody>
                </tbody>
              </table>
            </div>
          </div>

          <div className={`tab-panel${activeTab === 'performance' ? ' active' : ''}`} data-tab-panel="performance">
            <div className="chart-placeholder">일별 수익(바) + 누적 손익(선) Placeholder</div>
          </div>
        </div>
      </section>
    </>
  )
}
