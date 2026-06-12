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

// ══════════════════════════════════════════════════════════════════════════
// 퀀트 자동 추세선 엔진 (8단계)
// Pivot → ZigZag(max(3%,ATR×2)) → 중요도 점수 → C(N,2) 페어 채점 → Top-N
// ══════════════════════════════════════════════════════════════════════════

// ATR (Wilder 14기간)
function qtATR(highs: number[], lows: number[], closes: number[], period = 14): number[] {
  const n = highs.length
  const trs = highs.map((h, i) =>
    i === 0 ? h - lows[i]
    : Math.max(h - lows[i], Math.abs(h - closes[i - 1]), Math.abs(lows[i] - closes[i - 1])),
  )
  const atrs = new Array(n).fill(0)
  let sum = 0
  for (let i = 1; i <= period && i < n; i++) sum += trs[i]
  if (period < n) {
    atrs[period] = sum / period
    for (let i = period + 1; i < n; i++)
      atrs[i] = (atrs[i - 1] * (period - 1) + trs[i]) / period
  }
  return atrs
}

// 거래량 단순 이동평균
function qtVolSMA(volumes: number[], period = 20): number[] {
  const n = volumes.length
  const out = new Array(n).fill(0)
  for (let i = period - 1; i < n; i++) {
    let s = 0
    for (let j = i - period + 1; j <= i; j++) s += volumes[j]
    out[i] = s / period
  }
  return out
}

// 피벗 고점·저점 탐지 (좌우 n봉 중 최고/최저)
function qtPivots(prices: number[], n: number, isHigh: boolean): Array<{ idx: number; price: number }> {
  const result: Array<{ idx: number; price: number }> = []
  for (let i = n; i < prices.length - n; i++) {
    let isPivot = true
    for (let j = i - n; j <= i + n; j++) {
      if (j === i) continue
      if (isHigh ? prices[j] >= prices[i] : prices[j] <= prices[i]) { isPivot = false; break }
    }
    if (isPivot) result.push({ idx: i, price: prices[i] })
  }
  return result
}

// ZigZag 필터: 직전 피벗과 swing이 max(zzPct%, ATR×zzAtrMul) 미만이면 제거
function qtZigZag(
  pivots: Array<{ idx: number; price: number }>,
  atrs: number[], zzPct: number, zzAtrMul: number,
): Array<{ idx: number; price: number }> {
  const out: Array<{ idx: number; price: number }> = []
  for (const p of pivots) {
    if (!out.length) { out.push(p); continue }
    const last = out[out.length - 1]
    const minSwing = Math.max(last.price * zzPct / 100, (atrs[p.idx] || 0.001) * zzAtrMul)
    if (Math.abs(p.price - last.price) >= minSwing) out.push(p)
  }
  return out
}

// 피벗 중요도 점수 (0~10)
// 거래량·반전폭·꼬리·스파이크 반영
function qtPivotScore(
  idx: number, isHigh: boolean,
  highs: number[], lows: number[], closes: number[],
  volumes: number[], volMAs: number[], atrs: number[],
): number {
  let sc = 5.0
  const vr = (volumes[idx] || 0) / Math.max(volMAs[idx] || 1, 1)
  sc += Math.min(2.0, (vr - 1) * 1.5)
  const rev = (highs[idx] - lows[idx]) / Math.max(atrs[idx] || 0.001, 0.001)
  sc += Math.min(2.0, (rev - 0.5) * 1.5)
  const range = Math.max(highs[idx] - lows[idx], 0.001)
  const prev = closes[Math.max(0, idx - 1)]
  const bodyTop = Math.max(closes[idx], prev), bodyBot = Math.min(closes[idx], prev)
  const wick = isHigh ? (highs[idx] - bodyTop) / range : (bodyBot - lows[idx]) / range
  sc -= Math.min(2.0, wick * 3)
  if (vr > 5) sc -= 1
  return Math.max(0, Math.min(10, sc))
}

// 추세선 페어 채점 (6요소 합산)
// returns [totalScore, touches, duration]
function qtLineScore(
  i1: number, p1: number, i2: number, p2: number, ps1: number, ps2: number,
  isSup: boolean,
  highs: number[], lows: number[], volumes: number[], volMAs: number[], atrs: number[],
  atrTol: number,
): [number, number, number] {
  const N = lows.length
  const m = (p2 - p1) / Math.max(i2 - i1, 1)
  const b = p1 - m * i1
  const atr = atrs[Math.min(i2, N - 1)] || atrs[N - 1] || 1
  const tol = atr * atrTol
  let touches = 0, vSum = 0, dev = 0
  for (let i = i1; i < N; i++) {
    const lineY = m * i + b
    const chk = isSup ? lows[i] : highs[i]
    if (Math.abs(chk - lineY) <= tol) {
      touches++
      vSum += Math.min(3, (volumes[i] || 0) / Math.max(volMAs[i] || 1, 1))
    } else {
      if (isSup && lows[i] < lineY - tol * 2) dev -= 1.5
      if (!isSup && highs[i] > lineY + tol * 2) dev -= 1.5
    }
  }
  const tScore = touches >= 4 ? 40 : touches >= 3 ? 25 : touches >= 2 ? 10 : 0
  const dur = i2 - i1
  const dScore = Math.min(30, dur / 2)
  const vScore = Math.min(20, vSum * 2)
  const rScore = Math.min(10, 10 - (N - 1 - i2) * 0.05)
  const devP = Math.max(-25, dev * 3)
  const relSlope = Math.abs(m) / Math.max(atr, 0.001)
  const slopeP = relSlope > 45 ? -15 : relSlope < 0.05 ? -8 : 0
  return [tScore + dScore + vScore + rScore + devP + slopeP + (ps1 + ps2) * 0.8, touches, dur]
}

interface QuantLine {
  x1: number; y1: number; x2: number; y2: number   // 차트 좌표 (클립됨)
  cx1: number; cy1: number; cx2: number; cy2: number // 채널 평행선
  i1: number; i2: number                             // 데이터 인덱스
  p1: number; p2: number                             // 앵커 가격 (교차점 계산용)
  touches: number; dur: number; score: number
  isSup: boolean; rank: number
  rising: boolean            // 기울기 방향 — 색은 역할(지지/저항)이 아니라 이걸로 결정
  valNow: number; broken: boolean
  strength: '강' | '보통' | '약'
  fadeBar?: number | null   // 이탈/돌파 시작 봉 — 이 지점부터 우측 잠식
}

// Top-N 추세선 탐색 + 차트 좌표 변환
function qtFindLines(
  pivots: Array<{ idx: number; price: number; score: number }>,
  isSup: boolean,
  highs: number[], lows: number[], closes: number[],
  volumes: number[], volMAs: number[], atrs: number[],
  topN: number, minTouches: number, atrTol: number,
  lo: number, hi: number, extIdx: number, curIdx: number,
  toX: (i: number) => number, toY: (v: number) => number,
): QuantLine[] {
  const sz = pivots.length
  if (sz < 2) return []
  const N = lows.length

  // 모든 페어 채점
  const cands: Array<{ score: number; touches: number; dur: number; i1: number; p1: number; i2: number; p2: number; ps1: number; ps2: number }> = []
  for (let a = 0; a < sz - 1; a++) {
    for (let b2 = a + 1; b2 < sz; b2++) {
      const [sc, tch, dur] = qtLineScore(
        pivots[a].idx, pivots[a].price, pivots[b2].idx, pivots[b2].price,
        pivots[a].score, pivots[b2].score,
        isSup, highs, lows, volumes, volMAs, atrs, atrTol,
      )
      if (tch >= minTouches && sc > 0)
        cands.push({ score: sc, touches: tch, dur, i1: pivots[a].idx, p1: pivots[a].price, i2: pivots[b2].idx, p2: pivots[b2].price, ps1: pivots[a].score, ps2: pivots[b2].score })
    }
  }

  // 상위 N 선택
  const used = new Set<number>()
  const result: QuantLine[] = []
  for (let rank = 0; rank < topN; rank++) {
    let bi = -1, bsc = -1
    for (let k = 0; k < cands.length; k++)
      if (!used.has(k) && cands[k].score > bsc) { bsc = cands[k].score; bi = k }
    if (bi < 0) break
    used.add(bi)
    const c = cands[bi]
    const m = (c.p2 - c.p1) / Math.max(c.i2 - c.i1, 1)
    const b = c.p1 - m * c.i1
    const at = (i: number) => m * i + b

    // 차트 좌표 계산 (경계 클립)
    const clip = (v: number) => Math.min(Math.max(v, lo), hi)
    let xs = 0, ys = at(0)
    if (ys < lo || ys > hi) {
      const bound = ys < lo ? lo : hi
      xs = Math.abs(m) < 1e-9 ? 0 : (bound - at(0)) / m
      ys = bound
    }
    let xe = extIdx, ye = at(extIdx)
    if (ye < lo || ye > hi) {
      const bound = ye < lo ? lo : hi
      xe = Math.abs(m) < 1e-9 ? extIdx : (bound - at(0)) / m
      ye = bound
    }
    if (xe <= xs) continue

    // 채널: 1위 선 반대편 극값까지 평행 이동
    let maxDev = 0
    for (let i = c.i1; i < N; i++) {
      const lineY = at(i)
      const opp = isSup ? highs[i] - lineY : lineY - lows[i]
      if (opp > maxDev) maxDev = opp
    }
    const chanOff = isSup ? maxDev : -maxDev

    // 이탈/돌파 판정은 종가 기준 — 꼬리(저가/고가)가 선을 찔러도 종가가 지키면 유효.
    // 걸쳐있는(테스트 중) 상태를 이탈로 오판하지 않도록 0.5% 여유폭.
    const valNow = at(curIdx)
    const curClose = closes[curIdx] || 0
    const broken = isSup ? curClose < valNow * 0.995 : curClose > valNow * 1.005
    const strength: QuantLine['strength'] =
      c.touches >= 4 || (c.touches >= 3 && c.dur >= 60) ? '강'
      : c.touches >= 3 || (c.touches >= 2 && c.dur >= 30) ? '보통'
      : '약'

    result.push({
      x1: toX(xs), y1: toY(clip(ys)),
      x2: toX(xe), y2: toY(clip(ye)),
      cx1: toX(xs), cy1: toY(clip(ys + chanOff)),
      cx2: toX(xe), cy2: toY(clip(ye + chanOff)),
      i1: c.i1, i2: c.i2,
      p1: c.p1, p2: c.p2,
      touches: c.touches, dur: c.dur, score: bsc,
      isSup, rank,
      rising: m > 0,
      valNow, broken,
      strength,
    })
  }
  return result
}

// ── 핵심 차트: 종가 120봉 + 목표/손절 + 퀀트 자동 추세선 + 매물대 ──────────
// 현재가는 가로 0.618 지점에서 반짝이고, 우측 38.2% 공간에 설명·가격 표시.
function PriceChart({ p }: { p: Dict }) {
  const closes: number[] = p.series?.closes ?? []
  const dates: string[] = p.series?.dates ?? []
  const highs: number[] = p.series?.highs ?? closes      // 없으면 종가 폴백
  const lows: number[] = p.series?.lows ?? closes
  const volumes: number[] = p.series?.volumes ?? new Array(closes.length).fill(0)
  if (closes.length < 10) return null
  const cur = closes[closes.length - 1]
  const target = p.targets?.avgTarget as number | null

  // 손절 3종: 단기(기술적) / 중기(수급) / 절대(구조) — 실전 손절 단계
  const stopsMap: Dict = p.stops ?? {}
  const stopDefs = [
    { key: '기술적 손절', name: '단기 손절', weight: 700 },
    { key: '수급 손절', name: '중기 손절', weight: 700 },
    { key: '구조 손절', name: '절대 손절', weight: 800 },
  ]
    .map(d => ({ ...d, price: (stopsMap[d.key]?.price ?? null) as number | null }))
    .filter(d => d.price && d.price < cur)

  const W = 680, H = 400, PX = 10, PT = 20, PB = 24
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

  const lo = Math.min(...closes, ...lows, ...stopDefs.map(d => d.price as number)) * 0.985
  const hi = Math.max(...closes, ...highs, target ?? 0, ...indivTargets.map(t => t.price)) * 1.015
  const toX = (i: number) => PX + (i / (closes.length - 1)) * (plotEnd - PX)
  const toY = (v: number) => PT + ((hi - v) / (hi - lo)) * (H - PT - PB)
  const curX = toX(closes.length - 1)
  const curY = toY(cur)
  const curIdx = closes.length - 1
  const extIdx = (closes.length - 1) * (0.92 / GOLDEN)

  // ── 퀀트 자동 추세선 엔진 ────────────────────────────────────────────────
  const atrs = qtATR(highs, lows, closes)
  const volMAs = qtVolSMA(volumes)
  const atrMa = atrs.slice(-50).reduce((a, b) => a + b, 0) / Math.min(50, atrs.length) || 1

  // Dynamic pivot N: 현재 ATR이 평균의 1.5배 이상이면 10봉으로 확장
  const pivN = atrs[curIdx] > atrMa * 1.5 ? 10 : 5

  // 피벗 탐지 + ZigZag 필터 (두 세트 모두 탐지, 동적 선택)
  const rawPH5  = qtPivots(highs, 5,  true)
  const rawPH10 = qtPivots(highs, 10, true)
  const rawPL5  = qtPivots(lows,  5,  false)
  const rawPL10 = qtPivots(lows,  10, false)
  const rawPH = pivN === 10 ? rawPH10 : rawPH5
  const rawPL = pivN === 10 ? rawPL10 : rawPL5

  const ZZ_PCT = 3.0, ZZ_ATR = 2.0
  const phFiltered = qtZigZag(rawPH, atrs, ZZ_PCT, ZZ_ATR).slice(-12)
  const plFiltered = qtZigZag(rawPL, atrs, ZZ_PCT, ZZ_ATR).slice(-12)

  // 피벗 중요도 점수 부여
  const phPivots = phFiltered.map(v => ({
    ...v, score: qtPivotScore(v.idx, true,  highs, lows, closes, volumes, volMAs, atrs),
  }))
  const plPivots = plFiltered.map(v => ({
    ...v, score: qtPivotScore(v.idx, false, highs, lows, closes, volumes, volMAs, atrs),
  }))

  // Top-3 지지선 (녹색) + 저항선 (적색)
  const supRaw = qtFindLines(plPivots, true,  highs, lows, closes, volumes, volMAs, atrs, 3, 2, 0.5, lo, hi, extIdx, curIdx, toX, toY)
  const resRaw = qtFindLines(phPivots, false, highs, lows, closes, volumes, volMAs, atrs, 3, 2, 0.5, lo, hi, extIdx, curIdx, toX, toY)

  // ── 생애주기: 돌파당한 추세선은 페이드 → 반대 추세 확정 시 소멸 ──────────
  // 종가 기준 연속 이탈 run을 역산해:
  //   · run 3봉 이상 + 현재가가 선에서 ATR×4 초과 → 선 자체 제거 (의미 상실)
  //   · 그 전(현재가가 아직 선 부근 — 선이 하락/상승의 이유를 시각적으로 설명) → 페이드 유지
  const lifecycle = (t: QuantLine): QuantLine | null => {
    const m = (t.p2 - t.p1) / Math.max(t.i2 - t.i1, 1)
    const b0 = t.p1 - m * t.i1
    const atr = atrs[curIdx] || 1
    const dist = Math.abs(closes[curIdx] - (m * curIdx + b0)) / atr
    // 영향력 컷: 선의 현재 연장값이 현재가에서 ATR×6 초과 — 주가 판단에 영향 없음
    if (dist > 6) return null
    // 깨짐은 선의 방향과 반대 관통만: 상승선=아래로 이탈 / 하락선=위로 돌파.
    // 신고가로 상승선을 위로 뚫는 것은 가속이지 깨짐이 아님 — 녹색 유지.
    const beyond = (i: number) => {
      const lv = m * i + b0
      return t.rising ? closes[i] < lv * 0.995 : closes[i] > lv * 1.005
    }
    if (!beyond(curIdx)) return { ...t, broken: false, fadeBar: null }
    let bb = curIdx
    while (bb - 1 > t.i2 && beyond(bb - 1)) bb--
    if (curIdx - bb + 1 >= 3 && dist > 4) return null  // 추세 동력 상실 — 소멸
    return { ...t, broken: true, fadeBar: bb }
  }
  const supLines = supRaw.map(lifecycle).filter((t): t is QuantLine => t != null)
  const resLines = resRaw.map(lifecycle).filter((t): t is QuantLine => t != null)
  const allTrendLines = [...supLines, ...resLines]

  // 접촉 물듦: 현재가가 "지금" 닿아있는 선(ATR 이내)에서, 가격 진행 방향 색과
  // 선의 색이 다를 때만 접점이 살짝 물듦 (상승 압력=녹색 / 하락 압력=적색).
  // 미래 교차점(apex)은 물들지 않음 — 펄스 원이 담당.
  const atrNow = atrs[curIdx] || 1
  const priceUp = cur >= closes[Math.max(0, closes.length - 4)]
  const touchTint = allTrendLines.map(t => {
    if (Math.abs(cur - t.valNow) > atrNow) return null
    const tint = priceUp ? '#34d399' : '#f87171'
    return (t.rising ? '#34d399' : '#f87171') === tint ? null : tint
  })

  // ── 수렴 감지: 상승 지지선 ↔ 하락 저항선이 교차점을 향해 좁혀질 때 색 전이 ──
  // 교차점(apex)이 curIdx 기준 -20 ~ +80봉 범위 내에 있으면 활성화.
  // 지지선: 교차점 방향 끝이 붉게 물듦 (위협)
  // 저항선: 교차점 방향 끝이 녹색으로 물듦 (돌파 기대)
  interface ConvGrad {
    supIdx: number; resIdx: number
    ixBar: number   // apex bar index
    proximity: number  // 0→1 (0=80봉 전, 1=apex)
    supGradId: string; resGradId: string
  }
  const convGrads: ConvGrad[] = []
  for (let si = 0; si < supLines.length; si++) {
    const sup = supLines[si]
    const mSup = (sup.p2 - sup.p1) / Math.max(sup.i2 - sup.i1, 1)
    const bSup = sup.p1 - mSup * sup.i1
    for (let ri = 0; ri < resLines.length; ri++) {
      const res = resLines[ri]
      const mRes = (res.p2 - res.p1) / Math.max(res.i2 - res.i1, 1)
      const bRes = res.p1 - mRes * res.i1
      // 수렴 조건: 지지선 우상향(mSup>0), 저항선 우하향(mRes<0), 교차점이 두 선 시작보다 오른쪽
      if (mSup <= 0 || mRes >= 0) continue
      if (Math.abs(mSup - mRes) < 1e-9) continue
      const ixBar = (bRes - bSup) / (mSup - mRes)
      if (ixBar < Math.max(sup.i1, res.i1)) continue
      const barsToApex = ixBar - curIdx
      if (barsToApex < -20 || barsToApex > 80) continue
      const proximity = Math.max(0, Math.min(1, 1 - barsToApex / 80))
      convGrads.push({
        supIdx: si, resIdx: ri,
        ixBar, proximity,
        supGradId: `cg-sup-${si}-${ri}`,
        resGradId: `cg-res-${si}-${ri}`,
      })
    }
  }
  // 각 라인이 속한 최강 gradient 매핑
  const supGradMap: Record<number, ConvGrad> = {}
  const resGradMap: Record<number, ConvGrad> = {}
  for (const cg of convGrads) {
    if (!supGradMap[cg.supIdx] || cg.proximity > supGradMap[cg.supIdx].proximity)
      supGradMap[cg.supIdx] = cg
    if (!resGradMap[cg.resIdx] || cg.proximity > resGradMap[cg.resIdx].proximity)
      resGradMap[cg.resIdx] = cg
  }

  // 현재가 방향 계산용: 가장 가까운 지지선 값
  const nearestSupVal = supLines.length ? supLines[0].valNow : null
  const nearestResVal = resLines.length ? resLines[0].valNow : null

  // 매물대 (MTF 일봉 거래량 프로파일) — 가격 밴드로 표시
  const dailyTf = (p.mtf?.timeframes ?? []).find((t: Dict) => t.label === '일봉')
  const zones: Dict[] = (dailyTf?.volumeProfile ?? []).filter(
    (z: Dict) => z.priceTo > lo && z.priceFrom < hi,
  )
  const biggest = zones.length ? Math.max(...zones.map((z: Dict) => z.volumePct)) : 0

  // ICT FVG (미충전 갭 = 스마트머니 매물대) — 상승=지지(초록), 하락=저항(빨강)
  const fvgBull: Dict[] = (dailyTf?.fvg?.bullish ?? [])
    .filter((z: Dict) => z.top > lo && z.bottom < hi).slice(-2)
  const fvgBear: Dict[] = (dailyTf?.fvg?.bearish ?? [])
    .filter((z: Dict) => z.top > lo && z.bottom < hi).slice(-2)

  // 신고가 판정
  const high52w = (p.series?.high52w as number | undefined) ?? Math.max(...closes)
  const isNewHigh = Math.max(...closes.slice(-15)) >= high52w * 0.999
  void isNewHigh  // 향후 라벨 명명에 활용 가능

  const anyBroken = supLines.some(t => t.broken)

  // 현재가 라벨 동적 색: 추세선 접근 시 방향에 따라 점차 물듦 (상승=녹색, 하락=적색)
  const blendHex = (a: string, b: string, k: number) => {
    const pa = [1, 3, 5].map(i => parseInt(a.slice(i, i + 2), 16))
    const pb = [1, 3, 5].map(i => parseInt(b.slice(i, i + 2), 16))
    return '#' + pa.map((v, i) => Math.round(v + (pb[i] - v) * k).toString(16).padStart(2, '0')).join('')
  }
  const rising = cur >= closes[Math.max(0, closes.length - 4)]
  const lineVals = [nearestSupVal, nearestResVal].filter((v): v is number => v != null && v > 0)
  const dMin = lineVals.length
    ? Math.min(...lineVals.map(v => Math.abs(cur - v) / cur))
    : 1
  const tint = Math.max(0, 1 - dMin / 0.03)
  let curColor = blendHex('#f1f5f9', rising ? '#34d399' : '#f87171', tint)
  if (anyBroken && !rising) curColor = '#f87171'

  const path = closes.map((c, i) => `${i === 0 ? 'M' : 'L'}${toX(i).toFixed(1)},${toY(c).toFixed(1)}`).join(' ')
  const area = `${path} L${curX},${H - PB} L${toX(0)},${H - PB} Z`

  // 존 사각형 좌표 사전 계산 (렌더 + 라벨 배치 공용)
  const zoneRects = zones.map((z: Dict) => ({
    yTop: Math.max(toY(Math.min(z.priceTo, hi)), PT),
    yBot: Math.min(toY(Math.max(z.priceFrom, lo)), H - PB),
    main: z.volumePct === biggest,
    pct: z.volumePct,
  })).filter(r => r.yBot > r.yTop)
  // 어려운 용어 대신 '지지/저항 + 가격'으로만 표현 (지지=구간 상단가, 저항=구간 하단가)
  const fvgRects = ([
    ...fvgBull.map((z: Dict): Dict => ({ ...z, color: '#34d399', kind: '지지', price: z.top })),
    ...fvgBear.map((z: Dict): Dict => ({ ...z, color: '#f87171', kind: '저항', price: z.bottom })),
  ] as Dict[]).map(z => ({
    yTop: Math.max(toY(Math.min(z.top, hi)), PT),
    yBot: Math.min(toY(Math.max(z.bottom, lo)), H - PB),
    color: z.color as string,
    name: `${z.kind} ${fmt(z.price)}`,
  })).filter(r => r.yBot > r.yTop)

  // ── 라벨 충돌 회피 엔진 ────────────────────────────────────────────────
  // 위치를 고정하지 않고 기준선의 우/상/하/좌 후보를 순서대로 시도해 빈 자리에 배치.
  type LabelSpec = {
    text: string; x: number; y: number; anchor: 'start' | 'end'
    fill: string; fs: number; weight?: number; opacity?: number
  }
  type Box = { x1: number; y1: number; x2: number; y2: number }
  const boxes: Box[] = []
  const labels: LabelSpec[] = []
  const textW = (t: string, fs: number) => {
    let w = 0
    for (const ch of t) w += /[가-힣]/.test(ch) ? fs : fs * 0.62
    return w
  }
  const collide = (b: Box) =>
    boxes.some(o => b.x1 < o.x2 && b.x2 > o.x1 && b.y1 < o.y2 && b.y2 > o.y1)
  const addLabel = (
    text: string, fs: number, fill: string,
    cands: Array<{ x: number; y: number; anchor: 'start' | 'end' }>,
    opts: { weight?: number; opacity?: number } = {},
  ) => {
    const w = textW(text, fs)
    for (const c of cands) {
      const x1 = c.anchor === 'start' ? c.x : c.x - w
      const box = { x1, x2: x1 + w, y1: c.y - fs, y2: c.y + 3 }
      if (box.x1 >= 2 && box.x2 <= W - 2 && box.y1 >= 2 && box.y2 <= H - 2 && !collide(box)) {
        boxes.push(box)
        labels.push({ text, fill, fs, ...c, ...opts })
        return c
      }
    }
    // 모든 후보가 충돌 — 첫 후보 강행 (박스는 등록해 이후 라벨이 피하게)
    const c = cands[0]
    const x1 = c.anchor === 'start' ? c.x : c.x - w
    boxes.push({ x1, x2: x1 + w, y1: c.y - fs, y2: c.y + 3 })
    labels.push({ text, fill, fs, ...c, ...opts })
    return c
  }

  // 장애물 선등록: 현재가 점 주변 + x축 날짜 행
  boxes.push({ x1: curX - 14, y1: curY - 14, x2: curX + 14, y2: curY + 14 })
  boxes.push({ x1: 0, y1: H - 18, x2: W, y2: H })

  // 모든 글씨 크기 통일 ('평균 목표' 기준)
  const FS = 14

  // 배치 우선순위: 현재가 → 평균 목표 → 손절 → 목표 사다리 → 회귀선 → 존
  // 현재가: 평균 목표와 같은 방식 — 오른쪽 끝 정렬 + 오늘 등락률 병기.
  // 점에서 라벨까지는 연결선을 길게 이어준다.
  const dayChg = closes.length >= 2 && closes[closes.length - 2] > 0
    ? (cur / closes[closes.length - 2] - 1) * 100
    : null
  const curText = `현재가 ${fmt(cur)}${dayChg != null ? ` (${dayChg >= 0 ? '+' : ''}${dayChg.toFixed(1)}%)` : ''}`
  const curPos = addLabel(curText, FS, curColor, [
    { x: W - PX, y: curY + 5, anchor: 'end' },
    { x: W - PX, y: curY - 14, anchor: 'end' },
    { x: W - PX, y: curY + 24, anchor: 'end' },
    { x: curX + 90, y: curY + 6, anchor: 'start' },
    { x: curX + 34, y: curY - 18, anchor: 'start' },
    { x: curX + 34, y: curY + 28, anchor: 'start' },
  ], { weight: 800 })
  const curLabelLeftX = curPos.anchor === 'end'
    ? curPos.x - textW(curText, FS) - 6
    : curPos.x - 5

  // 현재가 방향 신호 점멸: 추가 하락 우위 = 빨강 / 상승 우위 = 파랑 밑줄
  // 근거 = 유사 국면 빈도 확률(20일 상승지속 — 백엔드 6차원 k-NN 매칭)
  //       ± 구조 보정(추세 이탈 -8, 단기 방향 ±4)
  //       ± 선도달 우위 보정(목표 선도달% - 손절 선이탈% ≥ +15p → +3 / ≤ -15p → -3)
  //       ± 닷컴 대조 보정(1995~2002 미국 유사 국면 상승비율 ≥60% → +3 / ≤40% → -3,
  //         표본 15건 이상일 때만)
  let blink: 'up' | 'down' | null = null
  {
    const pr = p.probability ?? {}
    const upRaw = Number(pr.continueUpPct)
    if (Number.isFinite(upRaw)) {
      const edge = Number(pr.reachTargetPct) - Number(pr.hitStopPct)
      const edgeAdj = Number.isFinite(edge) ? (edge >= 15 ? 3 : edge <= -15 ? -3 : 0) : 0
      const dc = pr.dotcomAnalogs ?? {}
      const dcUp = Number(dc.continueUpPct)
      const dcAdj = Number.isFinite(dcUp) && Number(dc.sample) >= 15
        ? (dcUp >= 60 ? 3 : dcUp <= 40 ? -3 : 0) : 0
      const adj = upRaw + (rising ? 4 : -4) + (anyBroken ? -8 : 0) + edgeAdj + dcAdj  // anyBroken = 지지선 이탈
      if (adj >= 58) blink = 'up'
      else if (adj <= 42) blink = 'down'
    }
  }
  // 점멸 위치: 하락 우위 = 텍스트 밑 / 상승 우위 = 텍스트 위 / 횡보 = 없음
  const curUnderline = {
    x1: curPos.anchor === 'end' ? curPos.x - textW(curText, FS) : curPos.x,
    x2: curPos.anchor === 'end' ? curPos.x : curPos.x + textW(curText, FS),
    y: blink === 'up' ? curPos.y - FS - 4 : curPos.y + 4,
  }

  if (target) {
    const y = toY(target)
    addLabel(`평균 목표 ${fmt(target)} (+${p.targets?.avgTargetUpside}%)`, FS, '#34d399', [
      { x: W - PX, y: y - 7, anchor: 'end' },
      { x: W - PX, y: y + 18, anchor: 'end' },
      { x: PX + 4, y: y - 7, anchor: 'start' },
      { x: PX + 4, y: y + 18, anchor: 'start' },
    ], { weight: 800 })
  }
  // 손절 3단계: 단기 → 중기 → 절대 (오른쪽 정렬, 겹치면 선 위/아래 회피)
  for (const d of stopDefs) {
    const y = toY(d.price as number)
    addLabel(
      `${d.name} ${fmt(d.price)} (${(((d.price as number) / cur - 1) * 100).toFixed(1)}%)`,
      FS, d.name === '절대 손절' ? '#ef4444' : '#f87171', [
        { x: W - PX, y: y + 18, anchor: 'end' },
        { x: W - PX, y: y - 7, anchor: 'end' },
        { x: PX + 4, y: y + 18, anchor: 'start' },
        { x: PX + 4, y: y - 7, anchor: 'start' },
      ], { weight: d.weight })
  }

  // 목표 사다리 — 오른쪽 끝에 붙여 정렬 (선 위/아래로 회피)
  const ladderItems = indivTargets
    .map(t => ({ ...t, y: toY(t.price) }))
    .filter(t => t.y > PT + 8 && t.y < H - PB - 8)
    .sort((a, b) => a.y - b.y)
  for (const t of ladderItems) {
    addLabel(`${t.label} ${fmt(t.price)}`, FS, '#6ee7b7', [
      { x: W - PX, y: t.y - 6, anchor: 'end' },
      { x: W - PX, y: t.y + 17, anchor: 'end' },
      { x: W * 0.8 - 6, y: t.y + 5, anchor: 'end' },
      { x: W * 0.8 - 6, y: t.y - 9, anchor: 'end' },
    ], { opacity: 0.9 })
  }

  // 추세선은 이름 없이 색으로만 표현 — 상승=녹색, 하락=적색.
  // 지지·저항 명칭은 매물대(FVG·거래량 존) 라벨 전용.

  // 존 라벨: 세력 매집(거래량 집중) / 지지·저항(FVG) — 왼쪽 정렬, 쉬운 말
  for (const r of zoneRects) {
    if (!r.main) continue
    addLabel(`세력 매집 ${r.pct}%`, FS, '#94a3b8', [
      { x: PX + 4, y: r.yTop + 16, anchor: 'start' },
      { x: PX + 4, y: r.yBot - 5, anchor: 'start' },
      { x: W - PX - 4, y: r.yTop + 16, anchor: 'end' },
    ])
  }
  for (const r of fvgRects) {
    addLabel(r.name, FS, r.color, [
      { x: PX + 4, y: r.yBot - 5, anchor: 'start' },
      { x: PX + 4, y: r.yTop + 15, anchor: 'start' },
      { x: PX + 4, y: r.yTop - 5, anchor: 'start' },
      { x: PX + 4, y: r.yBot + 15, anchor: 'start' },
    ], { opacity: 0.9 })
  }

  // ── 시간축: 1개월 단위, 연도는 1월에만, 미래 구간까지 ──
  const monthTicks: Array<{ x: number; label: string; future?: boolean }> = []
  let lastMonth = ''
  dates.forEach((d, i) => {
    const m = String(d).slice(0, 6)
    if (m && m !== lastMonth) {
      lastMonth = m
      const mm = m.slice(4, 6)
      monthTicks.push({ x: toX(i), label: mm === '01' ? `${m.slice(2, 4)}.01` : mm })
    }
  })
  // 미래 구간: 마지막 날짜 이후 월 ~21거래일 간격으로 이어서 표시
  if (dates.length) {
    const lastD = String(dates[dates.length - 1])
    let fy = parseInt(lastD.slice(0, 4), 10)
    let fm = parseInt(lastD.slice(4, 6), 10)
    let fi = closes.length - 1
    for (let k = 0; k < 8; k++) {
      fm += 1
      if (fm > 12) { fm = 1; fy += 1 }
      fi += 21
      const x = toX(fi)
      if (x > W - 16) break
      monthTicks.push({
        x,
        label: fm === 1 ? `${String(fy).slice(2)}.01` : String(fm).padStart(2, '0'),
        future: true,
      })
    }
  }

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', display: 'block' }}>
      <defs>
        <linearGradient id="cr-area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#60a5fa" stopOpacity="0.26" />
          <stop offset="100%" stopColor="#60a5fa" stopOpacity="0.02" />
        </linearGradient>

        {/* 깨진 선 gradient —
            상승선: 관통점부터 붉게 잠식 (하방 전환 위험)
            하락선: 주가가 위로 돌아선 지지 확인 — 현재가 오른쪽으로 선이 점차 사라짐
                    (녹색으로 바뀌는 게 아니라 투명 소멸 = "앞으로 하락은 없다") */}
        {[
          ...supLines.map((t, i) => ({ t, id: `bo-sup-${i}` })),
          ...resLines.map((t, i) => ({ t, id: `bo-res-${i}` })),
        ].map(({ t, id }) => {
          if (!t.broken || t.fadeBar == null) return null
          // 상승선은 깨져도 전 구간 녹색 유지 — gradient 없음.
          // (접점 경고는 터치 물듦, 소멸은 lifecycle이 담당)
          if (t.rising) return null
          // 하락선: 현재가 x좌표부터 우측 투명 페이드
          const fc = Math.max(0.06, Math.min(0.94, (curX - t.x1) / Math.max(t.x2 - t.x1, 1)))
          return (
            <linearGradient key={id} id={id} gradientUnits="userSpaceOnUse"
              x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2}>
              <stop offset="0%" stopColor="#f87171" stopOpacity="0.85" />
              <stop offset={`${(fc * 100).toFixed(1)}%`} stopColor="#f87171" stopOpacity="0.7" />
              <stop offset="100%" stopColor="#f87171" stopOpacity="0.02" />
            </linearGradient>
          )
        })}

        {/* 접촉 물듦 gradient — 현재가가 실제로 닿아있는 접점 부근만 반대 색으로 살짝.
            우상향 선은 그 외 전 구간 녹색, 우하향 선은 전 구간 적색. */}
        {allTrendLines.map((t, gi) => {
          const tint = touchTint[gi]
          if (!tint || t.broken) return null
          const own = t.rising ? '#34d399' : '#f87171'
          const fc = Math.max(0.06, Math.min(0.94, (curX - t.x1) / Math.max(t.x2 - t.x1, 1)))
          const w = 0.06  // 접점 반경 (선 길이 대비)
          return (
            <linearGradient key={`touch-${gi}`} id={`touch-${gi}`} gradientUnits="userSpaceOnUse"
              x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2}>
              <stop offset="0%" stopColor={own} stopOpacity="0.9" />
              <stop offset={`${((fc - w) * 100).toFixed(1)}%`} stopColor={own} stopOpacity="0.9" />
              <stop offset={`${(fc * 100).toFixed(1)}%`} stopColor={tint} stopOpacity="0.8" />
              <stop offset={`${((fc + w) * 100).toFixed(1)}%`} stopColor={own} stopOpacity="0.9" />
              <stop offset="100%" stopColor={own} stopOpacity="0.9" />
            </linearGradient>
          )
        })}
      </defs>

      {/* 매물대 밴드 */}
      {zoneRects.map((r, i) => (
        <rect key={`z-${i}`} x={PX} y={r.yTop} width={W - PX * 2} height={r.yBot - r.yTop}
          fill="#94a3b8" fillOpacity={r.main ? 0.1 : 0.055} />
      ))}

      {/* ICT FVG 존 */}
      {fvgRects.map((r, i) => (
        <rect key={`f-${i}`} x={PX} y={r.yTop} width={W - PX * 2} height={r.yBot - r.yTop}
          fill={r.color} fillOpacity="0.09"
          stroke={r.color} strokeOpacity="0.35" strokeWidth="0.7" strokeDasharray="3,3" />
      ))}

      {/* 퀀트 추세선 — 지지(녹) / 저항(적), 채널(점선), 강도별 굵기 */}
      {/* 수렴 구간에서는 gradient로 색 전이 (지지선 끝 붉게, 저항선 끝 녹색) */}
      {allTrendLines.map((t, gi) => {
        const lineIdx = t.isSup
          ? supLines.findIndex(s => s === t)
          : resLines.findIndex(r => r === t)
        const cg = t.isSup ? supGradMap[lineIdx] : resGradMap[lineIdx]
        // 깨진 하락선만 gradient(현재가 우측 투명 소멸). 상승선은 깨져도 전 구간 녹색.
        // 그 외에는 현재가 접촉 물듦만 — 미래 교차점은 물들지 않음 (펄스가 담당)
        const breakGradId = t.broken && !t.rising ? `bo-${t.isSup ? 'sup' : 'res'}-${lineIdx}` : null
        const touchGradId = touchTint[gi] ? `touch-${gi}` : null
        const gradId = breakGradId ?? touchGradId

        const baseCol = t.rising ? '#34d399' : '#f87171'  // 기울기 기준: 상승=녹 / 하락=적
        const col = gradId ? `url(#${gradId})` : baseCol
        const chanCol = baseCol
        const opacity = Math.max(0.35, 0.85 - t.rank * 0.2)
        const width = Math.max(1, 3 - t.rank) * (t.strength === '강' ? 1.2 : 1)
        const dash = t.strength === '약' ? '4,4' : ''
        return (
          <g key={`tl-${t.isSup ? 's' : 'r'}${t.rank}`}>
            {/* 채널 (1위 선만) */}
            {t.rank === 0 && (
              <line x1={t.cx1} y1={t.cy1} x2={t.cx2} y2={t.cy2}
                stroke={chanCol} strokeWidth="1" strokeOpacity={opacity * 0.45}
                strokeDasharray="5,5" strokeLinecap="round" />
            )}
            {/* 메인 추세선 */}
            <line x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2}
              stroke={col} strokeWidth={width} strokeOpacity={opacity}
              strokeDasharray={dash} strokeLinecap="round" />
            {/* 수렴 구간 강조: apex 근처에 반짝이는 원 */}
            {cg && t.rank === 0 && (() => {
              const ap = cg.proximity
              if (ap < 0.3) return null
              const apexX = toX(Math.min(cg.ixBar, extIdx))
              const mLine = (t.p2 - t.p1) / Math.max(t.i2 - t.i1, 1)
              const bLine = t.p1 - mLine * t.i1
              const apexPrice = mLine * Math.min(cg.ixBar, curIdx + 60) + bLine
              const apexY = toY(Math.min(Math.max(apexPrice, lo), hi))
              return (
                <circle cx={apexX} cy={apexY} r={5 * ap} fill="none"
                  stroke={t.isSup ? '#f87171' : '#34d399'}
                  strokeWidth="1.5" strokeOpacity={ap * 0.8}>
                  <animate attributeName="r" values={`${4 * ap};${9 * ap};${4 * ap}`}
                    dur="2s" repeatCount="indefinite" />
                  <animate attributeName="opacity" values="0.8;0.1;0.8"
                    dur="2s" repeatCount="indefinite" />
                </circle>
              )
            })()}
          </g>
        )
      })}

      {/* 평균 목표 / 손절 3단계 라인 */}
      {target && (
        <line x1={PX} y1={toY(target)} x2={W - PX} y2={toY(target)}
          stroke="#34d399" strokeWidth="1.6" strokeDasharray="5,4" />
      )}
      {stopDefs.map(d => (
        <line key={d.name} x1={PX} y1={toY(d.price as number)} x2={W - PX} y2={toY(d.price as number)}
          stroke={d.name === '절대 손절' ? '#ef4444' : '#f87171'}
          strokeWidth={d.name === '절대 손절' ? 1.8 : 1.3}
          strokeDasharray="5,4" />
      ))}

      {/* 목표 사다리 틱 */}
      {ladderItems.map(t => (
        <g key={t.label}>
          <line x1={W * 0.8} y1={t.y} x2={W - PX - 4} y2={t.y}
            stroke="#6ee7b7" strokeWidth="1" strokeOpacity="0.5" strokeDasharray="2,3" />
          <circle cx={W * 0.8} cy={t.y} r="2.2" fill="#6ee7b7" fillOpacity="0.8" />
        </g>
      ))}

      <path d={area} fill="url(#cr-area)" />

      <path d={path} fill="none" stroke="#60a5fa" strokeWidth="2.2" strokeLinejoin="round" />

      {/* 현재가 — 0.618 지점 펄스 + 라벨 연결선 */}
      <circle cx={curX} cy={curY} r="5" fill="#f1f5f9" opacity="0.5">
        <animate attributeName="r" values="5;13;5" dur="1.8s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0.5;0;0.5" dur="1.8s" repeatCount="indefinite" />
      </circle>
      <circle cx={curX} cy={curY} r="4.2" fill="#f1f5f9">
        <animate attributeName="opacity" values="1;0.55;1" dur="1.8s" repeatCount="indefinite" />
      </circle>
      {/* 현재가 점 → 라벨 연결선 (라벨이 멀리 가면 길게 이어짐) */}
      <line
        x1={curX + 8} y1={curY}
        x2={curLabelLeftX}
        y2={curPos.y - 6}
        stroke="rgba(241,245,249,0.45)" strokeWidth="1"
      />

      {/* 현재가 방향 신호 — 하락 우위: 빨강 점멸 / 상승 우위: 파랑 점멸 */}
      {blink && (
        <line
          x1={curUnderline.x1} y1={curUnderline.y}
          x2={curUnderline.x2} y2={curUnderline.y}
          stroke={blink === 'down' ? '#f87171' : '#60a5fa'} strokeWidth="2.2"
          strokeLinecap="round"
        >
          <animate attributeName="opacity" values="1;0.12;1" dur="1.1s" repeatCount="indefinite" />
        </line>
      )}

      {/* 모든 라벨 (충돌 회피 배치 결과 — 최상위 레이어) */}
      {labels.map((l, i) => (
        <text key={i} x={l.x} y={l.y} textAnchor={l.anchor} fontSize={l.fs}
          fill={l.fill} fontWeight={l.weight ?? 400} fillOpacity={l.opacity ?? 1}>
          {l.text}
        </text>
      ))}

      {/* x축: 1개월 단위 (연도는 1월에만 표시, 미래 구간 포함) */}
      {monthTicks.map((t, i) => (
        <g key={`m-${i}`}>
          <line x1={t.x} y1={H - PB} x2={t.x} y2={H - PB + 4}
            stroke="#475569" strokeWidth="1" />
          <text x={t.x} y={H - 6} fontSize={FS - 2} textAnchor="middle"
            fill={t.future ? '#3b4759' : '#64748b'}>
            {t.label}
          </text>
        </g>
      ))}
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
  const dims: Dict[] = Array.isArray(pr.dimensions) ? pr.dimensions : []
  const matched: string[] = Array.isArray(pr.matchedDates) ? pr.matchedDates : []
  const dc: Dict = pr.dotcomAnalogs ?? {}
  const dcOk = Number.isFinite(Number(dc.continueUpPct)) && Number(dc.sample) > 0
  const dcUpCount = dcOk ? Math.round(Number(dc.continueUpPct) / 100 * Number(dc.sample)) : 0
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
        {dims.length > 0 ? (
          <>
            {dims.length}개 차원({dims.map(d => d.name).join('·')})에서 지금과 가장 비슷한
            과거 국면 <b style={{ color: '#f1f5f9' }}>{pr.sample}건</b>
            {pr.totalCandidates ? ` (후보 ${pr.totalCandidates}건 중 최근접)` : ''}을 찾았습니다.
            그때마다 100번 중 —
          </>
        ) : (
          <>
            지금과 같은 추세 국면이 과거에 <b style={{ color: '#f1f5f9' }}>{pr.sample}번</b> 있었습니다.
            그때마다 100번 중 —
          </>
        )}
      </p>

      {/* 다차원 근거: 차원별 현재값 vs 유사 표본 평균 — 점멸 신호의 판단 근거 공개 */}
      {dims.length > 0 && (
        <div style={{
          display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'center',
          margin: '0 0 12px',
        }}>
          {dims.map(d => (
            <span key={d.name} title={d.desc} style={{
              fontSize: 11, padding: '3px 8px', borderRadius: 10,
              background: 'rgba(96,165,250,0.12)', border: '1px solid rgba(96,165,250,0.25)',
              color: 'rgba(241,245,249,0.8)',
            }}>
              {d.name} <b style={{ color: '#93c5fd' }}>{d.current}</b>
              <span style={{ color: '#64748b' }}> / 표본평균 {d.analogMean}</span>
            </span>
          ))}
        </div>
      )}

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

      {/* 닷컴(1995~2002 미국) 대조 — 한국 표본에 없는 과열·붕괴 국면과의 비교 */}
      {dcOk && (
        <div style={{
          marginTop: 14, padding: '10px 12px', borderRadius: 10,
          background: 'rgba(96,165,250,0.07)', border: '1px solid rgba(96,165,250,0.18)',
        }}>
          <p style={{ fontSize: 12.5, lineHeight: 1.65, color: 'rgba(241,245,249,0.85)', margin: 0 }}>
            🇺🇸 <b>닷컴 버블(1995~2002) 대조</b> — 미국 기술주·나스닥에서 지금과 가장
            비슷했던 국면 <b style={{ color: '#f1f5f9' }}>{dc.sample}건</b> 중{' '}
            <b style={{ color: dcUpCount * 2 >= Number(dc.sample) ? '#34d399' : '#f87171' }}>
              {dcUpCount}건
            </b>이 20일 후 상승 (수익률 중앙값 {Number(dc.medianFwd20Pct) >= 0 ? '+' : ''}{dc.medianFwd20Pct}%)
          </p>
          {dc.phaseDistribution && (
            <p style={{ fontSize: 11.5, color: 'rgba(241,245,249,0.6)', margin: '6px 0 0' }}>
              매칭 국면: {Object.entries(dc.phaseDistribution as Record<string, number>)
                .map(([k, v]) => `${k} ${v}건`).join(' · ')}
            </p>
          )}
          {Array.isArray(dc.topMatches) && dc.topMatches.length > 0 && (
            <p style={{ fontSize: 11, color: '#64748b', margin: '5px 0 0' }}>
              예: {dc.topMatches.slice(0, 3).map((m: Dict) =>
                `${m.symbol} ${m.date}(${m.phase})`).join(' · ')}
            </p>
          )}
        </div>
      )}

      <p style={{ fontSize: 11, color: '#64748b', textAlign: 'center', marginTop: 8 }}>
        {matched.length > 0 ? `가장 비슷했던 시점: ${matched.join(' · ')}` : ''}
      </p>
      <p style={{ fontSize: 11, color: '#64748b', textAlign: 'center', marginTop: 4 }}>
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
  const momentumSec = sections.find(s => s.title.includes('모멘텀'))
  const actionSec = sections.find(s => s.title.includes('투자 행동'))
  const scenarioSec = sections.find(s => s.title.includes('시나리오') || s.title.includes('불확실'))
  const restSecs = sections.filter(s =>
    s !== momentumSec && s !== actionSec && s !== scenarioSec && !s.title.includes('종목 평가'))

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
          { l: '손익비', v: comp.riskReward ?? 'N/A', s: `상승지속 ${data.probability?.continueUpPct ?? '-'}%`, c: '#60a5fa' },
          { l: '손절가', v: fmt(stopPrice), s: stopPrice && cur ? `${((stopPrice / cur - 1) * 100).toFixed(1)}%` : '', c: '#f87171' },
        ].map(x => (
          <div key={x.l} style={{ ...card, flex: 1, textAlign: 'center', marginBottom: 0, padding: '12px 8px' }}>
            <div style={{ fontSize: 10.5, color: '#64748b', letterSpacing: 1 }}>{x.l}</div>
            <div style={{ fontSize: 18, fontWeight: 800, color: x.c, marginTop: 3 }}>{x.v}</div>
            <div style={{ fontSize: 11, color: 'rgba(241,245,249,0.55)', marginTop: 1 }}>{x.s}</div>
          </div>
        ))}
      </div>

      {/* 손익비 쉬운 설명 — 잃을 1 대비 벌 수 있는 배수 */}
      {comp.riskReward != null && data.targets?.avgTargetUpside != null && stopPrice && cur && (
        <p style={{
          fontSize: 12, color: 'rgba(241,245,249,0.6)', lineHeight: 1.6,
          margin: '-4px 2px 12px', padding: '0 4px',
        }}>
          <b style={{ color: '#60a5fa' }}>손익비 {comp.riskReward}</b>이란?
          예측이 맞으면 <b style={{ color: '#34d399' }}>+{data.targets.avgTargetUpside}%</b> 벌고,
          틀리면 <b style={{ color: '#f87171' }}>{((stopPrice / cur - 1) * 100).toFixed(1)}%</b>에서 멈춥니다.
          잃을 수 있는 돈 1 대비 벌 수 있는 돈이 {comp.riskReward}배라는 뜻 —
          1보다 크면 틀릴 때보다 맞힐 때 더 크게 가져가는 유리한 구조입니다.
        </p>
      )}

      {/* ── 핵심 차트 ── */}
      {data.series?.closes?.length > 10 && (
        <div style={card}>
          <p style={sectionTitle}>핵심 차트 — 가격 vs 목표·손절 (일봉 120)</p>
          <PriceChart p={data} />
        </div>
      )}

      {/* ── 모멘텀 (보유 이유 — 사라지면 매도 전환) ── */}
      {momentumSec && (
        <div style={{ ...card, borderColor: 'rgba(251,191,36,0.35)' }}>
          <p style={sectionTitle}>🔥 모멘텀 — 보유 이유 <span style={{ letterSpacing: 0, color: '#92700c' }}>
            (소멸 시 매도 전환)</span></p>
          <Story text={momentumSec.body} />
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
