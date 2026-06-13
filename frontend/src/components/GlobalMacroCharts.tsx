import { useEffect, useRef, useState } from 'react'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import { fetchJson } from '../lib/api'

type LWC = typeof import('lightweight-charts')

interface HistRow { date: string; [k: string]: number | string | null }
interface History { keys: string[]; count: number; series: HistRow[] }

const LABELS: Record<string, string> = {
  composite: '종합(Composite)', risk_appetite: '위험선호', liquidity: '유동성', ai_cycle: 'AI 사이클',
  growth: '경기', inflation: '물가안정', geopolitics: '지정학(완화)', us_equity: '미국증시', kr_equity: '한국증시',
}
// composite 먼저, 그다음 선행지표 순
const ORDER = ['composite', 'risk_appetite', 'liquidity', 'ai_cycle', 'growth', 'inflation', 'geopolitics', 'us_equity', 'kr_equity']
const color = (v: number) => (v >= 60 ? '#34d399' : v >= 40 ? '#fbbf24' : '#f87171')

// ── 개별 미니 차트 (일봉 라인, 로그/선형 토글) ───────────────────────────────
function MiniChart({ lwc, k, rows, log }: { lwc: LWC; k: string; rows: HistRow[]; log: boolean }) {
  const hostRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Line'> | null>(null)

  const data = rows
    .map(r => ({ time: r.date, value: r[k] as number | null }))
    .filter(d => d.value != null) as Array<{ time: string; value: number }>
  const last = data.length ? data[data.length - 1].value : null

  useEffect(() => {
    const host = hostRef.current
    if (!host || chartRef.current) return
    const chart = lwc.createChart(host, {
      autoSize: true, height: 150,
      layout: { background: { color: 'transparent' }, textColor: 'rgba(255,255,255,0.6)', fontSize: 10 },
      grid: { vertLines: { color: 'rgba(255,255,255,0.05)' }, horzLines: { color: 'rgba(255,255,255,0.05)' } },
      timeScale: { borderColor: 'rgba(255,255,255,0.12)', timeVisible: false },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.12)', mode: log ? 1 : 0 },
      crosshair: { vertLine: { color: 'rgba(255,255,255,0.18)' }, horzLine: { color: 'rgba(255,255,255,0.18)' } },
      handleScroll: false, handleScale: false,
    })
    const c = last != null ? color(last) : '#60a5fa'
    const sparse = data.length <= 30   // 점이 적을 때만 마커 표시(많으면 렌더 부담·시각 노이즈)
    const series = chart.addSeries(lwc.LineSeries, {
      color: c, lineWidth: 2,
      pointMarkersVisible: sparse, pointMarkersRadius: 3,
      lastValueVisible: true, priceLineVisible: false,
    })
    series.setData(data)
    chart.timeScale().fitContent()
    chartRef.current = chart
    seriesRef.current = series
    return () => { chart.remove(); chartRef.current = null; seriesRef.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lwc])

  // 데이터/스케일 갱신
  useEffect(() => {
    if (!seriesRef.current || !chartRef.current) return
    const c = last != null ? color(last) : '#60a5fa'
    seriesRef.current.applyOptions({ color: c })
    seriesRef.current.setData(data)
    chartRef.current.priceScale('right').applyOptions({ mode: log ? 1 : 0 })
    chartRef.current.timeScale().fitContent()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [log, rows])

  return (
    <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 10, padding: '8px 10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
        <span style={{ fontSize: 12, color: 'rgba(241,245,249,0.8)', fontWeight: k === 'composite' ? 700 : 400 }}>
          {LABELS[k] ?? k}
        </span>
        <span style={{ fontSize: 14, fontWeight: 700, color: last != null ? color(last) : '#64748b' }}>{last ?? 'N/A'}</span>
      </div>
      <div ref={hostRef} style={{ height: 150 }} />
    </div>
  )
}

// ── 차트 그리드 패널 ─────────────────────────────────────────────────────────
const panel: React.CSSProperties = {
  background: 'rgba(6,9,22,0.92)', border: '1px solid rgba(255,255,255,0.08)',
  borderRadius: 14, padding: '16px 18px', marginBottom: 18,
}

export function GlobalMacroCharts() {
  const [lwc, setLwc] = useState<LWC | null>(null)
  const [hist, setHist] = useState<History | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [log, setLog] = useState(true)

  useEffect(() => { import('lightweight-charts').then(setLwc).catch(() => setErr('차트 라이브러리 로드 실패')) }, [])
  useEffect(() => {
    fetchJson<History>('/api/admin/global-macro/history?days=180')
      .then(setHist)
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
  }, [])

  const rows = hist?.series ?? []
  const keys = ORDER.filter(k => (hist?.keys ?? ORDER).includes(k))

  return (
    <div style={{ ...panel, borderColor: 'rgba(96,165,250,0.3)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <h4 style={{ margin: 0, color: '#93c5fd' }}>📈 지표 일봉 추이 ({rows.length}일 누적)</h4>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['로그', '선형'] as const).map((lbl, i) => {
            const active = log === (i === 0)
            return (
              <button key={lbl} type="button" onClick={() => setLog(i === 0)} style={{
                fontSize: 12, padding: '3px 12px', borderRadius: 7, cursor: 'pointer',
                border: `1px solid ${active ? 'rgba(96,165,250,0.6)' : 'rgba(255,255,255,0.12)'}`,
                background: active ? 'rgba(96,165,250,0.15)' : 'transparent',
                color: active ? '#bfdbfe' : 'rgba(241,245,249,0.6)',
              }}>{lbl}</button>
            )
          })}
        </div>
      </div>

      {err && <p style={{ color: '#f87171', fontSize: 13 }}>차트 로드 실패: {err}</p>}
      {!err && rows.length < 2 && (
        <p style={{ color: '#94a3b8', fontSize: 12.5, margin: '0 0 10px' }}>
          데이터 누적 중 — 매일 06:00 동기화로 1행씩 쌓입니다 (현재 {rows.length}일). 2일 이상부터 추세선이 그려집니다.
        </p>
      )}
      {lwc && rows.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 12 }}>
          {keys.map(k => <MiniChart key={k} lwc={lwc} k={k} rows={rows} log={log} />)}
        </div>
      )}
      <p style={{ fontSize: 11, color: '#475569', margin: '10px 0 0' }}>
        점수 50=중립 · {log ? '로그' : '선형'} 스케일 · 일봉 · 실데이터만 표시(시드 없음)
      </p>
    </div>
  )
}
