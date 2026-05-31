import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchJson } from '../lib/api'

// ─── Types ──────────────────────────────────────────────────────────────────

interface MacroDetail {
  tnx?: number | null
  dxy?: number | null
  vix?: number
  tnx20dChg?: number
  dxy20dChg?: number
  growthScore?: number
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
}

interface SectorDetail {
  foreignBil: number
  institutionalBil: number
  momentumPct: number
  volumeSurgePct: number
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

const fmtBil = (v: number) => {
  if (v === 0) return '—'
  return (v >= 0 ? '+' : '') + v.toFixed(0) + '억'
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
      <div style={{ display: 'grid', gridTemplateColumns: '28px 1fr auto auto auto', gap: 10, alignItems: 'center' }}>
        {/* Rank */}
        <span style={{
          fontSize: 13, fontWeight: 700, color: rank <= 3 ? '#fbbf24' : 'rgba(255,255,255,0.4)',
          textAlign: 'center',
        }}>#{rank}</span>

        {/* Sector name */}
        <span style={{ fontSize: 15, fontWeight: 600, color: '#f1f5f9' }}>{item.sector}</span>

        {/* Lifecycle badge */}
        <span style={{
          fontSize: 11, padding: '3px 8px', borderRadius: 99,
          background: lcBg, color: lcColor, border: `1px solid ${lcColor}40`,
          whiteSpace: 'nowrap',
        }}>
          {item.lifecycle}
        </span>

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
        <div style={{ color: 'rgba(255,255,255,0.5)' }}>
          외국인 <span style={{ color: item.detail.foreignBil >= 0 ? '#34d399' : '#f87171' }}>
            {fmtBil(item.detail.foreignBil)}
          </span>
        </div>
        <div style={{ color: 'rgba(255,255,255,0.5)' }}>
          기관 <span style={{ color: item.detail.institutionalBil >= 0 ? '#34d399' : '#f87171' }}>
            {fmtBil(item.detail.institutionalBil)}
          </span>
        </div>
        <div style={{ color: 'rgba(255,255,255,0.5)' }}>
          모멘텀 <span style={{ color: item.detail.momentumPct >= 0 ? '#34d399' : '#f87171' }}>
            {fmtPct(item.detail.momentumPct)}
          </span>
        </div>
        <div style={{ color: 'rgba(255,255,255,0.5)' }}>
          거래대금 <span style={{ color: item.detail.volumeSurgePct >= 0 ? '#34d399' : '#f87171' }}>
            {fmtPct(item.detail.volumeSurgePct)}
          </span>
        </div>
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

function MacroCard({ detail }: { detail: MacroDetail }) {
  const items: [string, string | number | null | undefined, string?][] = [
    ['미국 10Y', detail.tnx != null ? detail.tnx + '%' : '—',
      detail.tnx20dChg != null ? fmtPct(detail.tnx20dChg) + ' (20d)' : undefined],
    ['달러(DXY)', detail.dxy ?? '—',
      detail.dxy20dChg != null ? fmtPct(detail.dxy20dChg) + ' (20d)' : undefined],
    ['VIX', detail.vix ?? '—', undefined],
    ['성장주 우호도', detail.growthScore != null ? detail.growthScore + ' / 100' : '—', undefined],
  ]

  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
      gap: 10, background: 'rgba(255,255,255,0.03)',
      border: '1px solid rgba(255,255,255,0.08)',
      borderRadius: 12, padding: '14px 16px',
    }}>
      {items.map(([label, val, sub]) => (
        <div key={label}>
          <p style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', marginBottom: 2 }}>{label}</p>
          <p style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9' }}>{val}</p>
          {sub && <p style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)' }}>{sub}</p>}
        </div>
      ))}
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

// ─── Sector Compass ────────────────────────────────────────────────────────────

function SectorCompass({ sectors }: { sectors: SectorItem[] }) {
  if (sectors.length < 2) return null

  const SZ = 520
  const cx = 260, cy = 260
  const OR = 142   // outer radius (normal)
  const TR = 160   // outer radius (rank-1, protrudes)
  const IR = 54    // inner radius (center hole)
  const BM = OR - 6  // max radar bar radius

  const toRad = (d: number) => (d * Math.PI) / 180
  const polar  = (r: number, d: number) => ({ x: cx + r * Math.cos(toRad(d)), y: cy + r * Math.sin(toRad(d)) })

  const donut = (r1: number, r2: number, sDeg: number, eDeg: number) => {
    const a = polar(r1, sDeg), b = polar(r1, eDeg)
    const c = polar(r2, eDeg), d = polar(r2, sDeg)
    const lg = eDeg - sDeg > 180 ? 1 : 0
    return `M${a.x.toFixed(1)},${a.y.toFixed(1)} A${r1},${r1} 0 ${lg},1 ${b.x.toFixed(1)},${b.y.toFixed(1)} L${c.x.toFixed(1)},${c.y.toFixed(1)} A${r2},${r2} 0 ${lg},0 ${d.x.toFixed(1)},${d.y.toFixed(1)}Z`
  }

  // 시계방향 · 동(E=0°)=1위, SE=2위, S=3위, SW=4위, W=5위, NW=6위, N=7위, NE=8위
  const pos = sectors.slice(0, 8).map((item, i) => ({ item, i, cDeg: i * 45, isTop: i === 0 }))
  const best = sectors[0]
  const bestColor = SCORE_COLOR(best.score)

  const radarPts = pos
    .map(({ item, cDeg }) => {
      const r = IR + (BM - IR) * Math.max(0.05, item.score / 100)
      const p = polar(r, cDeg)
      return `${p.x.toFixed(1)},${p.y.toFixed(1)}`
    })
    .join(' ')

  return (
    <div style={{
      background: 'rgba(6,9,22,0.92)',
      border: '1px solid rgba(255,255,255,0.08)',
      borderRadius: 16,
      padding: '16px 16px 12px',
      marginBottom: 24,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
    }}>
      <p style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)', letterSpacing: 2, marginBottom: 6 }}>
        SECTOR ROTATION COMPASS · 동(E) = 1위 주도 섹터 · 시계방향 순위
      </p>

      <svg
        viewBox={`0 0 ${SZ} ${SZ}`}
        width={SZ}
        style={{ width: '100%', maxWidth: SZ, display: 'block', overflow: 'visible' }}
      >
        <defs>
          <filter id="cGlow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <radialGradient id="eastGlow" cx="72%" cy="50%" r="40%">
            <stop offset="0%" stopColor={bestColor} stopOpacity="0.18" />
            <stop offset="100%" stopColor={bestColor} stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* East ambient glow */}
        <ellipse cx={cx} cy={cy} rx={SZ * 0.44} ry={SZ * 0.44} fill="url(#eastGlow)" />

        {/* Guide rings (33 / 67 / 100) */}
        {[0.33, 0.67, 1.0].map((f) => (
          <circle key={f} cx={cx} cy={cy} r={IR + (BM - IR) * f}
            fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth={1} strokeDasharray="3 9" />
        ))}
        {[{ f: 0.33, l: '33' }, { f: 0.67, l: '67' }, { f: 1.0, l: '100' }].map(({ f, l }) => {
          const p = polar(IR + (BM - IR) * f, 258)
          return <text key={l} x={p.x + 3} y={p.y + 3} fill="rgba(255,255,255,0.12)" fontSize={8}>{l}</text>
        })}

        {/* Axis dividers */}
        {[0, 45, 90, 135].map((d) => {
          const a = polar(IR, d), b = polar(OR + 2, d)
          const a2 = polar(IR, d + 180), b2 = polar(OR + 2, d + 180)
          return (
            <g key={d}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="rgba(255,255,255,0.07)" strokeWidth={1} />
              <line x1={a2.x} y1={a2.y} x2={b2.x} y2={b2.y} stroke="rgba(255,255,255,0.07)" strokeWidth={1} />
            </g>
          )
        })}

        {/* Donut segments */}
        {pos.map(({ item, cDeg, isTop }) => {
          const color = SCORE_COLOR(item.score)
          const r = isTop ? TR : OR
          const alpha = 0.3 + (item.score / 100) * 0.55
          return (
            <g key={'seg-' + item.sector}>
              <path d={donut(r, IR, cDeg - 21.5, cDeg + 21.5)}
                fill={color} opacity={alpha} stroke="rgba(0,0,0,0.55)" strokeWidth={1.5} />
              {isTop && (
                <path d={donut(r + 5, IR, cDeg - 21.5, cDeg + 21.5)}
                  fill="none" stroke={color} strokeWidth={2.5} opacity={0.7} filter="url(#cGlow)" />
              )}
            </g>
          )
        })}

        {/* Radar polygon */}
        <polygon points={radarPts}
          fill="rgba(148,163,184,0.06)" stroke="rgba(148,163,184,0.22)" strokeWidth={1.5} />

        {/* Radar dots */}
        {pos.map(({ item, cDeg, isTop }) => {
          const r = IR + (BM - IR) * Math.max(0.05, item.score / 100)
          const p = polar(r, cDeg)
          const color = SCORE_COLOR(item.score)
          return (
            <g key={'dot-' + item.sector}>
              {isTop && <circle cx={p.x} cy={p.y} r={11} fill={color} opacity={0.18} filter="url(#cGlow)" />}
              <circle cx={p.x} cy={p.y} r={isTop ? 6.5 : 3.5}
                fill={color} stroke="rgba(0,0,0,0.55)" strokeWidth={1.5} />
            </g>
          )
        })}

        {/* Rank numbers inside segments */}
        {pos.map(({ item, cDeg, i, isTop }) => {
          const p = polar((isTop ? TR : OR) - 14, cDeg)
          return (
            <text key={'rk-' + item.sector} x={p.x} y={p.y + 4} textAnchor="middle"
              fill={isTop ? '#fbbf24' : 'rgba(255,255,255,0.35)'}
              fontSize={isTop ? 13 : 10} fontWeight={700}>{i + 1}</text>
          )
        })}

        {/* Center circle */}
        <circle cx={cx} cy={cy} r={IR} fill="rgba(4,7,18,0.98)" stroke={bestColor} strokeWidth={2} />
        <text x={cx} y={cy - 17} textAnchor="middle" fill="rgba(255,255,255,0.2)" fontSize={8} letterSpacing={2}>주도섹터</text>
        <text x={cx} y={cy + 2}  textAnchor="middle" fill="#f1f5f9" fontSize={13} fontWeight={700}>{best.sector}</text>
        <text x={cx} y={cy + 21} textAnchor="middle" fill={bestColor} fontSize={20} fontWeight={800}>{best.score}</text>

        {/* Outer labels */}
        {pos.map(({ item, cDeg, isTop }) => {
          const p = polar((isTop ? TR : OR) + 46, cDeg)
          const lc = LIFECYCLE_COLORS[item.lifecycleStage] ?? '#6b7280'
          return (
            <g key={'lbl-' + item.sector}>
              <text x={p.x} y={p.y - 9} textAnchor="middle"
                fill={isTop ? '#fbbf24' : 'rgba(241,245,249,0.85)'}
                fontSize={isTop ? 13 : 11} fontWeight={isTop ? 700 : 500}>{item.sector}</text>
              <text x={p.x} y={p.y + 5} textAnchor="middle"
                fill={SCORE_COLOR(item.score)} fontSize={12} fontWeight={700}>{item.score}</text>
              <text x={p.x} y={p.y + 17} textAnchor="middle"
                fill={lc} fontSize={8.5}>{item.lifecycle}</text>
            </g>
          )
        })}

        {/* East arrow indicator */}
        {(() => {
          const tip = polar(TR + 14, 0)
          return (
            <polygon
              points={`${(tip.x + 11).toFixed(1)},${tip.y.toFixed(1)} ${tip.x.toFixed(1)},${(tip.y - 6).toFixed(1)} ${tip.x.toFixed(1)},${(tip.y + 6).toFixed(1)}`}
              fill="#fbbf24" opacity={0.95} filter="url(#cGlow)" />
          )
        })()}

        {/* Cardinal direction labels */}
        {[{ d: 0, l: 'E' }, { d: 90, l: 'S' }, { d: 180, l: 'W' }, { d: 270, l: 'N' }].map(({ d, l }) => {
          const isE = d === 0
          const p = polar((isE ? TR : OR) + 78, d)
          return (
            <text key={l} x={p.x} y={p.y + 4} textAnchor="middle"
              fill={isE ? 'rgba(251,191,36,0.55)' : 'rgba(255,255,255,0.12)'}
              fontSize={isE ? 13 : 10} fontWeight={isE ? 700 : 400}>{l}</text>
          )
        })}
      </svg>

      {/* Score legend */}
      <div style={{ display: 'flex', gap: 20, fontSize: 11, color: 'rgba(255,255,255,0.3)', marginTop: 8 }}>
        <span><span style={{ color: '#34d399' }}>●</span> 75+ 강매집</span>
        <span><span style={{ color: '#60a5fa' }}>●</span> 55–74 유입</span>
        <span><span style={{ color: '#eab308' }}>●</span> 40–54 중립</span>
        <span><span style={{ color: '#f87171' }}>●</span> ~39 약세</span>
      </div>
    </div>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

export function SectorRotationPage() {
  const [data, setData] = useState<RotationData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const timerRef = useRef<number | null>(null)

  const load = useCallback(async (force = false) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetchJson<RotationData>(`/api/sector-rotation${force ? '?force=true' : ''}`)
      setData(res)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '데이터 로드 실패')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    load()
    timerRef.current = window.setInterval(() => load(), 60 * 60 * 1000)  // 1시간마다 갱신
    return () => { if (timerRef.current) window.clearInterval(timerRef.current) }
  }, [load])

  const handleForceRefresh = () => {
    setRefreshing(true)
    load(true)
  }

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
          {data && (
            <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)' }}>
              {data.cached ? '📦 캐시' : '🔄 신선'} · {data.asOf}
            </span>
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

      {/* Loading skeleton */}
      {loading && !data && (
        <div style={{ textAlign: 'center', padding: '80px 0', color: 'rgba(255,255,255,0.3)' }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>⏳</div>
          <p style={{ fontSize: 14 }}>데이터 수집 중... (최초 약 30~60초 소요)</p>
          <p style={{ fontSize: 12, marginTop: 6 }}>외국인/기관 수급 데이터를 KRX에서 수집합니다</p>
        </div>
      )}

      {data && (
        <>
          <SectorCompass sectors={data.sectors} />

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
            <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)', marginBottom: 8 }}>
              Layer 1 · 거시경제 지표
            </p>
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
            ※ 수급 데이터: KRX(pykrx) / 매크로: Yahoo Finance / 뉴스 레이어: 업데이트 예정 (현재 50점 고정)
            <br />
            ※ 캐시 TTL 1시간 | 강제 갱신 시 30~60초 소요 | 투자 참고용 정보이며 투자 권유가 아닙니다
          </div>
        </>
      )}
    </div>
  )
}
