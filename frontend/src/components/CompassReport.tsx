/* 시장 나침반 12단계 분석 — "3초 안에 투자 아이디어가 보이는" 뉴스레터 스타일 리포트.
   모바일 우선(1열, max 680px), 차트 중심, 인포그래픽, 데이터 스토리텔링.
   입력: ai_analysis_cache.result_json (source = market-compass-12stage) */

type Dict = Record<string, any>

const GRADE_COLOR: Record<string, string> = {
  S: '#fbbf24', A: '#34d399', B: '#60a5fa', C: '#eab308', D: '#f87171',
}
const SIGNAL_LABEL: Record<string, string> = {
  STRONG_BUY: '적극 매수', BUY: '매수', HOLD: '관망', SELL: '매도', STRONG_SELL: '적극 매도',
}
const fmt = (n: number | null | undefined) =>
  n == null ? 'N/A' : Math.round(n).toLocaleString()

const card: React.CSSProperties = {
  background: 'rgba(13,18,34,0.9)', border: '1px solid rgba(255,255,255,0.09)',
  borderRadius: 14, padding: '14px 16px', marginBottom: 12,
}
const sectionTitle: React.CSSProperties = {
  fontSize: 11, letterSpacing: 2, color: '#64748b', margin: '0 0 10px', fontWeight: 700,
}

// ── 헤드라인 한 줄 결론 (데이터 → 문장 자동 생성) ───────────────────────────
function headline(p: Dict): string {
  const sig = SIGNAL_LABEL[p.composite?.grade >= 'S' ? '' : ''] // unused guard
  void sig
  const grade = p.composite?.grade
  const regime = p.market?.regime?.label ?? ''
  const up = p.targets?.avgTargetUpside
  const action =
    grade === 'S' || grade === 'A' ? '진입 검토 구간' :
    grade === 'B' ? (regime.includes('위기') ? '위기 장세 — 조건 충족 전까지 관망' : '조건부 접근') :
    '리스크 우위 — 회피'
  return `${action}${up != null ? ` · 평균 목표까지 +${up}%` : ''}`
}

// ── 자동 추세선: 스윙 고/저점 검출 → 최근 두 점 연결 ────────────────────────
// n봉 좌우보다 높은/낮은 점 = 스윙. 마지막 두 스윙 저점 연결 = 지지 추세선,
// 마지막 두 스윙 고점 연결 = 저항 추세선. 차트 우측 끝까지 연장.
function autoTrendlines(closes: number[], n = 4) {
  const highs: number[] = []
  const lows: number[] = []
  for (let i = n; i < closes.length - n; i++) {
    const win = closes.slice(i - n, i + n + 1)
    if (closes[i] === Math.max(...win)) highs.push(i)
    if (closes[i] === Math.min(...win)) lows.push(i)
  }
  const line = (idx: number[]) => {
    if (idx.length < 2) return null
    const [i1, i2] = idx.slice(-2)
    if (i2 === i1) return null
    const slope = (closes[i2] - closes[i1]) / (i2 - i1)
    return { i1, i2, slope, at: (x: number) => closes[i1] + slope * (x - i1) }
  }
  return { support: line(lows), resistance: line(highs) }
}

// ── 핵심 차트: 종가 120봉 + 목표/손절 + 자동 추세선 + 매물대 + MTF 추세 ──────
// 현재가는 가로 0.618 지점에서 반짝이고, 우측 38.2% 공간에 설명·가격 표시.
function PriceChart({ p }: { p: Dict }) {
  const closes: number[] = p.series?.closes ?? []
  const dates: string[] = p.series?.dates ?? []
  if (closes.length < 10) return null
  const cur = closes[closes.length - 1]
  const target = p.targets?.avgTarget as number | null
  const stop = (p.stops?.['기술적 손절']?.price ?? p.stops?.['구조 손절']?.price) as number | null

  const W = 680, H = 400, PX = 10, PT = 34, PB = 24
  const GOLDEN = 0.618
  const plotEnd = PX + (W - PX * 2) * GOLDEN // 현재가 위치 (황금비)

  // 목표가 5종 → 차트 우측 가격 사다리 (이상치·N/A 제외)
  const TARGET_SHORT: Record<string, string> = {
    '피보나치 확장 1.272': '피보나치',
    '거래량 프로파일 저항': '매물대 저항',
    '과거 사이클 평균': '과거 사이클',
    '기관 컨센서스': '기관 목표',
    '섹터 밸류에이션': '밸류에이션',
  }
  // 유효한 목표가만: 평균 계산에 포함된 것(이상치 제외)이면서 현재가보다 위에 있는 것
  const indivTargets: Array<{ label: string; price: number }> = Object.entries(
    (p.targets?.list ?? {}) as Dict,
  )
    .filter(([, t]) => {
      const d = t as Dict
      return d?.price && !d.excluded && d.price > cur && d.price <= cur * 2.0
    })
    .map(([k, t]) => ({ label: TARGET_SHORT[k] ?? k, price: (t as Dict).price as number }))

  const lo = Math.min(...closes, stop ?? Infinity) * 0.985
  const hi = Math.max(...closes, target ?? 0, ...indivTargets.map(t => t.price)) * 1.015
  const toX = (i: number) => PX + (i / (closes.length - 1)) * (plotEnd - PX)
  const toY = (v: number) => PT + ((hi - v) / (hi - lo)) * (H - PT - PB)
  const curX = toX(closes.length - 1)
  const curY = toY(cur)

  // 자동 추세선 — 우측 미래 영역까지 연장, 차트 경계에서 클립
  const tl = autoTrendlines(closes)
  const extIdx = (closes.length - 1) * (0.92 / GOLDEN) // x≈92% 지점까지 연장
  const trendSeg = (t: { i1: number; at: (x: number) => number } | null) => {
    if (!t) return null
    const y1v = t.at(t.i1)
    if (y1v < lo || y1v > hi) return null
    let xe = extIdx
    let ye = t.at(xe)
    if (ye < lo || ye > hi) {
      // 경계와의 교차점에서 자르기
      const bound = ye < lo ? lo : hi
      xe = t.i1 + (bound - y1v) / ((t.at(t.i1 + 1) - y1v) || 1e-9)
      if (xe <= t.i1) return null
      ye = bound
    }
    return { x1: toX(t.i1), y1: toY(y1v), x2: PX + (xe / (closes.length - 1)) * (plotEnd - PX), y2: toY(ye) }
  }
  const supSeg = trendSeg(tl.support)
  const resSeg = trendSeg(tl.resistance)

  // 매물대 (MTF 일봉 거래량 프로파일) — 가격 밴드로 표시
  const dailyTf = (p.mtf?.timeframes ?? []).find((t: Dict) => t.label === '일봉')
  const zones: Dict[] = (dailyTf?.volumeProfile ?? []).filter(
    (z: Dict) => z.priceTo > lo && z.priceFrom < hi,
  )
  const biggest = zones.length ? Math.max(...zones.map((z: Dict) => z.volumePct)) : 0

  // MTF 추세 화살표 (패널 대신 차트 상단에 통합)
  const TF_SHORT: Record<string, string> = {
    '월봉': '월', '주봉': '주', '일봉': '일', '60분(5일)': '60분', '15분(5일)': '15분',
  }
  const arrows = (p.mtf?.timeframes ?? []).map((t: Dict) => {
    const tr = String(t.trend ?? '')
    return {
      label: TF_SHORT[t.label] ?? t.label,
      glyph: t.error ? '·' : tr.includes('상승') ? '▲' : tr.includes('하락') ? '▼' : '▬',
      color: t.error ? '#475569' : tr.includes('상승') ? '#34d399' : tr.includes('하락') ? '#f87171' : '#eab308',
    }
  })

  const path = closes.map((c, i) => `${i === 0 ? 'M' : 'L'}${toX(i).toFixed(1)},${toY(c).toFixed(1)}`).join(' ')
  const area = `${path} L${curX},${H - PB} L${toX(0)},${H - PB} Z`
  const dlabel = (idx: number) => {
    const d = dates[idx] ?? ''
    return d.length === 8 ? `${d.slice(2, 4)}.${d.slice(4, 6)}` : d
  }

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', display: 'block' }}>
      <defs>
        <linearGradient id="cr-area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#60a5fa" stopOpacity="0.26" />
          <stop offset="100%" stopColor="#60a5fa" stopOpacity="0.02" />
        </linearGradient>
      </defs>

      {/* MTF 추세 통합 스트립 (차트 상단) */}
      <text x={PX} y={16} fontSize="11" fill="#64748b" fontWeight="700">추세</text>
      {arrows.map((a: { label: string; glyph: string; color: string }, i: number) => (
        <text key={a.label} x={PX + 38 + i * 64} y={16} fontSize="11.5" fill={a.color} fontWeight="800">
          {a.label} {a.glyph}
        </text>
      ))}

      {/* 매물대 밴드 */}
      {zones.map((z: Dict, i: number) => {
        const yTop = Math.max(toY(Math.min(z.priceTo, hi)), PT)
        const yBot = Math.min(toY(Math.max(z.priceFrom, lo)), H - PB)
        if (yBot <= yTop) return null
        const main = z.volumePct === biggest
        return (
          <g key={i}>
            <rect x={PX} y={yTop} width={W - PX * 2} height={yBot - yTop}
              fill="#94a3b8" fillOpacity={main ? 0.1 : 0.055} />
            {main && (
              <text x={PX + 4} y={yTop + 12} fontSize="10" fill="#94a3b8">
                매물대 {z.volumePct}%
              </text>
            )}
          </g>
        )
      })}

      {/* 평균 목표가 */}
      {target && (
        <>
          <line x1={PX} y1={toY(target)} x2={W - PX} y2={toY(target)}
            stroke="#34d399" strokeWidth="1.6" strokeDasharray="5,4" />
          <text x={W - PX} y={toY(target) - 6} textAnchor="end" fontSize="12" fill="#34d399" fontWeight="800">
            평균 목표 {fmt(target)} (+{p.targets?.avgTargetUpside}%)
          </text>
        </>
      )}

      {/* 목표가 산출 5종 — 우측 가격 사다리 (겹침 방지 정렬) */}
      {(() => {
        const items = indivTargets
          .map(t => ({ ...t, y: toY(t.price) }))
          .filter(t => t.y > PT + 8 && t.y < H - PB - 8)
          .sort((a, b) => a.y - b.y)
        // 라벨 겹침 방지: 위에서부터 최소 14px 간격으로 밀어내기
        let prevY = -Infinity
        const placed = items.map(t => {
          const ly = Math.max(t.y, prevY + 14)
          prevY = ly
          return { ...t, ly }
        })
        return placed.map(t => (
          <g key={t.label}>
            <line x1={W * 0.8} y1={t.y} x2={W - PX - 4} y2={t.y}
              stroke="#6ee7b7" strokeWidth="1" strokeOpacity="0.5" strokeDasharray="2,3" />
            <circle cx={W * 0.8} cy={t.y} r="2.2" fill="#6ee7b7" fillOpacity="0.8" />
            <text x={W * 0.8 - 5} y={t.ly + 3.5} textAnchor="end" fontSize="9.8" fill="#6ee7b7" fillOpacity="0.85">
              {t.label} {fmt(t.price)}
            </text>
          </g>
        ))
      })()}
      {/* 손절가 */}
      {stop && (
        <>
          <line x1={PX} y1={toY(stop)} x2={W - PX} y2={toY(stop)}
            stroke="#f87171" strokeWidth="1.4" strokeDasharray="5,4" />
          <text x={W - PX} y={toY(stop) + 15} textAnchor="end" fontSize="12" fill="#f87171" fontWeight="700">
            손절 {fmt(stop)} ({((stop / cur - 1) * 100).toFixed(1)}%)
          </text>
        </>
      )}

      <path d={area} fill="url(#cr-area)" />

      {/* 자동 추세선 (미래 영역까지 연장) */}
      {supSeg && (
        <>
          <line {...supSeg} stroke="#a78bfa" strokeWidth="1.5" strokeOpacity="0.85" />
          <text x={supSeg.x2 + 4} y={supSeg.y2 + 4} fontSize="10.5" fill="#a78bfa">지지 추세선</text>
        </>
      )}
      {resSeg && (
        <>
          <line {...resSeg} stroke="#f59e0b" strokeWidth="1.5" strokeOpacity="0.85" />
          <text x={resSeg.x2 + 4} y={resSeg.y2 + 4} fontSize="10.5" fill="#f59e0b">저항 추세선</text>
        </>
      )}

      <path d={path} fill="none" stroke="#60a5fa" strokeWidth="2.2" strokeLinejoin="round" />

      {/* 현재가 — 0.618 지점에서 펄스 + 우측 설명 */}
      <circle cx={curX} cy={curY} r="5" fill="#f1f5f9" opacity="0.5">
        <animate attributeName="r" values="5;13;5" dur="1.8s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0.5;0;0.5" dur="1.8s" repeatCount="indefinite" />
      </circle>
      <circle cx={curX} cy={curY} r="4.2" fill="#f1f5f9">
        <animate attributeName="opacity" values="1;0.55;1" dur="1.8s" repeatCount="indefinite" />
      </circle>
      <line x1={curX + 8} y1={curY} x2={curX + 26} y2={curY} stroke="rgba(241,245,249,0.4)" strokeWidth="1" />
      <text x={curX + 30} y={curY - 3} fontSize="11" fill="#94a3b8">현재가</text>
      <text x={curX + 30} y={curY + 13} fontSize="14.5" fill="#f1f5f9" fontWeight="800">
        {fmt(cur)}원
      </text>

      {/* x축 날짜 (가격 구간만) */}
      <text x={PX} y={H - 7} fontSize="10" fill="#475569">{dlabel(0)}</text>
      <text x={(PX + plotEnd) / 2} y={H - 7} fontSize="10" fill="#475569" textAnchor="middle">
        {dlabel(Math.floor(closes.length / 2))}
      </text>
      <text x={plotEnd} y={H - 7} fontSize="10" fill="#475569" textAnchor="middle">{dlabel(closes.length - 1)}</text>
    </svg>
  )
}

// ── 섹터 로테이션 맵 (현금→방어→경기민감→성장→테마) ─────────────────────────
function RotationMap({ p }: { p: Dict }) {
  const ladder = p.market?.rotationLadder
  if (!ladder) return null
  const steps: string[] = ladder.ladder ?? ['현금', '방어주', '경기민감주', '성장주', '고위험 테마주']
  const groups: Dict = ladder.groups ?? {}
  const pos = ladder.position

  return (
    <div style={card}>
      <p style={sectionTitle}>섹터 로테이션 맵 — 자금의 현재 위치</p>
      <div style={{ display: 'flex', gap: 4 }}>
        {steps.map((s, i) => {
          const g = groups[s]
          const active = s === pos
          const chg = g?.avgIntraday
          return (
            <div key={s} style={{ flex: 1, textAlign: 'center', position: 'relative' }}>
              <div style={{
                padding: '10px 2px 8px', borderRadius: 10,
                background: active ? 'rgba(251,191,36,0.16)' : 'rgba(255,255,255,0.04)',
                border: `1.5px solid ${active ? '#fbbf24' : 'rgba(255,255,255,0.08)'}`,
              }}>
                {active && <div style={{ fontSize: 14, lineHeight: 1, marginBottom: 3 }}>📍</div>}
                <div style={{
                  fontSize: 11.5, fontWeight: active ? 800 : 600,
                  color: active ? '#fbbf24' : 'rgba(241,245,249,0.65)',
                  wordBreak: 'keep-all',
                }}>{s}</div>
                {chg != null && (
                  <div style={{ fontSize: 11, fontWeight: 700, marginTop: 2, color: chg >= 0 ? '#34d399' : '#f87171' }}>
                    {chg >= 0 ? '+' : ''}{chg}%
                  </div>
                )}
              </div>
              {i < steps.length - 1 && (
                <span style={{
                  position: 'absolute', right: -7, top: '50%', transform: 'translateY(-50%)',
                  color: '#475569', fontSize: 11, zIndex: 1,
                }}>▸</span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── 주도 섹터 순위 (막대 인포그래픽) ─────────────────────────────────────────
function SectorRanking({ p }: { p: Dict }) {
  const ranking: Dict[] = p.market?.sectorRanking ?? []
  if (!ranking.length) return null
  const max = Math.max(...ranking.map(r => r.score ?? 0), 1)
  const mySector = p.stock?.sector

  return (
    <div style={card}>
      <p style={sectionTitle}>주도 섹터 순위</p>
      {ranking.slice(0, 10).map(r => {
        const mine = r.sector === mySector
        const top3 = r.rank <= 3
        return (
          <div key={r.sector} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 0' }}>
            <span style={{
              width: 86, fontSize: 12, fontWeight: mine ? 800 : 600, flexShrink: 0,
              color: mine ? '#fbbf24' : top3 ? '#f1f5f9' : 'rgba(241,245,249,0.55)',
            }}>
              {r.rank}. {r.sector}{mine ? ' ★' : ''}
            </span>
            <div style={{ flex: 1, height: 14, background: 'rgba(255,255,255,0.05)', borderRadius: 7, overflow: 'hidden' }}>
              <div style={{
                width: `${(r.score / max) * 100}%`, height: '100%', borderRadius: 7,
                background: mine
                  ? 'linear-gradient(90deg, #b45309, #fbbf24)'
                  : top3
                    ? 'linear-gradient(90deg, #1d4ed8, #60a5fa)'
                    : 'rgba(96,165,250,0.3)',
              }} />
            </div>
            <span style={{ width: 32, fontSize: 11.5, textAlign: 'right', color: 'rgba(241,245,249,0.7)' }}>{r.score}</span>
            <span style={{
              width: 48, fontSize: 11.5, textAlign: 'right', fontWeight: 700,
              color: (r.intradayPct ?? 0) >= 0 ? '#34d399' : '#f87171',
            }}>
              {(r.intradayPct ?? 0) >= 0 ? '+' : ''}{r.intradayPct}%
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ── 확률 — "과거 비슷한 상황 100번 중 몇 번?" 와플 차트 (자연빈도 표현) ───────
function ProbBar({ p }: { p: Dict }) {
  const pr = p.probability ?? {}
  const reach = Math.round(Number(pr.reachTargetPct ?? 0))
  const stopP = Math.round(Number(pr.hitStopPct ?? 0))
  const und = Math.max(0, 100 - reach - stopP)
  const contUp = pr.continueUpPct != null ? Math.round(Number(pr.continueUpPct) / 10) : null
  if (!reach && !stopP) return null

  // 100개 점: 초록(목표 먼저) → 회색(결판 안 남) → 빨강(손절 먼저)
  const dots = [
    ...Array(reach).fill('#34d399'),
    ...Array(und).fill('rgba(255,255,255,0.16)'),
    ...Array(stopP).fill('#f87171'),
  ].slice(0, 100)

  return (
    <div style={card}>
      <p style={sectionTitle}>📊 과거에 비슷한 상황에서는?</p>

      <p style={{ fontSize: 13.5, lineHeight: 1.7, color: 'rgba(241,245,249,0.85)', margin: '0 0 12px' }}>
        지금과 같은 추세 국면이 과거에 <b style={{ color: '#f1f5f9' }}>{pr.sample}번</b> 있었습니다.
        그때마다 100번 중 —
      </p>

      {/* 와플 차트: 10 × 10 */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(20, 1fr)', gap: 3,
        maxWidth: 420, margin: '0 auto 12px',
      }}>
        {dots.map((c, i) => (
          <div key={i} style={{ aspectRatio: '1', borderRadius: 2.5, background: c }} />
        ))}
      </div>

      {/* 쉬운 말 범례 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 16px', justifyContent: 'center', fontSize: 12.5 }}>
        <span><span style={{ color: '#34d399', fontWeight: 800 }}>● {reach}번</span> 목표가에 먼저 닿음</span>
        <span><span style={{ color: '#f87171', fontWeight: 800 }}>● {stopP}번</span> 손절가에 먼저 닿음</span>
        <span><span style={{ color: '#94a3b8', fontWeight: 800 }}>● {und}번</span> 두 달 안에 결판 안 남</span>
      </div>

      {/* 한 달 뒤 — 10칸 게이지 */}
      {contUp != null && (
        <p style={{ fontSize: 13, textAlign: 'center', marginTop: 14, color: 'rgba(241,245,249,0.8)' }}>
          한 달 뒤 가격이 올라 있던 경우 — 10번 중{' '}
          <b style={{ color: '#34d399', fontSize: 15 }}>{contUp}번</b>{' '}
          <span style={{ letterSpacing: 1.5 }}>
            <span style={{ color: '#34d399' }}>{'●'.repeat(contUp)}</span>
            <span style={{ color: 'rgba(255,255,255,0.15)' }}>{'●'.repeat(10 - contUp)}</span>
          </span>
        </p>
      )}

      <p style={{ fontSize: 11, color: '#64748b', textAlign: 'center', marginTop: 8 }}>
        {pr.lowConfidence ? '⚠ 과거 사례가 적어 참고만 하세요 · ' : ''}
        과거 통계일 뿐, 미래를 보장하지 않습니다
      </p>
    </div>
  )
}

// ── 간이 마크다운 (AI 스토리) ────────────────────────────────────────────────
function Story({ text }: { text: string }) {
  return (
    <div style={{ fontSize: 13.5, color: 'rgba(241,245,249,0.85)' }}>
      {text.split('\n').map((raw, i) => {
        const bold = (s: string) =>
          s.split(/(\*\*.+?\*\*)/).map((seg, j) =>
            seg.startsWith('**')
              ? <b key={j} style={{ color: '#f1f5f9' }}>{seg.slice(2, -2)}</b>
              : seg)
        if (raw.startsWith('# ')) return <h3 key={i} style={{ margin: '16px 0 8px', color: '#93c5fd' }}>{raw.slice(2)}</h3>
        if (raw.startsWith('## ')) return <h4 key={i} style={{ margin: '12px 0 6px', color: '#a5b4fc' }}>{raw.slice(3)}</h4>
        if (raw.trim() === '---') return <hr key={i} style={{ border: 'none', borderTop: '1px solid rgba(255,255,255,0.1)', margin: '12px 0' }} />
        if (/^\s*[*-]\s+/.test(raw)) {
          return (
            <p key={i} style={{ margin: '3px 0 3px 14px', lineHeight: 1.65 }}>
              <span style={{ color: '#64748b' }}>•</span> {bold(raw.replace(/^\s*[*-]\s+/, ''))}
            </p>
          )
        }
        if (raw.trim() === '') return <div key={i} style={{ height: 6 }} />
        return <p key={i} style={{ margin: '3px 0', lineHeight: 1.65 }}>{bold(raw)}</p>
      })}
    </div>
  )
}

// ── AI 리포트 섹션 분해 ("# 제목" 기준) ─────────────────────────────────────
function splitSections(text: string): Array<{ title: string; body: string }> {
  const out: Array<{ title: string; body: string }> = []
  let title = ''
  let buf: string[] = []
  const flush = () => {
    const body = buf.join('\n').replace(/^[\s-]*\n/, '').replace(/\n[\s-]*$/, '').trim()
    if (title || body) out.push({ title, body })
    buf = []
  }
  for (const line of text.split('\n')) {
    if (line.startsWith('# ')) {
      flush()
      title = line.slice(2).trim()
    } else {
      buf.push(line)
    }
  }
  flush()
  return out
}

// ── 메인 리포트 ──────────────────────────────────────────────────────────────
export function CompassReport({ data }: { data: Dict }) {
  const comp = data.composite ?? {}
  const stock = data.stock ?? {}
  const grade = comp.grade ?? '?'
  const gradeColor = GRADE_COLOR[grade] ?? '#94a3b8'
  const score = comp.score
  const signal =
    score >= 80 ? 'STRONG_BUY' : score >= 70 ? 'BUY' : score >= 55 ? 'HOLD' : score >= 40 ? 'SELL' : 'STRONG_SELL'
  const regime = data.market?.regime?.label
  const stops = data.stops ?? {}
  const stopPrice = stops['기술적 손절']?.price ?? stops['구조 손절']?.price
  const cur = stock.currentPrice

  // AI 리포트 섹션 분해: 종목 평가는 제목·차트와 중복이라 제외,
  // 투자 행동·시나리오는 차트 바로 아래, 나머지(시장 해석)는 하단 노트로.
  const sections = data.aiReport ? splitSections(String(data.aiReport)) : []
  const actionSec = sections.find(s => s.title.includes('투자 행동'))
  const scenarioSec = sections.find(s => s.title.includes('시나리오') || s.title.includes('불확실'))
  const restSecs = sections.filter(s =>
    s !== actionSec && s !== scenarioSec && !s.title.includes('종목 평가'))

  return (
    <div style={{ maxWidth: 680, margin: '0 auto' }}>
      {/* ── 헤드라인 배너: 3초 결론 ── */}
      <div style={{
        ...card,
        background: `linear-gradient(135deg, ${gradeColor}1c, rgba(13,18,34,0.95))`,
        border: `1.5px solid ${gradeColor}55`,
        display: 'flex', alignItems: 'center', gap: 16,
      }}>
        <div style={{ textAlign: 'center', flexShrink: 0 }}>
          <div style={{ fontSize: 44, fontWeight: 900, lineHeight: 1, color: gradeColor }}>{grade}</div>
          <div style={{ fontSize: 11, color: gradeColor, fontWeight: 700, marginTop: 2 }}>{score}점</div>
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 17, fontWeight: 800 }}>
            {stock.name} <span style={{ color: '#64748b', fontSize: 12 }}>{stock.code}</span>
          </div>
          <div style={{ fontSize: 13, color: 'rgba(241,245,249,0.75)', marginTop: 2 }}>
            {fmt(cur)}원 · {stock.sector} {stock.sectorRank}위 · <b style={{ color: gradeColor }}>{SIGNAL_LABEL[signal]}</b>
            {regime ? ` · ${regime}` : ''}
          </div>
          <div style={{ fontSize: 13.5, fontWeight: 700, color: '#f1f5f9', marginTop: 5 }}>
            💡 {headline(data)}
          </div>
        </div>
      </div>

      {/* ── 3대 숫자 ── */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
        {[
          { l: '평균 목표가', v: fmt(data.targets?.avgTarget), s: data.targets?.avgTargetUpside != null ? `+${data.targets.avgTargetUpside}%` : '', c: '#34d399' },
          { l: '손절가', v: fmt(stopPrice), s: stopPrice && cur ? `${((stopPrice / cur - 1) * 100).toFixed(1)}%` : '', c: '#f87171' },
          { l: '손익비', v: comp.riskReward ?? 'N/A', s: `상승지속 ${data.probability?.continueUpPct ?? '-'}%`, c: '#60a5fa' },
        ].map(x => (
          <div key={x.l} style={{ ...card, flex: 1, textAlign: 'center', marginBottom: 0, padding: '12px 8px' }}>
            <div style={{ fontSize: 10.5, color: '#64748b', letterSpacing: 1 }}>{x.l}</div>
            <div style={{ fontSize: 18, fontWeight: 800, color: x.c, marginTop: 3 }}>{x.v}</div>
            <div style={{ fontSize: 11, color: 'rgba(241,245,249,0.55)', marginTop: 1 }}>{x.s}</div>
          </div>
        ))}
      </div>

      {/* ── 핵심 차트 ── */}
      {data.series?.closes?.length > 10 && (
        <div style={card}>
          <p style={sectionTitle}>핵심 차트 — 가격 vs 목표·손절 (일봉 120)</p>
          <PriceChart p={data} />
        </div>
      )}

      {/* ── 투자 행동 + 반대 시나리오 (차트 직하 — 행동으로 직결) ── */}
      {actionSec && (
        <div style={{ ...card, borderColor: 'rgba(52,211,153,0.3)' }}>
          <p style={sectionTitle}>🎯 투자 행동</p>
          <Story text={actionSec.body} />
        </div>
      )}
      {scenarioSec && (
        <div style={{ ...card, borderColor: 'rgba(248,113,113,0.25)' }}>
          <p style={sectionTitle}>⚠ 불확실성 · 반대 시나리오</p>
          <Story text={scenarioSec.body} />
        </div>
      )}

      <ProbBar p={data} />

      {/* ── AI 시장 해석 (남은 섹션) ── */}
      {restSecs.length > 0 && (
        <div style={card}>
          <p style={sectionTitle}>AI 시장 해석 <span style={{ letterSpacing: 0 }}>({data.aiProvider})</span></p>
          {restSecs.map((s, i) => (
            <div key={i}>
              {s.title && <h4 style={{ margin: '10px 0 6px', color: '#a5b4fc' }}>{s.title}</h4>}
              <Story text={s.body} />
            </div>
          ))}
        </div>
      )}

      {/* ── 시장 배경 (종목 판단의 맥락 — 참고용이라 맨 아래) ── */}
      <RotationMap p={data} />
      <SectorRanking p={data} />

      <p style={{ fontSize: 10.5, color: '#475569', textAlign: 'center', margin: '4px 0 8px' }}>
        {data.asOf} 기준 · 모든 수치는 데이터 계산, AI는 해석만 · 확률은 과거 빈도 — 투자 권유 아님
      </p>
    </div>
  )
}
