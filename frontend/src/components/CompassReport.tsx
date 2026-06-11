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

// ── 하락 추세선: 최근 고점 기준(anchor) 하향 저항선 ─────────────────────────
// 주가가 고점을 찍고 내려오는 국면에서만 생성. 고점에서 시작해 이후의 낮아지는
// 고점들을 가장 많이 스치는 선을 찾고, 접촉점이 없는 신선한 하락에서는
// 고점→현재가 직선을 가이드로 제공. 이 선을 딛고 오르는지/깨고 내려가는지가
// 실전 매매(손절)의 기준이다.
function fallingTrendline(closes: number[]) {
  const len = closes.length
  if (len < 10) return null
  // 최근 90봉 내 최고점
  const start = Math.max(0, len - 90)
  let peakIdx = start
  for (let i = start; i < len; i++) if (closes[i] > closes[peakIdx]) peakIdx = i
  const peak = closes[peakIdx]
  const cur = closes[len - 1]
  // 하락 국면 판정: 고점 이후 2봉 이상 경과 + 고점 대비 2% 이상 하락
  if (len - 1 - peakIdx < 2 || cur > peak * 0.98) return null

  // 고점 이후 로컬 고점들
  const cands: number[] = []
  for (let i = peakIdx + 1; i < len - 1; i++) {
    if (closes[i] >= closes[i - 1] && closes[i] >= closes[i + 1]) cands.push(i)
  }

  let best: { i1: number; at: (x: number) => number; score: number } | null = null
  for (const ib of cands) {
    const slope = (closes[ib] - peak) / (ib - peakIdx)
    if (slope >= 0) continue
    const at = (x: number) => peak + slope * (x - peakIdx)
    // 고점 이후 선 위로 2% 초과 돌파가 있으면 무효
    let ok = true
    for (let i = peakIdx; i < len; i++) {
      if (closes[i] > at(i) * 1.02) { ok = false; break }
    }
    if (!ok) continue
    let touches = 1 // 고점 자신
    for (const k of cands) {
      if (Math.abs(closes[k] - at(k)) / at(k) < 0.015) touches++
    }
    const score = touches * 100 + (ib - peakIdx)
    if (!best || score > best.score) best = { i1: peakIdx, at, score }
  }

  if (!best) {
    // 폴백: 접촉 고점이 아직 없는 신선한 하락 — 고점→현재가 직선
    const slope = (cur - peak) / (len - 1 - peakIdx)
    if (slope >= 0) return null
    best = { i1: peakIdx, at: (x: number) => peak + slope * (x - peakIdx), score: 0 }
  }
  return best
}

// ── 핵심 차트: 종가 120봉 + 목표/손절 + 자동 추세선 + 매물대 + MTF 추세 ──────
// 현재가는 가로 0.618 지점에서 반짝이고, 우측 38.2% 공간에 설명·가격 표시.
function PriceChart({ p }: { p: Dict }) {
  const closes: number[] = p.series?.closes ?? []
  const dates: string[] = p.series?.dates ?? []
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

  const lo = Math.min(...closes, ...stopDefs.map(d => d.price as number)) * 0.985
  const hi = Math.max(...closes, target ?? 0, ...indivTargets.map(t => t.price)) * 1.015
  const toX = (i: number) => PX + (i / (closes.length - 1)) * (plotEnd - PX)
  const toY = (v: number) => PT + ((hi - v) / (hi - lo)) * (H - PT - PB)
  const curX = toX(closes.length - 1)
  const curY = toY(cur)

  // 하락 추세선 (붉은색, 고점 다점 접촉) — 우측 미래 영역까지 연장.
  // 수평 저항·지지는 ICT 매물대(FVG·거래량 존)가 담당한다.
  const tlFalling = fallingTrendline(closes)
  const extIdx = (closes.length - 1) * (0.92 / GOLDEN) // x≈92% 지점까지 연장
  const trendSeg = (t: { i1: number; at: (x: number) => number } | null) => {
    if (!t) return null
    const slope = t.at(1) - t.at(0)
    // 왼쪽 연장: 과거 어디서 시작된 추세인지 — 차트 시작(0)까지, 경계 밖이면 교차점 절단
    let xs = 0
    let ys = t.at(0)
    if (ys < lo || ys > hi) {
      const bound = ys < lo ? lo : hi
      if (Math.abs(slope) < 1e-9) return null
      xs = (bound - t.at(0)) / slope
      ys = bound
    }
    // 오른쪽 연장: 목표치와 닿는 시계열이 보이도록 미래 영역까지
    let xe = extIdx
    let ye = t.at(xe)
    if (ye < lo || ye > hi) {
      const bound = ye < lo ? lo : hi
      if (Math.abs(slope) < 1e-9) return null
      xe = (bound - t.at(0)) / slope
      ye = bound
    }
    if (xe <= xs) return null
    const ix = (i: number) => PX + (i / (closes.length - 1)) * (plotEnd - PX)
    return {
      x1: ix(xs), y1: toY(ys),
      x2: ix(xe), y2: toY(ye),
      label: '하락 추세선', color: '#f87171',
    }
  }
  const fallSeg = trendSeg(tlFalling)
  const curIdxAll = closes.length - 1
  const fallValNow = tlFalling ? tlFalling.at(curIdxAll) : null

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

  // ── 맥선 (현재 상승 다리의 생명선) ──────────────────────────────────────
  // 상승의 시작 바닥(기점)과 이후 되돌림 바닥을 연결한 지지선 — 사용자 매매 기준.
  // 예: SK하이닉스 3/31 바닥 → 4/13 바닥 연결선. 피보나치의 기준이 되는 선.
  // 회귀선(평균 관통선)으로는 표현 불가 — 앵커드 스윙 지지선으로 구현.
  const backboneLine = (() => {
    const len = closes.length
    // 1) 상승 다리 기점: 전체 구간 최저점 (이후 충분히 상승했어야 다리로 인정)
    let o = 0
    for (let i = 0; i < len; i++) if (closes[i] < closes[o]) o = i
    if (len - 1 - o < 8) return null
    if (closes[len - 1] < closes[o] * 1.05) return null
    // 2) 기점 이후 되돌림 바닥들 (스윙 저점, n=3)
    const lows: number[] = []
    for (let i = Math.max(o + 3, 3); i < len - 3; i++) {
      const win = closes.slice(i - 3, i + 4)
      if (closes[i] === Math.min(...win)) lows.push(i)
    }
    if (!lows.length) return null
    // 3) 기점과 연결했을 때 위반(선 아래 2% 초과 이탈) 없이 접촉 바닥이 많은 선
    let best: { at: (x: number) => number; score: number } | null = null
    for (const ib of lows) {
      if (ib - o < 5) continue
      const slope = (closes[ib] - closes[o]) / (ib - o)
      if (slope <= 0) continue // 맥선은 우상향
      const at = (x: number) => closes[o] + slope * (x - o)
      let ok = true
      for (let i = o; i < len; i++) {
        if (closes[i] < at(i) * 0.98) { ok = false; break }
      }
      if (!ok) continue
      let touches = 1
      for (const k of lows) {
        if (Math.abs(closes[k] - at(k)) / at(k) < 0.015) touches++
      }
      const score = touches * 100 + (ib - o)
      if (!best || score > best.score) best = { at, score }
    }
    return best
  })()

  // ── 추세선 3종 ──────────────────────────────────────────────────────────
  // 장기 = 전체 120봉 회귀 / 중기 = 맥선 (없으면 60봉 회귀 폴백) / 단기 = 20봉 회귀
  const regress = (win: number) => {
    const seg = closes.slice(-win)
    const n = seg.length
    if (n < Math.max(4, win * 0.6)) return null
    const x0 = closes.length - n
    let sx = 0, sy = 0, sxy = 0, sxx = 0
    seg.forEach((y, i) => { sx += i; sy += y; sxy += i * y; sxx += i * i })
    const slope = (n * sxy - sx * sy) / (n * sxx - sx * sx || 1)
    const icept = (sy - slope * sx) / n
    const avg = sy / n
    return { x0, n, at: (gi: number) => icept + slope * (gi - x0), pctPerBar: slope / (avg || 1) }
  }

  const curIdx = closes.length - 1
  const trendLines = [
    { label: '장기', win: closes.length, width: 2.4, dash: '', op: 0.6 },
    { label: '중기', win: 60, width: 1.8, dash: '7,4', op: 0.8 },
    { label: '단기', win: 20, width: 1.5, dash: '3,3', op: 0.95 },
  ].map(def => {
    // 중기 = 맥선 우선 (현재 상승 다리의 바닥 연결선), 없으면 회귀 폴백
    const isBackbone = def.label === '중기' && backboneLine != null
    let at: (gi: number) => number
    let pctPerBar: number
    if (isBackbone) {
      at = backboneLine!.at
      pctPerBar = (at(1) - at(0)) / (cur || 1)
    } else {
      const r = regress(def.win)
      if (!r) return null
      at = r.at
      pctPerBar = r.pctPerBar
    }
    const slopePer = at(1) - at(0)
    const flat = Math.abs(pctPerBar) < 0.0006
    let baseColor = flat ? '#eab308' : pctPerBar > 0 ? '#34d399' : '#f87171'

    // 좌측 과거 연장 (추세 기원) — 경계 밖이면 교차점 절단
    let iStart = 0
    let yStart = at(0)
    if (yStart < lo || yStart > hi) {
      const bound = yStart < lo ? lo : hi
      if (Math.abs(slopePer) < 1e-9) return null
      iStart = (bound - at(0)) / slopePer
      yStart = at(iStart)
    }
    // 우측 미래 연장 (목표와 닿는 시계열) — 경계 밖이면 교차점 절단
    let iEnd = extIdx
    let yEnd = at(iEnd)
    if (yEnd < lo || yEnd > hi) {
      const bound = yEnd < lo ? lo : hi
      if (Math.abs(slopePer) < 1e-9) return null
      iEnd = (bound - at(0)) / slopePer
      yEnd = at(iEnd)
    }
    if (iEnd <= iStart) return null
    const cl = (v: number) => Math.min(Math.max(v, lo), hi)

    // 깨짐/접근 판정 (실전 손절 기준)
    const valNow = at(curIdx)
    const broken = cur < valNow * 0.999
    const nearing = !broken && valNow > 0 && (cur - valNow) / cur < 0.02
    let suffix = ''
    if (broken) {
      baseColor = '#f87171'
      suffix = ' (깨짐)'
    }

    // 위험 구간 세그먼트 (접근 시 현재가 주변)
    let danger: { x1: number; y1: number; x2: number; y2: number } | null = null
    if (nearing) {
      const a = Math.max(iStart, curIdx - 12)
      const b = Math.min(iEnd, curIdx + 16)
      danger = {
        x1: toX(a), y1: toY(cl(at(a))),
        x2: toX(b), y2: toY(cl(at(b))),
      }
    }

    return {
      ...def, color: baseColor, suffix, broken, danger, valNow, isBackbone,
      x1: toX(iStart), y1: toY(cl(yStart)),
      x2: toX(iEnd), y2: toY(cl(yEnd)),
    }
  }).filter(Boolean) as Array<{
    label: string; width: number; dash: string; op: number
    color: string; suffix: string; broken: boolean; valNow: number; isBackbone: boolean
    danger: { x1: number; y1: number; x2: number; y2: number } | null
    x1: number; y1: number; x2: number; y2: number
  }>

  // 하락 추세선 표시 조건: 고점 대비 하락 국면(탐지 함수가 보장)이거나
  // 단기/중기/장기 중 하나라도 깨졌을 때
  const anyBroken = trendLines.some(t => t.broken)
  const showFall = fallSeg != null

  // 현재가 라벨 동적 색: 추세선 접근 시 방향에 따라 점차 물듦 (상승=녹색, 하락=적색)
  const blendHex = (a: string, b: string, k: number) => {
    const pa = [1, 3, 5].map(i => parseInt(a.slice(i, i + 2), 16))
    const pb = [1, 3, 5].map(i => parseInt(b.slice(i, i + 2), 16))
    return '#' + pa.map((v, i) => Math.round(v + (pb[i] - v) * k).toString(16).padStart(2, '0')).join('')
  }
  const rising = cur >= closes[Math.max(0, closes.length - 4)]
  const lineVals = [
    ...trendLines.map(t => t.valNow),
    ...(fallValNow != null ? [fallValNow] : []),
  ].filter(v => v > 0)
  const dMin = lineVals.length
    ? Math.min(...lineVals.map(v => Math.abs(cur - v) / cur))
    : 1
  const tint = Math.max(0, 1 - dMin / 0.03) // 3% 이내 접근부터 물들기 시작
  let curColor = blendHex('#f1f5f9', rising ? '#34d399' : '#f87171', tint)
  if (anyBroken && !rising) curColor = '#f87171' // 추세 깨고 하락 중 — 명확한 적색

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
  // 현재가: 빈 공간을 찾아 멀리 가도 됨 — 점에서 라벨까지 연결선을 길게 그린다.
  const curPos = addLabel(`현재가 ${fmt(cur)}원`, FS, curColor, [
    { x: curX + 34, y: curY + 6, anchor: 'start' },
    { x: curX + 90, y: curY + 6, anchor: 'start' },
    { x: curX + 34, y: curY - 18, anchor: 'start' },
    { x: curX + 90, y: curY - 18, anchor: 'start' },
    { x: curX + 34, y: curY + 28, anchor: 'start' },
    { x: curX + 90, y: curY + 28, anchor: 'start' },
    { x: curX - 34, y: curY - 18, anchor: 'end' },
  ], { weight: 800 })

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

  // 회전 라벨 헬퍼 — 선과 같은 기울기로 선 위에, 빈 공간을 찾아 배치
  const placeOnLine = (
    seg: { x1: number; y1: number; x2: number; y2: number } | null,
    text: string,
    tCands: number[] = [0.42, 0.3, 0.55, 0.18, 0.68],
    side: 'above' | 'below' = 'above',
  ): { x: number; y: number; deg: number } | null => {
    if (!seg) return null
    const dx = seg.x2 - seg.x1
    const dy = seg.y2 - seg.y1
    const deg = Math.atan2(dy, dx) * 180 / Math.PI
    const len = Math.hypot(dx, dy) || 1
    const sign = side === 'above' ? 1 : -1
    const offX = (dy / len) * 13 * sign
    const offY = (-dx / len) * 13 * sign
    for (const t of tCands) {
      const x = seg.x1 + dx * t + offX
      const y = seg.y1 + dy * t + offY
      const w = textW(text, FS)
      const box = { x1: x - w / 2, x2: x + w / 2, y1: y - FS, y2: y + 4 }
      if (box.x1 >= 2 && box.x2 <= W - 2 && box.y1 >= 2 && box.y2 <= H - 2 && !collide(box)) {
        boxes.push(box)
        return { x, y, deg }
      }
    }
    return { x: seg.x1 + dx * 0.42 + offX, y: seg.y1 + dy * 0.42 + offY, deg }
  }

  // 추세선 라벨 3종 — 선과 같은 기울기로 회전 배치 (깨짐/돌파 표기)
  // 중기는 선의 왼쪽 아래, 나머지는 선 위쪽
  const lineTexts = trendLines.map(t => {
    const text = t.isBackbone
      ? `중기 추세선·맥선${t.suffix}`
      : `${t.label} 추세선${t.suffix}`
    const isMid = t.label === '중기'
    return {
      line: t,
      text,
      pos: placeOnLine(
        t, text,
        isMid ? [0.12, 0.2, 0.3, 0.42] : [0.42, 0.3, 0.55, 0.18, 0.68],
        isMid ? 'below' : 'above',
      ),
    }
  })

  // 하락 추세선 라벨 — 선의 왼쪽 위 (고점 부근)
  const fallText = showFall
    ? placeOnLine(fallSeg, '하락 추세선', [0.1, 0.18, 0.28, 0.4])
    : null

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

      {/* 회귀 추세선 (장/중/단기) — 깨지면 선 전체 붉게, 접근 시 현재가 부근만 붉게 */}
      {trendLines.map(t => (
        <g key={t.label}>
          <line x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2}
            stroke={t.color} strokeWidth={t.width} strokeOpacity={t.op}
            strokeDasharray={t.dash} strokeLinecap="round" />
          {t.danger && (
            <line x1={t.danger.x1} y1={t.danger.y1} x2={t.danger.x2} y2={t.danger.y2}
              stroke="#f87171" strokeWidth={t.width + 1.4} strokeOpacity="0.9"
              strokeLinecap="round" />
          )}
        </g>
      ))}

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

      {/* 하락 추세선 — 단/중/장기 중 하나라도 깨졌을 때 표시 (손절 판단의 기준선) */}
      {showFall && fallSeg && (
        <line x1={fallSeg.x1} y1={fallSeg.y1} x2={fallSeg.x2} y2={fallSeg.y2}
          stroke={fallSeg.color} strokeWidth="1.7" strokeOpacity="0.85" />
      )}

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
        x2={curPos.anchor === 'start' ? curPos.x - 5 : curPos.x + 5}
        y2={curPos.y - 6}
        stroke="rgba(241,245,249,0.45)" strokeWidth="1"
      />

      {/* 추세선 라벨 3종 — 각 선과 같은 색·기울기로 선 위에 */}
      {lineTexts.map(lt => lt.pos && (
        <text
          key={lt.text}
          x={lt.pos.x} y={lt.pos.y}
          textAnchor="middle" fontSize={FS} fill={lt.line.color} fontWeight="700"
          transform={`rotate(${lt.pos.deg.toFixed(1)} ${lt.pos.x.toFixed(1)} ${lt.pos.y.toFixed(1)})`}
        >
          {lt.text}
        </text>
      ))}

      {/* '하락 추세선' — 붉은색, 선 위에 같은 기울기 */}
      {fallText && fallSeg && (
        <text
          x={fallText.x} y={fallText.y}
          textAnchor="middle" fontSize={FS} fill={fallSeg.color} fontWeight="700"
          transform={`rotate(${fallText.deg.toFixed(1)} ${fallText.x.toFixed(1)} ${fallText.y.toFixed(1)})`}
        >
          하락 추세선
        </text>
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
