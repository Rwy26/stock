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

// ── 자동 추세선: 신뢰도 최대 지지선 탐색 ────────────────────────────────────
// 원칙: 많은 저점을 스치며 방향성을 가질수록 신뢰도가 높은 추세선이다.
// 스윙 저점 쌍을 전수 평가 — 접촉 저점 수(±1%)가 많고 기간이 길수록 고득점,
// 종가가 선 아래로 2% 이상 이탈한 봉이 많으면(8% 초과) 탈락.
function supportTrendline(closes: number[], n = 4) {
  const lows: number[] = []
  for (let i = n; i < closes.length - n; i++) {
    const win = closes.slice(i - n, i + n + 1)
    if (closes[i] === Math.min(...win)) lows.push(i)
  }
  if (lows.length < 2) return null

  let best: { i1: number; at: (x: number) => number; score: number } | null = null
  for (let a = 0; a < lows.length - 1; a++) {
    for (let b = a + 1; b < lows.length; b++) {
      const ia = lows[a], ib = lows[b]
      if (ib - ia < 10) continue // 너무 짧은 구간 제외
      const slope = (closes[ib] - closes[ia]) / (ib - ia)
      const at = (x: number) => closes[ia] + slope * (x - ia)
      // 유효성: 선 형성 이후 종가가 선을 크게 이탈하면 추세선 자격 없음
      let viol = 0
      for (let i = ia; i < closes.length; i++) {
        if (closes[i] < at(i) * 0.98) viol++
      }
      if (viol > (closes.length - ia) * 0.08) continue
      // 접촉 저점 수 (선에서 ±1% 이내)
      let touches = 0
      for (const k of lows) {
        if (k >= ia && Math.abs(closes[k] - at(k)) / at(k) < 0.01) touches++
      }
      if (touches < 2) continue
      const score = touches * 100 + (ib - ia)
      if (!best || score > best.score) best = { i1: ia, at, score }
    }
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
  const stop = (p.stops?.['기술적 손절']?.price ?? p.stops?.['구조 손절']?.price) as number | null

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

  const lo = Math.min(...closes, stop ?? Infinity) * 0.985
  const hi = Math.max(...closes, target ?? 0, ...indivTargets.map(t => t.price)) * 1.015
  const toX = (i: number) => PX + (i / (closes.length - 1)) * (plotEnd - PX)
  const toY = (v: number) => PT + ((hi - v) / (hi - lo)) * (H - PT - PB)
  const curX = toX(closes.length - 1)
  const curY = toY(cur)

  // 추세선 (다점 접촉 최고 신뢰 지지선, 1개) — 우측 미래 영역까지 연장.
  // 저항·지지는 선이 아니라 ICT 매물대(FVG·거래량 존)가 담당한다.
  const tlSupport = supportTrendline(closes)
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
    return {
      x1: toX(t.i1), y1: toY(y1v),
      x2: PX + (xe / (closes.length - 1)) * (plotEnd - PX), y2: toY(ye),
      label: '추세선', color: '#a78bfa',
    }
  }
  const supSeg = trendSeg(tlSupport)

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

  // MTF 추세 → 회귀 추세선 3개 (장기 120봉 / 중기 60봉 / 단기 20봉)
  // 기울기 방향으로 색: 상승 초록 / 하락 빨강 / 횡보 노랑 — 한눈에 읽히는 추세선
  const regress = (win: number) => {
    const seg = closes.slice(-win)
    const n = seg.length
    if (n < Math.max(10, win * 0.6)) return null
    const x0 = closes.length - n
    let sx = 0, sy = 0, sxy = 0, sxx = 0
    seg.forEach((y, i) => { sx += i; sy += y; sxy += i * y; sxx += i * i })
    const slope = (n * sxy - sx * sy) / (n * sxx - sx * sx || 1)
    const icept = (sy - slope * sx) / n
    const avg = sy / n
    const pctPerBar = slope / (avg || 1)
    return { x0, n, yAt: (i: number) => icept + slope * i, pctPerBar }
  }
  const trendLines = [
    { label: '장기', win: closes.length, width: 2.4, dash: '', op: 0.55 },
    { label: '중기', win: 60, width: 1.8, dash: '7,4', op: 0.75 },
    { label: '단기', win: 20, width: 1.5, dash: '3,3', op: 0.95 },
  ].map(def => {
    const r = regress(def.win)
    if (!r) return null
    const flat = Math.abs(r.pctPerBar) < 0.0006 // 봉당 ±0.06% 미만 = 횡보
    const color = flat ? '#eab308' : r.pctPerBar > 0 ? '#34d399' : '#f87171'
    const glyph = flat ? '→' : r.pctPerBar > 0 ? '↗' : '↘'
    const y1 = r.yAt(0)
    // 우측 미래 영역으로 연장 (시간 시계열 체감) — 경계 밖이면 교차점에서 절단
    const extN = Math.round((closes.length - 1) * 0.28)
    let iEnd = r.n - 1 + extN
    let yEnd = r.yAt(iEnd)
    if (yEnd < lo || yEnd > hi) {
      const bound = yEnd < lo ? lo : hi
      const slopePer = r.yAt(1) - r.yAt(0)
      if (Math.abs(slopePer) > 1e-9) {
        iEnd = Math.min(iEnd, Math.max(r.n - 1, (bound - r.yAt(0)) / slopePer))
        yEnd = r.yAt(iEnd)
      }
    }
    if ((y1 < lo && yEnd < lo) || (y1 > hi && yEnd > hi)) return null
    const cl = (v: number) => Math.min(Math.max(v, lo), hi)
    return {
      ...def, color, glyph,
      x1: toX(r.x0), y1: toY(cl(y1)),
      x2: toX(r.x0 + iEnd), y2: toY(cl(yEnd)),
    }
  }).filter(Boolean) as Array<{
    label: string; width: number; dash: string; op: number
    color: string; glyph: string; x1: number; y1: number; x2: number; y2: number
  }>

  const path = closes.map((c, i) => `${i === 0 ? 'M' : 'L'}${toX(i).toFixed(1)},${toY(c).toFixed(1)}`).join(' ')
  const area = `${path} L${curX},${H - PB} L${toX(0)},${H - PB} Z`
  const dlabel = (idx: number) => {
    const d = dates[idx] ?? ''
    return d.length === 8 ? `${d.slice(2, 4)}.${d.slice(4, 6)}` : d
  }

  // 존 사각형 좌표 사전 계산 (렌더 + 라벨 배치 공용)
  const zoneRects = zones.map((z: Dict) => ({
    yTop: Math.max(toY(Math.min(z.priceTo, hi)), PT),
    yBot: Math.min(toY(Math.max(z.priceFrom, lo)), H - PB),
    main: z.volumePct === biggest,
    pct: z.volumePct,
  })).filter(r => r.yBot > r.yTop)
  const fvgRects = ([
    ...fvgBull.map((z: Dict): Dict => ({ ...z, color: '#34d399', name: 'FVG 지지' })),
    ...fvgBear.map((z: Dict): Dict => ({ ...z, color: '#f87171', name: 'FVG 저항' })),
  ] as Dict[]).map(z => ({
    yTop: Math.max(toY(Math.min(z.top, hi)), PT),
    yBot: Math.min(toY(Math.max(z.bottom, lo)), H - PB),
    color: z.color as string,
    name: `${z.name}${z.ceTouched ? ' (절반 충전)' : ''}`,
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

  // 배치 우선순위: 현재가 → 평균 목표 → 손절 → 목표 사다리 → 회귀선 → 존
  // 현재가: 빈 공간을 찾아 멀리 가도 됨 — 점에서 라벨까지 연결선을 길게 그린다.
  const curPos = addLabel(`현재가 ${fmt(cur)}원`, 16, '#f1f5f9', [
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
    addLabel(`평균 목표 ${fmt(target)} (+${p.targets?.avgTargetUpside}%)`, 14, '#34d399', [
      { x: W - PX, y: y - 7, anchor: 'end' },
      { x: W - PX, y: y + 18, anchor: 'end' },
      { x: PX + 4, y: y - 7, anchor: 'start' },
      { x: PX + 4, y: y + 18, anchor: 'start' },
    ], { weight: 800 })
  }
  if (stop) {
    const y = toY(stop)
    addLabel(`손절 ${fmt(stop)} (${((stop / cur - 1) * 100).toFixed(1)}%)`, 14, '#f87171', [
      { x: W - PX, y: y + 18, anchor: 'end' },
      { x: W - PX, y: y - 7, anchor: 'end' },
      { x: PX + 4, y: y + 18, anchor: 'start' },
      { x: PX + 4, y: y - 7, anchor: 'start' },
    ], { weight: 700 })
  }

  // 목표 사다리 — 오른쪽 끝에 붙여 정렬 (선 위/아래로 회피)
  const ladderItems = indivTargets
    .map(t => ({ ...t, y: toY(t.price) }))
    .filter(t => t.y > PT + 8 && t.y < H - PB - 8)
    .sort((a, b) => a.y - b.y)
  for (const t of ladderItems) {
    addLabel(`${t.label} ${fmt(t.price)}`, 12, '#6ee7b7', [
      { x: W - PX, y: t.y - 6, anchor: 'end' },
      { x: W - PX, y: t.y + 16, anchor: 'end' },
      { x: W * 0.8 - 6, y: t.y + 4, anchor: 'end' },
      { x: W * 0.8 - 6, y: t.y - 9, anchor: 'end' },
    ], { opacity: 0.9 })
  }

  // 회귀 추세선 라벨 (장/중/단기) — 선과 같은 색, 선 끝의 우/상/하
  for (const t of trendLines) {
    addLabel(`${t.label}${t.glyph}`, 13, t.color, [
      { x: t.x2 + 6, y: t.y2 + 5, anchor: 'start' },
      { x: t.x2 + 6, y: t.y2 - 10, anchor: 'start' },
      { x: t.x2 + 6, y: t.y2 + 20, anchor: 'start' },
      { x: t.x2 - 5, y: t.y2 - 10, anchor: 'end' },
      { x: t.x1 - 6, y: t.y1 + 5, anchor: 'end' },
    ], { weight: 800 })
  }

  // 존 라벨 (매물대/FVG) — 좌측 안쪽 우선, 막히면 존 위/우측
  for (const r of zoneRects) {
    if (!r.main) continue
    addLabel(`매물대 ${r.pct}%`, 12, '#94a3b8', [
      { x: PX + 4, y: r.yTop + 14, anchor: 'start' },
      { x: PX + 4, y: r.yBot - 5, anchor: 'start' },
      { x: W - PX - 4, y: r.yTop + 14, anchor: 'end' },
    ])
  }
  for (const r of fvgRects) {
    addLabel(r.name, 11.5, r.color, [
      { x: PX + 4, y: r.yBot - 5, anchor: 'start' },
      { x: PX + 4, y: r.yTop + 13, anchor: 'start' },
      { x: PX + 4, y: r.yTop - 5, anchor: 'start' },
      { x: PX + 4, y: r.yBot + 13, anchor: 'start' },
    ], { opacity: 0.85 })
  }

  // '추세선' 글자 — 선과 같은 기울기로 선 위에 배치 (위치는 유동: 빈 공간 탐색)
  let trendlineText: { x: number; y: number; deg: number } | null = null
  if (supSeg) {
    const dx = supSeg.x2 - supSeg.x1
    const dy = supSeg.y2 - supSeg.y1
    const deg = Math.atan2(dy, dx) * 180 / Math.PI
    const len = Math.hypot(dx, dy) || 1
    // 선에 수직으로 12px 위 오프셋
    const offX = (dy / len) * 12
    const offY = (-dx / len) * 12
    for (const t of [0.42, 0.3, 0.55, 0.18, 0.68]) {
      const x = supSeg.x1 + dx * t + offX
      const y = supSeg.y1 + dy * t + offY
      const w = textW('추세선', 12.5)
      const box = { x1: x - w / 2, x2: x + w / 2, y1: y - 13, y2: y + 4 }
      if (box.x1 >= 2 && box.x2 <= W - 2 && box.y1 >= 2 && box.y2 <= H - 2 && !collide(box)) {
        boxes.push(box)
        trendlineText = { x, y, deg }
        break
      }
    }
    if (!trendlineText) {
      const x = supSeg.x1 + dx * 0.42 + offX
      const y = supSeg.y1 + dy * 0.42 + offY
      trendlineText = { x, y, deg }
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

      {/* 회귀 추세선 (장/중/단기) */}
      {trendLines.map(t => (
        <line key={t.label} x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2}
          stroke={t.color} strokeWidth={t.width} strokeOpacity={t.op}
          strokeDasharray={t.dash} strokeLinecap="round" />
      ))}

      {/* 평균 목표 / 손절 라인 */}
      {target && (
        <line x1={PX} y1={toY(target)} x2={W - PX} y2={toY(target)}
          stroke="#34d399" strokeWidth="1.6" strokeDasharray="5,4" />
      )}
      {stop && (
        <line x1={PX} y1={toY(stop)} x2={W - PX} y2={toY(stop)}
          stroke="#f87171" strokeWidth="1.4" strokeDasharray="5,4" />
      )}

      {/* 목표 사다리 틱 */}
      {ladderItems.map(t => (
        <g key={t.label}>
          <line x1={W * 0.8} y1={t.y} x2={W - PX - 4} y2={t.y}
            stroke="#6ee7b7" strokeWidth="1" strokeOpacity="0.5" strokeDasharray="2,3" />
          <circle cx={W * 0.8} cy={t.y} r="2.2" fill="#6ee7b7" fillOpacity="0.8" />
        </g>
      ))}

      <path d={area} fill="url(#cr-area)" />

      {/* 추세선 (스윙 저점 연결) */}
      {supSeg && (
        <line x1={supSeg.x1} y1={supSeg.y1} x2={supSeg.x2} y2={supSeg.y2}
          stroke={supSeg.color} strokeWidth="1.5" strokeOpacity="0.85" />
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

      {/* '추세선' — 선과 같은 색·같은 기울기로 선 위에 */}
      {trendlineText && supSeg && (
        <text
          x={trendlineText.x} y={trendlineText.y}
          textAnchor="middle" fontSize="12.5" fill={supSeg.color} fontWeight="700"
          transform={`rotate(${trendlineText.deg.toFixed(1)} ${trendlineText.x.toFixed(1)} ${trendlineText.y.toFixed(1)})`}
        >
          추세선
        </text>
      )}

      {/* 모든 라벨 (충돌 회피 배치 결과 — 최상위 레이어) */}
      {labels.map((l, i) => (
        <text key={i} x={l.x} y={l.y} textAnchor={l.anchor} fontSize={l.fs}
          fill={l.fill} fontWeight={l.weight ?? 400} fillOpacity={l.opacity ?? 1}>
          {l.text}
        </text>
      ))}

      {/* x축 날짜 */}
      <text x={PX} y={H - 7} fontSize="11" fill="#64748b">{dlabel(0)}</text>
      <text x={(PX + plotEnd) / 2} y={H - 7} fontSize="11" fill="#64748b" textAnchor="middle">
        {dlabel(Math.floor(closes.length / 2))}
      </text>
      <text x={plotEnd} y={H - 7} fontSize="11" fill="#64748b" textAnchor="middle">{dlabel(closes.length - 1)}</text>
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
