import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchJson } from '../lib/api'

// ─── Types ──────────────────────────────────────────────────────────────────

interface MacroDetail {
  tnx?: number | null
  dxy?: number | null
  vix?: number
  tnx20dChg?: number
  tnxChg5d?: number
  dxy20dChg?: number
  growthScore?: number
  nasdaq?: number | null
  nasdaqChg5d?: number
  nasdaqChg20d?: number
  usKrw?: number | null
  usKrwChg5d?: number
  usKrwChg20d?: number
  oil?: number | null
  oilChg5d?: number
  oilChg20d?: number
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

interface LeadStock {
  code: string
  name: string
  change14d: number
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

// ─── Mini Chart (Google Finance style) ──────────────────────────────────────
// chg5d: 최근 5거래일 변화율, chg20d: 최근 20거래일 변화율
// 3-anchor bezier area chart: start(day-20) → mid(day-5) → end(today)
function MiniChart({ chg5d = 0, chg20d = 0, color, id }: {
  chg5d?: number; chg20d?: number; color: string; id: string
}) {
  const W = 64, H = 28, PX = 2, PY = 3

  // 3 anchor pct values relative to day-20 baseline
  const p0 = 0                   // day -20
  const p1 = chg20d - chg5d      // day -5
  const p2 = chg20d              // day  0

  const allV = [p0, p1, p2]
  const span = Math.max(Math.abs(p2 - p0), Math.abs(p1), 0.5)  // min span to prevent flat
  const minV = Math.min(...allV) - span * 0.18
  const maxV = Math.max(...allV) + span * 0.18
  const range = maxV - minV

  const toY = (v: number) => PY + ((maxV - v) / range) * (H - PY * 2)

  const x0 = PX, x1 = W / 2, x2 = W - PX
  const y0 = toY(p0), y1 = toY(p1), y2 = toY(p2)
  const yBase = Math.min(toY(0), H - PY)  // baseline clipped to bottom

  // smooth bezier through 3 points (midpoint control points)
  const mx = (x0 + x1) / 2, mx2 = (x1 + x2) / 2
  const linePath = `M${x0},${y0} C${mx},${y0} ${mx},${y1} ${x1},${y1} C${mx2},${y1} ${mx2},${y2} ${x2},${y2}`
  const areaPath = `${linePath} L${x2},${H} L${x0},${H} Z`

  const gid = `gf-${id}`

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}
      style={{ flex: `0 0 ${W}px`, display: 'block', overflow: 'visible' }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor={color} stopOpacity="0.45" />
          <stop offset="100%" stopColor={color} stopOpacity="0.03" />
        </linearGradient>
      </defs>
      {/* baseline dashed */}
      <line x1={PX} y1={yBase} x2={W - PX} y2={yBase}
        stroke="rgba(255,255,255,0.18)" strokeWidth="0.8" strokeDasharray="2.5,2.5" />
      {/* area fill */}
      <path d={areaPath} fill={`url(#${gid})`} />
      {/* line */}
      <path d={linePath} fill="none" stroke={color} strokeWidth="1.7"
        strokeLinecap="round" strokeLinejoin="round" />
      {/* end dot */}
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
        SECTOR ROTATION COMPASS · 동(E) = 1위 주도 섹터 · 시계방향 순위 · 종목 수익률: 14거래일
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
                <MiniChart chg5d={chg5d} chg20d={chg20d} color={color} id={id} />
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
                  {stocks.slice(0, 3).map(stock => (
                    <div key={stock.code} style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 4,
                    }}>
                      <span style={{
                        fontSize: 11, color: 'rgba(241,245,249,0.78)',
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        flex: 1, minWidth: 0,
                      }}>{stock.name}</span>
                      <span style={{
                        fontSize: 11, fontWeight: 700, flexShrink: 0,
                        color: stock.change14d >= 0 ? '#34d399' : '#f87171',
                      }}>
                        {stock.change14d >= 0 ? '+' : ''}{stock.change14d.toFixed(1)}%
                      </span>
                    </div>
                  ))}
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
const REFRESH_INTERVAL = 8 * 60 * 60 * 1000  // 8시간 (KRX 일일 데이터 기준)

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

export function SectorRotationPage() {
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
      const res = await fetchJson<RotationData>(`/api/sector-rotation${force ? '?force=true' : ''}`)
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
  }, [])

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
            ※ 수급 데이터: KRX 공식 데이터(pykrx) — 블룸버그돈 트거미널이 한국 주식에 사용하는 같은 한국거래소 원천
            <br />
            ※ 매크로: Yahoo Finance(TNX/DXY/VIX) · 캐시 TTL 8시간 | 강제 갱신 시 30~60초 소요 | 투자 참고용 정보이며 투자 권유가 아닙니다
          </div>
        </>
      )}
    </div>
  )
}
