import { useEffect, useMemo, useState } from 'react'
import { fetchJson } from '../lib/api'
import { formatNumber, formatPercent } from '../lib/format'

type AutomationConfigResponse = {
  enabled: boolean
  config: unknown
  updatedAt: string | null
}

function asObj(v: unknown): Record<string, unknown> | null {
  if (!v || typeof v !== 'object') return null
  return v as Record<string, unknown>
}

function pickNumber(obj: Record<string, unknown> | null, key: string): number | null {
  if (!obj) return null
  const v = obj[key]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function pickString(obj: Record<string, unknown> | null, key: string): string | null {
  if (!obj) return null
  const v = obj[key]
  return typeof v === 'string' ? v : null
}

function pickBoolean(obj: Record<string, unknown> | null, key: string): boolean | null {
  if (!obj) return null
  const v = obj[key]
  return typeof v === 'boolean' ? v : null
}

function formatDateTime(value: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('ko-KR', { hour12: false })
}

export function StrategyPage() {
  const [sa, setSa] = useState<AutomationConfigResponse | null>(null)
  const [plus, setPlus] = useState<AutomationConfigResponse | null>(null)

  useEffect(() => {
    let cancelled = false

    const refresh = () => {
      Promise.allSettled([
        fetchJson<AutomationConfigResponse>('/api/automation/sa'),
        fetchJson<AutomationConfigResponse>('/api/automation/plus'),
      ]).then(([saRes, plusRes]) => {
        if (cancelled) return
        setSa(saRes.status === 'fulfilled' ? saRes.value : null)
        setPlus(plusRes.status === 'fulfilled' ? plusRes.value : null)
      })
    }

    refresh()
    const id = window.setInterval(refresh, 30_000)

    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  const saObj = useMemo(() => asObj(sa?.config), [sa?.config])
  const plusObj = useMemo(() => asObj(plus?.config), [plus?.config])

  const saEnabled = Boolean(sa?.enabled)
  const plusEnabled = Boolean(plus?.enabled)

  const saMinScore = pickNumber(saObj, 'minSaScore')
  const saMaxPositions = pickNumber(saObj, 'maxPositions')
  const saVolAdjust = pickBoolean(saObj, 'volatilityAdjust')

  const plusScanStart = pickNumber(plusObj, 'scanStartRank')
  const plusScanEnd = pickNumber(plusObj, 'scanEndRank')
  const plusStopLoss = pickNumber(plusObj, 'stopLossPct')
  const plusTakeProfit = pickNumber(plusObj, 'takeProfitPct')
  const plusMinSaScore = pickNumber(plusObj, 'minSaScore')

  const plusRotationMin = pickString(plusObj, 'rotationCheckMinutes')

  const showRotation = plusRotationMin && String(plusRotationMin).trim() !== ''

  const hasSa = sa != null
  const hasPlus = plus != null

  return (
    <>
      <header className="topbar glass">
        <div>
          <p className="top-label">Strategy</p>
          <h2>전략</h2>
          <p className="subtle">현재 적용 중인 자동매매 전략(엔진) 설정 요약</p>
        </div>
        <div className="status-pill">30초 갱신</div>
      </header>

      <section className="two-col">
        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>SA 전략</h3>
            <p className="subtle">골든크로스 예측 + OBV/MFI/매집패턴 가중치</p>
          </div>

          <ul className="engine-list">
            <li>
              <span>상태</span>
              <span className={saEnabled ? 'chip on' : 'chip off'}>{!hasSa ? '—' : saEnabled ? 'ON' : 'OFF'}</span>
            </li>
            <li>
              <span>최소 SA 점수</span>
              <b>{saMinScore == null ? '—' : formatNumber(saMinScore)}</b>
            </li>
            <li>
              <span>최대 보유 종목 수</span>
              <b>{saMaxPositions == null ? '—' : formatNumber(saMaxPositions)}</b>
            </li>
            <li>
              <span>변동성 보정</span>
              <b>{saVolAdjust == null ? '—' : saVolAdjust ? 'On' : 'Off'}</b>
            </li>
            <li>
              <span>마지막 변경</span>
              <b>{formatDateTime(sa?.updatedAt ?? null)}</b>
            </li>
          </ul>

          <div className="divider"></div>
          <p className="hint">설정 변경은 ‘SA 자동매매’ 화면에서 수행합니다.</p>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>Plus 전략</h3>
            <p className="subtle">포트폴리오 순환 매매(언더퍼포머 자동 교체)</p>
          </div>

          <ul className="engine-list">
            <li>
              <span>상태</span>
              <span className={plusEnabled ? 'chip on' : 'chip off'}>{!hasPlus ? '—' : plusEnabled ? 'ON' : 'OFF'}</span>
            </li>
            <li>
              <span>스캔 범위</span>
              <b>
                {plusScanStart == null || plusScanEnd == null ? '—' : `${formatNumber(plusScanStart)} ~ ${formatNumber(plusScanEnd)}`}
              </b>
            </li>
            <li>
              <span>최소 SA 점수</span>
              <b>{plusMinSaScore == null ? '—' : formatNumber(plusMinSaScore)}</b>
            </li>
            <li>
              <span>손절/익절</span>
              <b>
                {plusStopLoss == null || plusTakeProfit == null
                  ? '—'
                  : `${formatPercent(plusStopLoss)} / ${formatPercent(plusTakeProfit)}`}
              </b>
            </li>
            <li>
              <span>순환 체크(분)</span>
              <b>{showRotation ? plusRotationMin : '—'}</b>
            </li>
            <li>
              <span>마지막 변경</span>
              <b>{formatDateTime(plus?.updatedAt ?? null)}</b>
            </li>
          </ul>

          <div className="divider"></div>
          <p className="hint">설정 변경은 ‘Plus 자동매매’ 화면에서 수행합니다.</p>
        </article>
      </section>
    </>
  )
}
