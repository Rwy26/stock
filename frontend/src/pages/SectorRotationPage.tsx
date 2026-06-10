import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchJson } from '../lib/api'
import { publicFetch } from '../lib/publicApi'

// ─── Types ──────────────────────────────────────────────────────────────────

interface MacroDetail {
  tnx?: number | null
  dxy?: number | null
  vix?: number
  vkospi?: number | null
  nasdaq?: number | null
  usKrw?: number | null
  oil?: number | null
  // scores
  tnxScore?: number
  dxyScore?: number
  vixScore?: number
  vkospiScore?: number
  nasScore?: number
  krwScore?: number
  oilScore?: number
  // changes
  tnxChg1d?: number
  tnxChg5d?: number
  tnx20dChg?: number
  dxyChg1d?: number
  dxy20dChg?: number
  vixChg1d?: number
  nasdaqChg1d?: number
  nasdaqChg5d?: number
  nasdaqChg20d?: number
  usKrwChg1d?: number
  usKrwChg5d?: number
  usKrwChg20d?: number
  oilChg1d?: number
  oilChg5d?: number
  oilChg20d?: number
  vkospiChg1d?: number
  growthScore?: number
  // series
  series1d?: Record<string, number[]>
  series1h?: Record<string, number[]>
  error?: string
}

interface SectorBreakdown {
  macro: number
  foreign: number
  institutional: number
  momentum: number
  news: number
  volume: number
  smart: number
  intraday?: number
}

interface SectorDetail {
  foreignBil: number
  institutionalBil: number
  momentumPct: number
  volumeSurgePct: number
}

interface LeadStock {
  code: string
  name: string
  change14d: number
  changeToday?: number
}

interface DominanceData {
  prices: number[]
  bbUpper: (number | null)[]
  bbMiddle: (number | null)[]
  bbLower: (number | null)[]
  rsi: number[]
  signals: { idx: number; type: 'buy' | 'sell' }[]
}

interface SectorItem {
  sector: string
  score: number
  lifecycle: string
  lifecycleStage: number
  stars: number
  breakdown: SectorBreakdown
  detail: SectorDetail
  codes: string[]
  leadNames?: string[]
  componentNames?: string[]
  trends?: { tags: string[]; theme: string }
  leadStocks?: LeadStock[]
  dominance?: DominanceData | null
}

interface RotationData {
  asOf: string
  macroDetail: MacroDetail
  sectors: SectorItem[]
  topSectors: string[]
  warningSectors: string[]
  cached: boolean
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const LIFECYCLE_COLORS: Record<number, string> = {
  0: '#ef4444',   // 붕괴: 빨강
  1: '#6b7280',   // 관망: 회색
  2: '#3b82f6',   // 기관매집: 파랑
  3: '#06b6d4',   // 외국인유입: 청록
  4: '#eab308',   // 뉴스확산: 노랑
  5: '#f97316',   // 개인추격·과열: 주황
  6: '#dc2626',   // 분배주의: 진빨강
}

const LIFECYCLE_BG: Record<number, string> = {
  0: 'rgba(239,68,68,0.15)',
  1: 'rgba(107,114,128,0.15)',
  2: 'rgba(59,130,246,0.15)',
  3: 'rgba(6,182,212,0.15)',
  4: 'rgba(234,179,8,0.15)',
  5: 'rgba(249,115,22,0.15)',
  6: 'rgba(220,38,38,0.15)',
}

const SCORE_COLOR = (score: number) => {
  if (score >= 75) return '#34d399'
  if (score >= 55) return '#60a5fa'
  if (score >= 40) return '#eab308'
  return '#f87171'
}

const STARS = (n: number) =>
  '★'.repeat(n) + '☆'.repeat(5 - n)

// 추이 화살표: bil(억원) 또는 pct(%) 기준
function trendArrow(v: number, type: 'bil' | 'pct'): { arrow: string; color: string } {
  const [big, small] = type === 'bil' ? [500, 50] : [10, 2]
  if (v >  big) return { arrow: '↑↑', color: '#34d399' }
  if (v >  small) return { arrow: '↑',  color: '#86efac' }
  if (v > -small) return { arrow: '→',  color: 'rgba(255,255,255,0.3)' }
  if (v > -big)  return { arrow: '↓',  color: '#fca5a5' }
  return             { arrow: '↓↓', color: '#f87171' }
}

const fmtBil = (v: number) => {
  if (v === 0) return '—'
  const sign = v >= 0 ? '+' : ''
  const abs = Math.abs(v)
  if (abs >= 10000) return sign + (v / 10000).toFixed(1) + '조'
  return sign + v.toFixed(0) + '억'
}

const fmtPct = (v: number) => (v >= 0 ? '+' : '') + v.toFixed(1) + '%'

// ─── Score Bar ───────────────────────────────────────────────────────────────

function ScoreBar({ value, color }: { value: number; color: string }) {
  return (
    <div style={{ position: 'relative', height: 8, background: 'rgba(255,255,255,0.1)', borderRadius: 4, overflow: 'hidden', width: '100%' }}>
      <div style={{
        position: 'absolute', top: 0, left: 0, height: '100%',
        width: `${value}%`, background: color,
        borderRadius: 4, transition: 'width 0.6s ease',
      }} />
    </div>
  )
}

// ─── Breakdown Radar (horizontal bars) ──────────────────────────────────────

function BreakdownBars({ bd }: { bd: SectorBreakdown }) {
  const rows: [string, number, string][] = [
    ['당일',     bd.intraday ?? 50, '#f87171'],
    ['매크로',   bd.macro,         '#a78bfa'],
    ['외국인',   bd.foreign,       '#60a5fa'],
    ['기관',     bd.institutional, '#34d399'],
    ['모멘텀',   bd.momentum,      '#fb923c'],
    ['거래대금', bd.volume,        '#f59e0b'],
    ['스마트',   bd.smart,         '#e879f9'],
  ]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {rows.map(([label, val, color]) => (
        <div key={label} style={{ display: 'grid', gridTemplateColumns: '70px 1fr 40px', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.6)' }}>{label}</span>
          <ScoreBar value={val} color={color} />
          <span style={{ fontSize: 11, color, textAlign: 'right' }}>{val.toFixed(0)}</span>
        </div>
      ))}
    </div>
  )
}

// ─── Dominance Chart (BB + RSI overlay) ──────────────────────────────────────
// 볼린저 밴드 위에 RSI를 이중축으로 중첩. 좌축=가격(BB), 우축=RSI(0~100)
// 매수신호(▲): 가격≤BB하단*1.01 AND RSI≤35 / 매도신호(▼): 가격≥BB상단*0.99 AND RSI≥65

function DominanceChart({ data }: { data: DominanceData }) {
  const W = 200, H = 46, PX = 2, PY = 3
  const n = data.prices.length
  if (n < 4) return null

  const validU = data.bbUpper.filter((x): x is number => x != null)
  const validL = data.bbLower.filter((x): x is number => x != null)
  if (validU.length < 2 || validL.length < 2) return null

  const priceMin   = Math.min(...validL)
  const priceMax   = Math.max(...validU)
  const priceRange = priceMax - priceMin || 1

  const toX  = (i: number) => PX + (i / (n - 1)) * (W - 2 * PX)
  const toYP = (v: number) => PY + (1 - (v - priceMin) / priceRange) * (H - 2 * PY)
  const toYR = (r: number) => PY + (1 - r / 100) * (H - 2 * PY)

  // BB 채움 다각형: 상단 순방향 + 하단 역방향
  const fillPts: string[] = []
  data.bbUpper.forEach((v, i) => { if (v != null) fillPts.push(`${toX(i)},${toYP(v)}`) })
  for (let i = n - 1; i >= 0; i--) {
    const v = data.bbLower[i]
    if (v != null) fillPts.push(`${toX(i)},${toYP(v)}`)
  }

  // 경로 빌더 (null 구간 건너뜀)
  const makePath = (arr: (number | null)[], toY: (v: number) => number) => {
    let d = ''
    arr.forEach((v, i) => {
      if (v == null) return
      d += d ? ` L${toX(i)},${toY(v)}` : `M${toX(i)},${toY(v)}`
    })
    return d
  }

  const pricePath = data.prices.map((v, i) =>
    `${i === 0 ? 'M' : ' L'}${toX(i)},${toYP(v)}`).join('')
  const rsiPath = data.rsi.map((v, i) =>
    `${i === 0 ? 'M' : ' L'}${toX(i)},${toYR(v)}`).join('')

  return (
    <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`}
      style={{ display: 'block' }}
      preserveAspectRatio="none">
      {/* BB 채움 */}
      {fillPts.length > 3 && (
        <polygon points={fillPts.join(' ')} fill="rgba(255,255,255,0.05)" />
      )}
      {/* RSI 70/30 가이드 (이중축 우측 스케일) */}
      <line x1={PX} y1={toYR(70)} x2={W - PX} y2={toYR(70)}
        stroke="rgba(249,115,22,0.4)" strokeWidth={0.7} strokeDasharray="3,3" />
      <line x1={PX} y1={toYR(30)} x2={W - PX} y2={toYR(30)}
        stroke="rgba(96,165,250,0.4)" strokeWidth={0.7} strokeDasharray="3,3" />
      {/* RSI 과매수/과매도 배경 하이라이트 */}
      <rect x={PX} y={PY} width={W - 2 * PX} height={toYR(70) - PY}
        fill="rgba(249,115,22,0.04)" />
      <rect x={PX} y={toYR(30)} width={W - 2 * PX} height={H - PY - toYR(30)}
        fill="rgba(96,165,250,0.04)" />
      {/* BB 밴드 */}
      <path d={makePath(data.bbUpper, toYP)} fill="none"
        stroke="rgba(248,113,113,0.55)" strokeWidth={0.9} strokeDasharray="3,2" />
      <path d={makePath(data.bbLower, toYP)} fill="none"
        stroke="rgba(96,165,250,0.55)" strokeWidth={0.9} strokeDasharray="3,2" />
      <path d={makePath(data.bbMiddle, toYP)} fill="none"
        stroke="rgba(255,255,255,0.18)" strokeWidth={0.7} strokeDasharray="2,3" />
      {/* 가격선 (좌축 스케일) */}
      <path d={pricePath} fill="none" stroke="rgba(255,255,255,0.72)" strokeWidth={1.4}
        strokeLinecap="round" strokeLinejoin="round" />
      {/* RSI 오버레이 (우축 스케일, twinx) */}
      <path d={rsiPath} fill="none" stroke="rgba(167,139,250,0.78)" strokeWidth={1.0}
        strokeLinecap="round" strokeLinejoin="round" />
      {/* 매수/매도 시그널 마커 */}
      {data.signals.map((sig, si) => {
        if (sig.idx >= n) return null
        const sx = toX(sig.idx)
        const sy = toYP(data.prices[sig.idx])
        return sig.type === 'buy'
          ? <polygon key={si}
              points={`${sx},${sy - 5} ${sx - 3.5},${sy + 2} ${sx + 3.5},${sy + 2}`}
              fill="#4ade80" opacity={0.92} />
          : <polygon key={si}
              points={`${sx},${sy + 5} ${sx - 3.5},${sy - 2} ${sx + 3.5},${sy - 2}`}
              fill="#f87171" opacity={0.92} />
      })}
    </svg>
  )
}

// ─── Decline Reason ──────────────────────────────────────────────────────────

interface DeclineCause { label: string; color: string }

function getSectorCauses(item: SectorItem): DeclineCause[] {
  const causes: DeclineCause[] = []
  const { breakdown: bd, detail: dt, score } = item

  if (score >= 55) {
    // 상승 원인
    if (dt.foreignBil > 0 && bd.foreign >= 55)
      causes.push({ label: '외국인 매집', color: '#34d399' })
    if (dt.institutionalBil > 0 && bd.institutional >= 55)
      causes.push({ label: '기관 매집', color: '#60a5fa' })
    if (dt.volumeSurgePct >= 20)
      causes.push({ label: '거래대금 급증', color: '#fbbf24' })
    if (bd.macro >= 65)
      causes.push({ label: '매크로 순풍', color: '#a78bfa' })
  } else {
    // 하락 원인
    if (dt.foreignBil < 0 && bd.foreign < 45)
      causes.push({ label: '외국인 순매도', color: '#f87171' })
    if (dt.institutionalBil < 0 && bd.institutional < 45)
      causes.push({ label: '기관 순매도', color: '#fb923c' })
    if (dt.volumeSurgePct < -20)
      causes.push({ label: '거래대금 급감', color: '#94a3b8' })
    if (bd.macro < 35)
      causes.push({ label: '매크로 역풍', color: '#a78bfa' })
  }
  return causes
}

// ─── Sector Card ─────────────────────────────────────────────────────────────

function SectorCard({ item, rank, expanded, onToggle }: {
  item: SectorItem
  rank: number
  expanded: boolean
  onToggle: () => void
}) {
  const color = SCORE_COLOR(item.score)
  const lcColor = LIFECYCLE_COLORS[item.lifecycleStage] ?? '#6b7280'
  const lcBg = LIFECYCLE_BG[item.lifecycleStage] ?? 'rgba(107,114,128,0.15)'

  return (
    <div
      onClick={onToggle}
      style={{
        background: expanded ? 'rgba(255,255,255,0.07)' : 'rgba(255,255,255,0.03)',
        border: `1px solid ${expanded ? color + '60' : 'rgba(255,255,255,0.08)'}`,
        borderRadius: 12,
        padding: '14px 16px',
        cursor: 'pointer',
        transition: 'all 0.2s',
      }}
    >
      {/* Header row */}
      <div style={{ display: 'grid', gridTemplateColumns: '28px auto 1fr auto auto auto', gap: 8, alignItems: 'center' }}>
        {/* Rank */}
        <span style={{
          fontSize: 13, fontWeight: 700, color: rank <= 3 ? '#fbbf24' : 'rgba(255,255,255,0.4)',
          textAlign: 'center',
        }}>#{rank}</span>

        {/* Sector name */}
        <span style={{ fontSize: 15, fontWeight: 600, color: '#f1f5f9', whiteSpace: 'nowrap' }}>{item.sector}</span>

        {/* Dominance chart (BB+RSI 이중축) */}
        <div style={{ minWidth: 60, overflow: 'hidden', height: 46, display: 'flex', alignItems: 'center' }}>
          {item.dominance && <DominanceChart data={item.dominance} />}
        </div>

        {/* Cause tags (생애주기 배지 자리) */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3, alignItems: 'flex-start', justifyContent: 'center' }}>
          {getSectorCauses(item).length > 0
            ? getSectorCauses(item).map(c => (
                <span key={c.label} style={{
                  fontSize: 10, padding: '2px 8px', borderRadius: 99,
                  background: c.color + '18', color: c.color,
                  border: `1px solid ${c.color}40`,
                  whiteSpace: 'nowrap', lineHeight: 1.5,
                }}>{c.label}</span>
              ))
            : <span style={{
                fontSize: 11, padding: '3px 8px', borderRadius: 99,
                background: lcBg, color: lcColor, border: `1px solid ${lcColor}40`,
                whiteSpace: 'nowrap',
              }}>{item.lifecycle}</span>
          }
        </div>

        {/* Stars */}
        <span style={{ fontSize: 13, color: '#fbbf24', letterSpacing: -2 }}>{STARS(item.stars)}</span>

        {/* Score */}
        <span style={{ fontSize: 20, fontWeight: 800, color, minWidth: 44, textAlign: 'right' }}>
          {item.score}
        </span>
      </div>

      {/* Score bar */}
      <div style={{ marginTop: 10 }}>
        <ScoreBar value={item.score} color={color} />
      </div>

      {/* Quick stats */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 8, marginTop: 10, fontSize: 11,
      }}>
        {[['외국인', item.detail.foreignBil, 'bil'], ['기관', item.detail.institutionalBil, 'bil'],
          ['모멘텀', item.detail.momentumPct, 'pct'], ['거래대금', item.detail.volumeSurgePct, 'pct']
         ].map(([label, val, type]) => {
           const v = val as number
           const t = type as 'bil' | 'pct'
           const valStr = t === 'bil' ? fmtBil(v) : fmtPct(v)
           const valColor = v >= 0 ? '#34d399' : '#f87171'
           const { arrow, color: arrowColor } = trendArrow(v, t)
           return (
             <div key={label as string} style={{ color: 'rgba(255,255,255,0.5)' }}>
               {label as string}{' '}
               <span style={{ color: valColor }}>{valStr}</span>
               {' '}<span style={{ fontSize: 11, color: arrowColor, fontWeight: 700 }}>{arrow}</span>
             </div>
           )
         })}
      </div>

      {/* Expanded breakdown */}
      {expanded && (
        <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid rgba(255,255,255,0.08)' }}>
          <p style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', marginBottom: 10 }}>
            레이어별 점수 (0~100)
          </p>
          <BreakdownBars bd={item.breakdown} />
          <p style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)', marginTop: 10 }}>
            대표 종목: {item.codes.join(', ')}
          </p>
          {item.trends && item.trends.tags.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
              <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.25)' }}>🏷️</span>
              {item.trends.tags.map(tag => (
                <span key={tag} style={{
                  fontSize: 10, padding: '2px 7px', borderRadius: 99,
                  background: 'rgba(96,165,250,0.1)', color: '#93c5fd',
                  border: '1px solid rgba(96,165,250,0.2)',
                }}>{tag}</span>
              ))}
            </div>
          )}
          {item.trends?.theme && (
            <p style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)', marginTop: 4, fontStyle: 'italic' }}>
              ↗ {item.trends.theme}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Lifecycle Legend ────────────────────────────────────────────────────────

function LifecycleLegend() {
  const items = [
    [0, '붕괴'],
    [1, '관망'],
    [2, '기관매집'],
    [3, '외국인유입'],
    [4, '뉴스확산'],
    [5, '개인추격·과열'],
    [6, '분배주의'],
  ] as const

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, fontSize: 11 }}>
      {items.map(([stage, label]) => (
        <span key={stage} style={{
          padding: '3px 8px', borderRadius: 99,
          background: LIFECYCLE_BG[stage], color: LIFECYCLE_COLORS[stage],
          border: `1px solid ${LIFECYCLE_COLORS[stage]}30`,
        }}>{label}</span>
      ))}
    </div>
  )
}

// ─── Macro Summary ───────────────────────────────────────────────────────────

// ─── Macro Spark Line ────────────────────────────────────────────────────────
function MacroSpark({ series, color, invert = false }: { series: number[]; color: string; invert?: boolean }) {
  const W = 80, H = 24, PX = 1, PY = 2
  if (series.length < 2) return <svg width={W} height={H} />
  const mn = Math.min(...series), mx = Math.max(...series)
  const range = mx - mn || 1
  const toX = (i: number) => PX + (i / (series.length - 1)) * (W - 2 * PX)
  const toY = (v: number) => PY + (invert ? (v - mn) / range : 1 - (v - mn) / range) * (H - 2 * PY)
  const line = series.map((v, i) => `${i === 0 ? 'M' : 'L'}${toX(i)},${toY(v)}`).join(' ')
  const area = line + ` L${toX(series.length - 1)},${H} L${PX},${H} Z`
  const gid = `ms-${color.replace('#', '')}-${Math.random().toString(36).slice(2)}`
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', flexShrink: 0 }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0.03" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={toX(series.length - 1)} cy={toY(series[series.length - 1])} r="2" fill={color} />
    </svg>
  )
}

// ─── Macro Card (섹터 스타일) ─────────────────────────────────────────────────
type MacroTab = '1d' | '1h'

function MacroCard({ detail }: { detail: MacroDetail }) {
  const [tab, setTab] = useState<MacroTab>('1d')

  interface MacroItem {
    key: string; label: string; val: string
    score: number; chg1d: number; chg5d?: number; chg20d?: number
    seriesKey: string; scoreColor: string
    /** score 낮을수록 주가에 불리(금리·달러·원달러·VIX): invert spark */
    invertSpark?: boolean
    note?: string
  }

  const s1d = detail.series1d ?? {}
  const s1h = detail.series1h ?? {}

  const items: MacroItem[] = [
    {
      key: 'tnx', label: '미 10Y 국채금리', seriesKey: 'tnx', invertSpark: true,
      val: detail.tnx != null ? detail.tnx + '%' : '—',
      score: detail.tnxScore ?? 50,
      chg1d: detail.tnxChg1d ?? 0, chg5d: detail.tnxChg5d, chg20d: detail.tnx20dChg,
      scoreColor: (detail.tnxScore ?? 50) >= 60 ? '#34d399' : (detail.tnxScore ?? 50) >= 40 ? '#eab308' : '#f87171',
      note: '금리↑ = 성장주 불리',
    },
    {
      key: 'dxy', label: '달러 인덱스(DXY)', seriesKey: 'dxy', invertSpark: true,
      val: detail.dxy != null ? String(detail.dxy) : '—',
      score: detail.dxyScore ?? 50,
      chg1d: detail.dxyChg1d ?? 0, chg20d: detail.dxy20dChg,
      scoreColor: (detail.dxyScore ?? 50) >= 60 ? '#34d399' : (detail.dxyScore ?? 50) >= 40 ? '#eab308' : '#f87171',
      note: '달러↑ = 외국인 이탈',
    },
    {
      key: 'vix', label: 'VIX (미국)', seriesKey: 'vix', invertSpark: true,
      val: detail.vix != null ? String(detail.vix) : '—',
      score: detail.vixScore ?? 50,
      chg1d: detail.vixChg1d ?? 0,
      scoreColor: (detail.vixScore ?? 50) >= 60 ? '#34d399' : (detail.vixScore ?? 50) >= 40 ? '#eab308' : '#f87171',
      note: 'VIX↑ = 공포·변동성',
    },
    {
      key: 'vkospi', label: 'VKOSPI (한국)', seriesKey: 'vkospi', invertSpark: true,
      val: detail.vkospi != null ? String(detail.vkospi) : '—',
      score: detail.vkospiScore ?? 50,
      chg1d: detail.vkospiChg1d ?? 0,
      scoreColor: (detail.vkospiScore ?? 50) >= 60 ? '#34d399' : (detail.vkospiScore ?? 50) >= 40 ? '#eab308' : '#f87171',
      note: 'KOSPI 변동성 지수',
    },
    {
      key: 'nasdaq', label: '나스닥', seriesKey: 'nasdaq',
      val: detail.nasdaq != null ? detail.nasdaq.toLocaleString() : '—',
      score: detail.nasScore ?? 50,
      chg1d: detail.nasdaqChg1d ?? 0, chg5d: detail.nasdaqChg5d, chg20d: detail.nasdaqChg20d,
      scoreColor: (detail.nasScore ?? 50) >= 60 ? '#34d399' : (detail.nasScore ?? 50) >= 40 ? '#eab308' : '#f87171',
    },
    {
      key: 'krw', label: '달러/원 환율', seriesKey: 'krw', invertSpark: true,
      val: detail.usKrw != null ? detail.usKrw.toLocaleString() : '—',
      score: detail.krwScore ?? 50,
      chg1d: detail.usKrwChg1d ?? 0, chg5d: detail.usKrwChg5d, chg20d: detail.usKrwChg20d,
      scoreColor: (detail.krwScore ?? 50) >= 60 ? '#34d399' : (detail.krwScore ?? 50) >= 40 ? '#eab308' : '#f87171',
      note: '환율↑ = 외국인 이탈',
    },
    {
      key: 'oil', label: 'WTI 원유', seriesKey: 'oil',
      val: detail.oil != null ? '$' + detail.oil.toFixed(1) : '—',
      score: detail.oilScore ?? 50,
      chg1d: detail.oilChg1d ?? 0, chg5d: detail.oilChg5d, chg20d: detail.oilChg20d,
      scoreColor: (detail.oilScore ?? 50) >= 60 ? '#34d399' : (detail.oilScore ?? 50) >= 40 ? '#eab308' : '#f87171',
    },
  ]

  const { arrow: gsArrow, color: gsArColor } = trendArrow(
    (detail.growthScore ?? 50) - 50, 'pct'
  )

  return (
    <div style={{
      background: 'rgba(255,255,255,0.02)',
      border: '1px solid rgba(255,255,255,0.08)',
      borderRadius: 12, overflow: 'hidden',
    }}>
      {/* 헤더 */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '10px 16px', borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.5)' }}>Layer 1 · 거시경제 지표</span>
          <span style={{
            fontSize: 12, padding: '2px 10px', borderRadius: 99,
            background: gsArColor + '18', color: gsArColor, border: `1px solid ${gsArColor}30`,
          }}>
            성장주 우호도 {detail.growthScore ?? '—'} {gsArrow}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['1d', '1h'] as MacroTab[]).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              fontSize: 11, padding: '3px 10px', borderRadius: 6,
              border: `1px solid ${tab === t ? 'rgba(96,165,250,0.5)' : 'rgba(255,255,255,0.1)'}`,
              background: tab === t ? 'rgba(96,165,250,0.15)' : 'transparent',
              color: tab === t ? '#60a5fa' : 'rgba(255,255,255,0.4)',
              cursor: 'pointer', fontFamily: 'inherit',
            }}>{t === '1d' ? '일봉' : '1시간'}</button>
          ))}
        </div>
      </div>

      {/* 지표 그리드 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 0 }}>
        {items.map((item, idx) => {
          const series = tab === '1d' ? (s1d[item.seriesKey] ?? []) : (s1h[item.seriesKey] ?? [])
          const { arrow: a1d, color: ac1d } = trendArrow(item.chg1d, 'pct')
          const chgDisplay = item.chg1d
          const borderRight = idx % 4 !== 3 ? '1px solid rgba(255,255,255,0.05)' : 'none'
          const borderBottom = idx < 4 ? '1px solid rgba(255,255,255,0.05)' : 'none'

          return (
            <div key={item.key} style={{
              padding: '12px 14px',
              borderRight, borderBottom,
            }}>
              {/* 라벨 + 화살표 */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                <span style={{ fontSize: 10.5, color: 'rgba(255,255,255,0.4)' }}>{item.label}</span>
                <span style={{ fontSize: 12, fontWeight: 700, color: ac1d }}>{a1d}</span>
              </div>
              {/* 현재값 + 스파크 */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6, marginBottom: 6 }}>
                <span style={{ fontSize: 17, fontWeight: 800, color: '#f1f5f9', lineHeight: 1 }}>{item.val}</span>
                {series.length >= 2 && (
                  <MacroSpark series={series} color={item.scoreColor} invert={item.invertSpark} />
                )}
              </div>
              {/* 점수 바 */}
              <ScoreBar value={item.score} color={item.scoreColor} />
              {/* 1d 변화율 + 추가 정보 */}
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 5 }}>
                <span style={{ fontSize: 10, color: ac1d, fontWeight: 600 }}>
                  {chgDisplay >= 0 ? '+' : ''}{chgDisplay.toFixed(2)}% <span style={{ fontWeight: 400, color: 'rgba(255,255,255,0.25)' }}>1d</span>
                </span>
                {item.chg20d != null && (
                  <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.25)' }}>
                    {item.chg20d >= 0 ? '+' : ''}{item.chg20d.toFixed(1)}% 20d
                  </span>
                )}
              </div>
              {item.note && (
                <div style={{ fontSize: 9.5, color: 'rgba(255,255,255,0.2)', marginTop: 3 }}>{item.note}</div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Lifecycle Pipeline ──────────────────────────────────────────────────────

function LifecyclePipeline({ sectors }: { sectors: SectorItem[] }) {
  const stages = [2, 3, 4, 5, 6] as const
  const stageLabels: Record<number, string> = {
    2: '기관매집', 3: '외국인유입', 4: '뉴스확산', 5: '개인추격', 6: '분배',
  }
  const bySage: Record<number, SectorItem[]> = {}
  for (const s of stages) bySage[s] = sectors.filter(x => x.lifecycleStage === s)

  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)',
      gap: 8,
    }}>
      {stages.map(stage => (
        <div key={stage} style={{
          background: LIFECYCLE_BG[stage],
          border: `1px solid ${LIFECYCLE_COLORS[stage]}30`,
          borderRadius: 10, padding: '10px 12px',
          minHeight: 70,
        }}>
          <p style={{ fontSize: 11, color: LIFECYCLE_COLORS[stage], fontWeight: 600, marginBottom: 6 }}>
            {stage}단계 · {stageLabels[stage]}
          </p>
          {bySage[stage].length === 0
            ? <p style={{ fontSize: 11, color: 'rgba(255,255,255,0.2)' }}>—</p>
            : bySage[stage].map(s => (
              <p key={s.sector} style={{ fontSize: 12, color: '#f1f5f9', marginBottom: 2 }}>
                {s.sector} <span style={{ color: SCORE_COLOR(s.score) }}>{s.score}</span>
              </p>
            ))}
        </div>
      ))}
    </div>
  )
}

// ─── Mini Chart (Google Finance style) ──────────────────────────────────────
// chg5d: 최근 5거래일 변화율, chg20d: 최근 20거래일 변화율
// 3-anchor bezier area chart: start(day-20) → mid(day-5) → end(today)
// BB(20, 2σ) 계산 — 일봉 시리즈에서 윈도우가 차는 구간만 반환
type BBPoint = { price: number; up: number; mid: number; lo: number }

function bollinger(series: number[], win = 20, k = 2) {
  const out: BBPoint[] = []
  for (let i = win - 1; i < series.length; i++) {
    const w = series.slice(i - win + 1, i + 1)
    const mean = w.reduce((a, b) => a + b, 0) / win
    const sd = Math.sqrt(w.reduce((a, b) => a + (b - mean) ** 2, 0) / win)
    out.push({ price: series[i], up: mean + k * sd, mid: mean, lo: mean - k * sd })
  }
  return out
}

function MiniChart({ chg5d = 0, chg20d = 0, color, id, series }: {
  chg5d?: number; chg20d?: number; color: string; id: string; series?: number[]
}) {
  const W = 64, H = 28, PX = 2, PY = 3
  const gid = `gf-${id}`

  // 실데이터(일봉)가 있으면 가격 라인 + 볼린저 밴드(20, 2σ)
  const bb = series && series.length >= 25 ? bollinger(series) : null
  if (bb && bb.length >= 2) {
    const minV = Math.min(...bb.map(p => Math.min(p.lo, p.price)))
    const maxV = Math.max(...bb.map(p => Math.max(p.up, p.price)))
    const range = Math.max(maxV - minV, 1e-9)
    const toY = (v: number) => PY + ((maxV - v) / range) * (H - PY * 2)
    const toX = (i: number) => PX + (i / (bb.length - 1)) * (W - PX * 2)

    const pts = (sel: (p: BBPoint) => number) =>
      bb.map((p, i) => `${toX(i).toFixed(1)},${toY(sel(p)).toFixed(1)}`)
    const bandPath =
      `M${pts(p => p.up).join(' L')} L${pts(p => p.lo).reverse().join(' L')} Z`
    const midPath = `M${pts(p => p.mid).join(' L')}`
    const pricePath = `M${pts(p => p.price).join(' L')}`
    const last = bb[bb.length - 1]

    return (
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}
        style={{ flex: `0 0 ${W}px`, display: 'block', overflow: 'visible' }}>
        {/* 볼린저 밴드 영역 */}
        <path d={bandPath} fill={color} fillOpacity="0.13" />
        {/* 상·하단 밴드 라인 */}
        <path d={`M${pts(p => p.up).join(' L')}`} fill="none"
          stroke={color} strokeOpacity="0.4" strokeWidth="0.7" />
        <path d={`M${pts(p => p.lo).join(' L')}`} fill="none"
          stroke={color} strokeOpacity="0.4" strokeWidth="0.7" />
        {/* 중심선(SMA20) 점선 */}
        <path d={midPath} fill="none" stroke="rgba(255,255,255,0.3)"
          strokeWidth="0.7" strokeDasharray="2,2" />
        {/* 가격 라인 */}
        <path d={pricePath} fill="none" stroke={color} strokeWidth="1.6"
          strokeLinecap="round" strokeLinejoin="round" />
        <circle cx={toX(bb.length - 1)} cy={toY(last.price)} r="2.2" fill={color} />
      </svg>
    )
  }

  // 폴백: 시리즈 없으면 기존 3포인트 베지어 스파크라인
  const p0 = 0, p1 = chg20d - chg5d, p2 = chg20d
  const allV = [p0, p1, p2]
  const span = Math.max(Math.abs(p2 - p0), Math.abs(p1), 0.5)
  const minV = Math.min(...allV) - span * 0.18
  const maxV = Math.max(...allV) + span * 0.18
  const range = maxV - minV
  const toY = (v: number) => PY + ((maxV - v) / range) * (H - PY * 2)
  const x0 = PX, x1 = W / 2, x2 = W - PX
  const y0 = toY(p0), y1 = toY(p1), y2 = toY(p2)
  const yBase = Math.min(toY(0), H - PY)
  const mx = (x0 + x1) / 2, mx2 = (x1 + x2) / 2
  const linePath = `M${x0},${y0} C${mx},${y0} ${mx},${y1} ${x1},${y1} C${mx2},${y1} ${mx2},${y2} ${x2},${y2}`
  const areaPath = `${linePath} L${x2},${H} L${x0},${H} Z`

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}
      style={{ flex: `0 0 ${W}px`, display: 'block', overflow: 'visible' }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor={color} stopOpacity="0.45" />
          <stop offset="100%" stopColor={color} stopOpacity="0.03" />
        </linearGradient>
      </defs>
      <line x1={PX} y1={yBase} x2={W - PX} y2={yBase}
        stroke="rgba(255,255,255,0.18)" strokeWidth="0.8" strokeDasharray="2.5,2.5" />
      <path d={areaPath} fill={`url(#${gid})`} />
      <path d={linePath} fill="none" stroke={color} strokeWidth="1.7"
        strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={x2} cy={y2} r="2.4" fill={color} />
    </svg>
  )
}

// ─── Sector Grid ─────────────────────────────────────────────────────────────
// 원형 도넛 → 3×3 사각형 그리드 (동=1위, 시계방향)
// 각 셀: 섹터 태그 + 점수 + 생애주기 + 대표 종목 3개(14거래일 수익률)

function SectorGrid({ sectors, macro }: { sectors: SectorItem[]; macro: MacroDetail }) {
  if (sectors.length < 2) return null

  const displayed = sectors.slice(0, 8)

  // E(1위) → SE(2위) → S(3위) → SW(4위) → W(5위) → NW(6위) → N(7위) → NE(8위)
  const AREA_MAP = ['e', 'se', 's', 'sw', 'w', 'nw', 'n', 'ne'] as const
  const DIR_LABEL: Record<string, string> = {
    e: 'E ▶', se: 'SE', s: 'S', sw: 'SW', w: 'W', nw: 'NW', n: 'N', ne: 'NE',
  }

  return (
    <div style={{
      background: 'rgba(6,9,22,0.92)',
      border: '1px solid rgba(255,255,255,0.08)',
      borderRadius: 16,
      padding: '12px 12px 10px',
      marginBottom: 24,
    }}>
      <p style={{ fontSize: 10, color: 'rgba(255,255,255,0.2)', letterSpacing: 3, textAlign: 'center', marginBottom: 10 }}>
        SECTOR ROTATION COMPASS · 동(E) = 1위 주도 섹터 · 시계방향 순위 · 종목: 당일 등락 (보조: 14거래일) · 장중 15분 갱신
      </p>

      <div style={{
        display: 'grid',
        gridTemplateAreas: '"nw n ne" "w c e" "sw s se"',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: 5,
        width: '100%',
      }}>

        {/* ── 중앙: 매크로 패널 (Google Finance style) ── */}
        <div style={{
          gridArea: 'c',
          background: 'linear-gradient(160deg, rgba(15,17,35,0.98), rgba(4,7,18,0.99))',
          border: '1px solid rgba(99,102,241,0.25)',
          borderRadius: 10,
          display: 'flex', flexDirection: 'column',
          padding: '9px 10px',
          minHeight: 148,
          gap: 4,
        }}>
          {([
            {
              id: 'nasdaq',
              label: '나스닥',
              val: macro.nasdaq != null ? macro.nasdaq.toLocaleString(undefined, { maximumFractionDigits: 0 }) : '—',
              chg: macro.nasdaqChg5d,
              chg5d: macro.nasdaqChg5d ?? 0,
              chg20d: macro.nasdaqChg20d ?? 0,
              color: (macro.nasdaqChg5d ?? 0) >= 0 ? '#34d399' : '#f87171',
            },
            {
              id: 'krw',
              label: '달러/원',
              val: macro.usKrw != null ? macro.usKrw.toLocaleString(undefined, { maximumFractionDigits: 1 }) : '—',
              chg: macro.usKrwChg5d,
              chg5d: macro.usKrwChg5d ?? 0,
              chg20d: macro.usKrwChg20d ?? 0,
              color: (macro.usKrwChg5d ?? 0) >= 0 ? '#f87171' : '#34d399',
            },
            {
              id: 'oil',
              label: '유가(WTI)',
              val: macro.oil != null ? macro.oil.toFixed(1) : '—',
              chg: macro.oilChg5d,
              chg5d: macro.oilChg5d ?? 0,
              chg20d: macro.oilChg20d ?? 0,
              color: (macro.oilChg5d ?? 0) >= 0 ? '#fbbf24' : '#60a5fa',
            },
            {
              id: 'tnx',
              label: '미 10Y',
              val: macro.tnx != null ? macro.tnx + '%' : '—',
              chg: macro.tnxChg5d,
              chg5d: macro.tnxChg5d ?? 0,
              chg20d: macro.tnx20dChg ?? 0,
              color: (macro.tnxChg5d ?? 0) >= 0 ? '#f87171' : '#34d399',
            },
          ] as const).map(({ id, label, val, chg, chg5d, chg20d, color }) => (
            <div key={id} style={{
              flex: 1,
              display: 'flex', flexDirection: 'column', justifyContent: 'center',
              borderBottom: id !== 'tnx' ? '1px solid rgba(255,255,255,0.05)' : 'none',
              paddingBottom: id !== 'tnx' ? 3 : 0,
            }}>
              {/* top row: label + change% */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 1 }}>
                <span style={{ fontSize: 9.5, color: 'rgba(255,255,255,0.38)', letterSpacing: 0.2 }}>{label}</span>
                {chg != null && (
                  <span style={{ fontSize: 10, fontWeight: 700, color }}>
                    {chg >= 0 ? '+' : ''}{chg.toFixed(1)}%
                  </span>
                )}
              </div>
              {/* bottom row: chart + value */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <MiniChart chg5d={chg5d} chg20d={chg20d} color={color} id={id}
                  series={macro.series1d?.[id]} />
                <span style={{ fontSize: 13.5, fontWeight: 700, color: '#f1f5f9', flex: 1, textAlign: 'right', letterSpacing: -0.3 }}>
                  {val}
                </span>
              </div>
            </div>
          ))}
        </div>

        {/* ── 8개 섹터 셀 ── */}
        {displayed.map((item, i) => {
          const area = AREA_MAP[i]
          const color = SCORE_COLOR(item.score)
          const lcColor = LIFECYCLE_COLORS[item.lifecycleStage] ?? '#6b7280'
          const isTop = i === 0
          const stocks = item.leadStocks ?? []

          return (
            <div key={item.sector} style={{
              gridArea: area,
              background: `linear-gradient(145deg, ${color}${isTop ? '16' : '0b'}, rgba(4,7,18,0.94))`,
              border: `1px solid ${isTop ? color + '55' : 'rgba(255,255,255,0.07)'}`,
              borderRadius: 10,
              padding: '10px 11px',
              display: 'flex', flexDirection: 'column', gap: 5,
              minHeight: 148,
              position: 'relative',
            }}>
              {/* 섹터 태그 + 순위 방향 */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{
                  fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 99,
                  background: color + '22', color, border: `1px solid ${color}44`,
                  maxWidth: '68%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>{item.sector}</span>
                <span style={{
                  fontSize: 9, color: isTop ? '#fbbf24' : 'rgba(255,255,255,0.2)',
                  fontWeight: isTop ? 700 : 400, flexShrink: 0,
                }}>#{i + 1} {DIR_LABEL[area]}</span>
              </div>

              {/* 점수 + 생애주기 */}
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                <span style={{ fontSize: 24, fontWeight: 800, color, lineHeight: 1 }}>{item.score}</span>
                <span style={{ fontSize: 10, color: lcColor }}>{item.lifecycle}</span>
              </div>

              {/* 구분선 */}
              <div style={{ height: 1, background: 'rgba(255,255,255,0.07)' }} />

              {/* 대표 종목 3개 (14거래일 수익률) */}
              {stocks.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {stocks.slice(0, 3).map(stock => {
                    const today = stock.changeToday
                    return (
                      <div key={stock.code} style={{
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 4,
                      }}>
                        <span style={{
                          fontSize: 11, color: 'rgba(241,245,249,0.78)',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                          flex: 1, minWidth: 0,
                        }}>{stock.name}</span>
                        {today != null && (
                          <span style={{
                            fontSize: 11, fontWeight: 700, flexShrink: 0,
                            color: today >= 0 ? '#34d399' : '#f87171',
                          }}>
                            {today >= 0 ? '+' : ''}{today.toFixed(1)}%
                          </span>
                        )}
                        <span style={{
                          fontSize: 9.5, fontWeight: 400, flexShrink: 0,
                          color: stock.change14d >= 0 ? 'rgba(52,211,153,0.5)' : 'rgba(248,113,113,0.5)',
                        }}>
                          14d {stock.change14d >= 0 ? '+' : ''}{stock.change14d.toFixed(0)}%
                        </span>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.15)' }}>수집 중...</span>
              )}
            </div>
          )
        })}
      </div>

      {/* 범례 */}
      <div style={{
        display: 'flex', gap: 16, fontSize: 11, flexWrap: 'wrap',
        color: 'rgba(255,255,255,0.25)', marginTop: 10, justifyContent: 'center',
      }}>
        <span><span style={{ color: '#34d399' }}>●</span> 75+ 강매집</span>
        <span><span style={{ color: '#60a5fa' }}>●</span> 55–74 유입</span>
        <span><span style={{ color: '#eab308' }}>●</span> 40–54 중립</span>
        <span><span style={{ color: '#f87171' }}>●</span> ~39 약세</span>
      </div>
    </div>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

const CACHE_KEY = 'apolloSectorCache'
const CACHE_TS_KEY = 'apolloSectorCacheTs'
const REFRESH_INTERVAL = 15 * 60 * 1000  // 15분 — 장중엔 백엔드가 새로 계산, 장외엔 캐시 반환이라 부담 없음

function loadCached(): { data: RotationData | null; stale: boolean; savedAt: number } {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    const ts = Number(localStorage.getItem(CACHE_TS_KEY) ?? '0')
    if (raw) return { data: JSON.parse(raw) as RotationData, stale: true, savedAt: ts }
  } catch { /* ignore */ }
  return { data: null, stale: false, savedAt: 0 }
}

function fmtCountdown(ms: number): string {
  if (ms <= 0) return '갱신 중...'
  const totalSec = Math.ceil(ms / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return m > 0 ? `${m}분 ${s}초 후 갱신` : `${s}초 후 갱신`
}

export function SectorRotationPage({ publicMode = false }: { publicMode?: boolean } = {}) {
  const init = loadCached()
  const [data, setData] = useState<RotationData | null>(init.data)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [stale, setStale] = useState(init.stale)
  const [nextRefreshAt, setNextRefreshAt] = useState<number>(init.savedAt ? init.savedAt + REFRESH_INTERVAL : 0)
  const [countdown, setCountdown] = useState<string>('')
  const timerRef = useRef<number | null>(null)
  const countdownRef = useRef<number | null>(null)

  const load = useCallback(async (force = false) => {
    setLoading(true)
    setError(null)
    try {
      const res = publicMode
        ? await publicFetch<RotationData>('/api/public/sector-rotation')
        : await fetchJson<RotationData>(`/api/sector-rotation${force ? '?force=true' : ''}`)
      setData(res)
      setStale(false)
      const now = Date.now()
      const next = now + REFRESH_INTERVAL
      setNextRefreshAt(next)
      try {
        localStorage.setItem(CACHE_KEY, JSON.stringify(res))
        localStorage.setItem(CACHE_TS_KEY, String(now))
      } catch { /* ignore */ }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '데이터 로드 실패')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [publicMode])

  // 카운트다운 타이머 (1초마다 갱신)
  useEffect(() => {
    const tick = () => {
      if (nextRefreshAt <= 0) { setCountdown(''); return }
      const remaining = nextRefreshAt - Date.now()
      setCountdown(remaining > 0 ? fmtCountdown(remaining) : '갱신 중...')
    }
    tick()
    countdownRef.current = window.setInterval(tick, 1000)
    return () => { if (countdownRef.current) window.clearInterval(countdownRef.current) }
  }, [nextRefreshAt])

  useEffect(() => {
    load()
    timerRef.current = window.setInterval(() => load(), REFRESH_INTERVAL)
    return () => { if (timerRef.current) window.clearInterval(timerRef.current) }
  }, [load])

  const handleForceRefresh = () => {
    setRefreshing(true)
    load(true)
  }

  // 로딩 중이면서 이미 캐시 데이터가 있으면 배너만 표시 (빈 화면 X)
  const showLoadingBanner = loading && !data
  const showStaleBanner   = stale && loading && !!data

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1100, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
        <div>
          <h2 style={{ fontSize: 22, fontWeight: 700, color: '#f1f5f9', margin: 0 }}>
            🧭 KOSPI 섹터 로테이션 나침반
          </h2>
          <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)', marginTop: 4 }}>
            7-Layer Score: 매크로 · 외국인수급 · 기관수급 · 모멘텀 · 뉴스 · 거래대금 · 스마트머니
          </p>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
          {!publicMode && (
            <button
              onClick={handleForceRefresh}
              disabled={loading || refreshing}
              style={{
                padding: '7px 14px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.15)',
                background: 'rgba(255,255,255,0.06)', color: '#f1f5f9', fontSize: 12,
                cursor: loading ? 'wait' : 'pointer', fontFamily: 'inherit',
              }}
            >
              {refreshing ? '⏳ 재계산 중...' : '↺ 강제 갱신'}
            </button>
          )}
          {data && (
            <div style={{ textAlign: 'right' }}>
              <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)', display: 'block' }}>
                {showStaleBanner
                  ? '⏳ 새 데이터 수집 중...'
                  : stale
                    ? '📦 이전 저장본'
                    : data.cached ? '📦 서버캐시' : '🔄 신선'} · {data.asOf}
              </span>
              {countdown && !showStaleBanner && (
                <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.2)', display: 'block', marginTop: 2 }}>
                  🕐 {countdown}
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div style={{
          background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)',
          borderRadius: 8, padding: '12px 16px', color: '#fca5a5', marginBottom: 16, fontSize: 13,
        }}>
          ⚠️ {error}
        </div>
      )}

      {/* Loading skeleton - 캐시가 없을 때만 전체 대기 화면 */}
      {showLoadingBanner && (
        <div style={{ textAlign: 'center', padding: '80px 0', color: 'rgba(255,255,255,0.3)' }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>⏳</div>
          <p style={{ fontSize: 14 }}>데이터 수집 중... (최초 약 30~60초 소요)</p>
          <p style={{ fontSize: 12, marginTop: 6 }}>외국인/기관 수급 데이터를 KRX에서 수집합니다</p>
        </div>
      )}

      {/* 캐시 표시 중 새 데이터 로딩 배너 */}
      {showStaleBanner && (
        <div style={{
          background: 'rgba(234,179,8,0.07)', border: '1px solid rgba(234,179,8,0.2)',
          borderRadius: 8, padding: '8px 14px', color: 'rgba(234,179,8,0.7)',
          marginBottom: 12, fontSize: 12, display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span style={{ animation: 'spin 1.2s linear infinite', display: 'inline-block' }}>⏳</span>
          이전 저장 데이터를 표시 중입니다. 새 수급 데이터 수집 중...
        </div>
      )}

      {data && (
        <>
          <SectorGrid sectors={data.sectors} macro={data.macroDetail} />

          {/* TOP 3 highlights */}
          {data.topSectors.length > 0 && (
            <div style={{
              background: 'linear-gradient(135deg, rgba(52,211,153,0.08), rgba(96,165,250,0.08))',
              border: '1px solid rgba(52,211,153,0.2)',
              borderRadius: 12, padding: '12px 16px', marginBottom: 16,
              display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap',
            }}>
              <span style={{ fontSize: 13, color: '#34d399', fontWeight: 600 }}>🏆 주도 섹터 TOP 3</span>
              {data.topSectors.map((s, i) => (
                <span key={s} style={{
                  fontSize: 13, padding: '4px 12px', borderRadius: 99,
                  background: i === 0 ? 'rgba(251,191,36,0.2)' : 'rgba(52,211,153,0.1)',
                  color: i === 0 ? '#fbbf24' : '#34d399',
                  border: `1px solid ${i === 0 ? '#fbbf2440' : '#34d39940'}`,
                }}>
                  {i + 1}위 {s}
                </span>
              ))}
              {data.warningSectors.length > 0 && (
                <>
                  <span style={{ fontSize: 13, color: '#f87171', fontWeight: 600, marginLeft: 8 }}>⚠️ 위험</span>
                  {data.warningSectors.map(s => (
                    <span key={s} style={{ fontSize: 13, color: '#f87171' }}>{s}</span>
                  ))}
                </>
              )}
            </div>
          )}

          {/* Macro summary */}
          <div style={{ marginBottom: 16 }}>
            <MacroCard detail={data.macroDetail} />
          </div>

          {/* Lifecycle pipeline */}
          <div style={{ marginBottom: 20 }}>
            <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)', marginBottom: 8 }}>
              섹터 생애주기 파이프라인
            </p>
            <LifecyclePipeline sectors={data.sectors} />
          </div>

          {/* Sector ranking */}
          <div style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)' }}>
                섹터 점수 순위 (클릭 → 레이어별 상세)
              </p>
              <LifecycleLegend />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {data.sectors.map((item, i) => (
                <SectorCard
                  key={item.sector}
                  item={item}
                  rank={i + 1}
                  expanded={expanded === item.sector}
                  onToggle={() => setExpanded(expanded === item.sector ? null : item.sector)}
                />
              ))}
            </div>
          </div>

          {/* Footer note */}
          <div style={{
            fontSize: 11, color: 'rgba(255,255,255,0.25)',
            borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 12, lineHeight: 1.6,
          }}>
            ※ 수급 데이터: KRX 공식 데이터(pykrx) — 블룸버그돈 트거미널이 한국 주식에 사용하는 같은 한국거래소 원천
            <br />
            ※ 매크로: Yahoo Finance(TNX/DXY/VIX) · 캐시 TTL 8시간 | 강제 갱신 시 30~60초 소요 | 투자 참고용 정보이며 투자 권유가 아닙니다
          </div>
        </>
      )}
    </div>
  )
}
