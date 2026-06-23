import { useEffect, useRef, useState } from 'react'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import { fetchSnapshot } from '../lib/api'

type LWC = typeof import('lightweight-charts')

interface HistRow { date: string; [k: string]: number | string | null }
interface History { keys: string[]; count: number; series: HistRow[] }

const LABELS: Record<string, string> = {
  composite: '종합(Composite)', risk_appetite: '시장 심리(Risk)', liquidity: '유동성', ai_cycle: 'AI 사이클',
  growth: '경기', inflation: '물가안정', geopolitics: '지정학(완화)', us_equity: '미국증시', kr_equity: '한국증시',
}
// composite 먼저, 그다음 선행지표 순
const ORDER = ['composite', 'risk_appetite', 'liquidity', 'ai_cycle', 'growth', 'inflation', 'geopolitics', 'us_equity', 'kr_equity']

// 각 지표가 기본으로 삼는 요소 (global_macro.py 점수 산출 근거 기준) — 클릭 시 표시
const DESC: Record<string, string> = {
  composite: '8개 점수의 가중평균. 시장심리 0.22·유동성 0.20·AI사이클 0.16·경기 0.12·물가 0.10·지정학 0.10·미국증시 0.06·한국증시 0.04. 선행지표(시장심리·유동성)에 더 큰 가중.',
  risk_appetite: 'VIX 변동성(안정<20·경계>25)·비트코인 5일 모멘텀·S&P500 신고가 여부. 낮은 VIX·BTC 강세·신고가 = Risk-On(시장 심리 우호).',
  liquidity: 'Fed 금리인하 확률(예측시장)·미 10년물 금리 20일 변화(상승=긴축)·달러지수 DXY 20일(달러강세=긴축). 인하기대↑·금리↓·약달러 = 유동성 우호.',
  ai_cycle: '빅테크 Capex 추세·반도체(SOX) 모멘텀·나스닥 20일 모멘텀. AI 밸류체인 투자·주가 강도.',
  growth: 'GDP 서프라이즈·실업률·ISM 제조업(≥50 확장)·예측시장 침체확률. 성장 상회·낮은 실업·ISM>50 = 경기 양호.',
  inflation: 'CPI 서프라이즈(상회=물가압박)·근원 CPI·WTI 유가·예측시장 CPI>3% 확률. 점수↑=물가안정(둔화), 점수↓=재가속.',
  geopolitics: '예측시장 분쟁확률·지정학 뉴스 감성·금(Gold) 5일. 점수↑=리스크 완화, 점수↓=긴장 고조.',
  us_equity: 'S&P500·나스닥·러셀2000 모멘텀에 시장심리·유동성을 가중 합성한 미국 증시 강도.',
  kr_equity: 'KOSPI·KOSDAQ 모멘텀·원달러 환율(약세=수출 환효과)·미국증시 동조·반도체 강도.',
}
const color = (v: number) => (v >= 60 ? '#34d399' : v >= 40 ? '#fbbf24' : '#f87171')

// ── 볼린저밴드(SMA ± 2σ) — 26일 윈도우라 기간은 데이터 길이에 맞춰 축소 ──────────
export type Pt = { time: string; value: number }
function bollinger(data: Pt[], mult = 2): { upper: Pt[]; lower: Pt[]; mid: Pt[] } {
  const out = { upper: [] as Pt[], lower: [] as Pt[], mid: [] as Pt[] }
  const period = Math.min(20, Math.max(4, Math.floor(data.length / 2)))
  if (data.length < period) return out
  for (let i = period - 1; i < data.length; i++) {
    const win = data.slice(i - period + 1, i + 1).map(d => d.value)
    const m = win.reduce((a, b) => a + b, 0) / period
    const sd = Math.sqrt(win.reduce((a, b) => a + (b - m) ** 2, 0) / period)
    const t = data[i].time
    out.mid.push({ time: t, value: m })
    out.upper.push({ time: t, value: m + mult * sd })
    out.lower.push({ time: t, value: m - mult * sd })
  }
  return out
}

// ── 현재 추세 방향 — 최근 구간 선형회귀 기울기 부호(중립 데드밴드) ──────────────
export function trendDir(data: Pt[]): 'up' | 'down' | 'flat' {
  const n = Math.min(5, data.length)
  if (n < 2) return 'flat'
  const w = data.slice(-n)
  const xs = w.map((_, i) => i)
  const mx = xs.reduce((a, b) => a + b, 0) / n
  const my = w.reduce((a, b) => a + b.value, 0) / n
  let num = 0, den = 0
  for (let i = 0; i < n; i++) { num += (xs[i] - mx) * (w[i].value - my); den += (xs[i] - mx) ** 2 }
  const slope = den ? num / den : 0
  return slope > 0.3 ? 'up' : slope < -0.3 ? 'down' : 'flat'
}
const ARROW = { up: '▲', down: '▼', flat: '▶' }
const ARROW_COLOR = { up: '#34d399', down: '#f87171', flat: '#94a3b8' }

// ── 개별 미니 차트 (일봉 라인, 로그/선형 토글) ───────────────────────────────
export function MiniChart({ lwc, k, rows, log, onSelect }: { lwc: LWC; k: string; rows: HistRow[]; log: boolean; onSelect: (k: string) => void }) {
  const hostRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const bbRef = useRef<{ upper: ISeriesApi<'Line'>; lower: ISeriesApi<'Line'>; mid: ISeriesApi<'Line'> } | null>(null)

  const data = rows
    .map(r => ({ time: r.date, value: r[k] as number | null }))
    .filter(d => d.value != null) as Array<{ time: string; value: number }>
  const last = data.length ? data[data.length - 1].value : null
  const dir = trendDir(data)

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
    // 볼린저밴드를 먼저 추가해 바탕(아래)에 깔고, 본선을 마지막에 올려 위로 보이게 함
    const bbBand = { color: 'rgba(96,165,250,0.30)', lineWidth: 1 as const, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false }
    const upper = chart.addSeries(lwc.LineSeries, bbBand)
    const lower = chart.addSeries(lwc.LineSeries, bbBand)
    const mid = chart.addSeries(lwc.LineSeries, { color: 'rgba(148,163,184,0.35)', lineWidth: 1, lineStyle: 2, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false })
    const bb = bollinger(data)
    upper.setData(bb.upper); lower.setData(bb.lower); mid.setData(bb.mid)
    bbRef.current = { upper, lower, mid }

    const c = last != null ? color(last) : '#60a5fa'
    const series = chart.addSeries(lwc.LineSeries, {
      color: c, lineWidth: 2,
      pointMarkersVisible: false,   // 날짜별 둥근 마커 제거 — 샤프한 직선만
      lastValueVisible: true, priceLineVisible: false,
    })
    series.setData(data)
    chart.timeScale().fitContent()
    chartRef.current = chart
    seriesRef.current = series
    return () => { chart.remove(); chartRef.current = null; seriesRef.current = null; bbRef.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lwc])

  // 데이터/스케일 갱신
  useEffect(() => {
    if (!seriesRef.current || !chartRef.current) return
    const c = last != null ? color(last) : '#60a5fa'
    seriesRef.current.applyOptions({ color: c })
    seriesRef.current.setData(data)
    if (bbRef.current) {
      const bb = bollinger(data)
      bbRef.current.upper.setData(bb.upper)
      bbRef.current.lower.setData(bb.lower)
      bbRef.current.mid.setData(bb.mid)
    }
    chartRef.current.priceScale('right').applyOptions({ mode: log ? 1 : 0 })
    chartRef.current.timeScale().fitContent()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [log, rows])

  return (
    <div onClick={() => onSelect(k)} title="클릭하면 이 지표의 기준 요소를 큰 창으로 설명"
      style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 10, padding: '8px 10px', cursor: 'pointer' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
        <span style={{ fontSize: 12, color: 'rgba(241,245,249,0.8)', fontWeight: k === 'composite' ? 700 : 400 }}>
          {LABELS[k] ?? k} <span style={{ fontSize: 10, color: 'rgba(148,163,184,0.7)' }}>ⓘ</span>
        </span>
        <span style={{ display: 'flex', alignItems: 'baseline', gap: 5 }}>
          <span title={`현재 추세: ${dir === 'up' ? '상승' : dir === 'down' ? '하락' : '횡보'}`}
            style={{ fontSize: 11, color: ARROW_COLOR[dir] }}>{ARROW[dir]}</span>
          <span style={{ fontSize: 14, fontWeight: 700, color: last != null ? color(last) : '#64748b' }}>{last ?? 'N/A'}</span>
        </span>
      </div>
      <div ref={hostRef} style={{ height: 150 }} />
    </div>
  )
}

// ── 지표 설명 모달 (연결된 큰 창) ─────────────────────────────────────────────
export function DescModal({ k, value, dir, onClose }: { k: string; value: number | null; dir: 'up' | 'down' | 'flat'; onClose: () => void }) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])
  const dirLabel = dir === 'up' ? '상승' : dir === 'down' ? '하락' : '횡보'
  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'rgba(2,6,18,0.72)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background: 'rgba(10,15,32,0.98)', border: '1px solid rgba(96,165,250,0.4)', borderRadius: 16,
        padding: '24px 28px', width: 'min(560px, 92vw)', maxHeight: '86vh', overflowY: 'auto',
        boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 20, color: '#bfdbfe' }}>{LABELS[k] ?? k}</h3>
          <button type="button" onClick={onClose} aria-label="닫기" style={{
            fontSize: 20, lineHeight: 1, background: 'transparent', border: 'none',
            color: 'rgba(241,245,249,0.6)', cursor: 'pointer', padding: 4,
          }}>✕</button>
        </div>
        <div style={{ display: 'flex', gap: 18, marginBottom: 18 }}>
          <div>
            <div style={{ fontSize: 11, color: '#64748b', marginBottom: 2 }}>현재 점수</div>
            <div style={{ fontSize: 30, fontWeight: 700, color: value != null ? color(value) : '#64748b' }}>{value ?? 'N/A'}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: '#64748b', marginBottom: 2 }}>추세</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: ARROW_COLOR[dir] }}>{ARROW[dir]} {dirLabel}</div>
          </div>
        </div>
        <div style={{ fontSize: 13, color: '#93c5fd', fontWeight: 600, marginBottom: 8 }}>기준 요소</div>
        <p style={{ fontSize: 15, lineHeight: 1.85, color: 'rgba(226,232,240,0.95)', margin: '0 0 16px' }}>
          {DESC[k] ?? '설명 준비 중'}
        </p>
        <p style={{ fontSize: 12.5, lineHeight: 1.7, color: '#64748b', margin: 0, borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: 12 }}>
          점수 50 = 중립 · 높을수록 우호적(물가·지정학은 점수↑=안정/완화) · 모든 수치는 실데이터 기반 결정론 계산.
        </p>
      </div>
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
  const [sel, setSel] = useState<string | null>(null)   // 설명 모달 대상 지표

  useEffect(() => { import('lightweight-charts').then(setLwc).catch(() => setErr('차트 라이브러리 로드 실패')) }, [])
  useEffect(() => {
    let alive = true
    const load = () => fetchSnapshot<History>('dashboard-global-macro.json', '/api/admin/global-macro/history?days=26')
      .then(d => { if (alive) setHist(d) })
      .catch(e => { if (alive) setErr(e instanceof Error ? e.message : String(e)) })
    load()
    const id = window.setInterval(load, 30 * 60 * 1000)   // 30분 차등 폴링 (정적 스냅샷 읽기계층)
    return () => { alive = false; window.clearInterval(id) }
  }, [])

  const rows = hist?.series ?? []
  const keys = ORDER.filter(k => (hist?.keys ?? ORDER).includes(k))

  // 선택 지표의 현재값·추세 (모달 표시용)
  const selData = sel
    ? (rows.map(r => ({ time: r.date, value: r[sel] as number | null })).filter(d => d.value != null) as Pt[])
    : []
  const selValue = selData.length ? selData[selData.length - 1].value : null
  const selDir = trendDir(selData)

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
          {keys.map(k => <MiniChart key={k} lwc={lwc} k={k} rows={rows} log={log} onSelect={setSel} />)}
        </div>
      )}
      {sel && <DescModal k={sel} value={selValue} dir={selDir} onClose={() => setSel(null)} />}
      <p style={{ fontSize: 11, color: '#475569', margin: '10px 0 0' }}>
        점수 50=중립 · {log ? '로그' : '선형'} 스케일 · 일봉(최근 26일) · 볼린저밴드 SMA±2σ 바탕 · ▲상승/▼하락/▶횡보 · 실데이터만 표시(시드 없음)
      </p>
    </div>
  )
}
