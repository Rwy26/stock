/* AI 분석 — 관심종목 네트워크 그래프 (우주 배경 + 로고 + 별 반짝임).
   Force Directed Graph: spring + repulsion + 충돌회피 + 경계 반발
   + 유기적 호흡 + 레이블 lag. 중심 인력 없음 → 전체 공간 활용. */

import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchPublicSnapshot } from '../../lib/publicApi'
import { StockReportModal } from '../../components/StockReportModal'

type GNode = {
  code: string; name: string; sector: string
  cap: number; capNorm: number; score: number
  signal: string | null; hasReport: boolean; chg1d: number
  aligned?: boolean; alignStr?: number; isEtf?: boolean; leader?: boolean; isNew?: boolean
  x: number; y: number; vx: number; vy: number
}
type GEdge = { a: number; b: number; w: number }
type Graph = {
  nodes: GNode[]; edges: GEdge[]
  sectorBoost: Record<string, number>
  climate: Record<string, number>
}
type Star = { x: number; y: number; r: number; base: number; phase: number; speed: number }

const KNOWN_SECTORS = [
  '반도체', 'AI 생태계', '로봇 AI', '2차전지', '바이오',
  '조선', '방산', '화학', '금융', '전력 인프라', '소비재', '기타',
]

// 등락률(%) → 틴트 색상 (로고 테두리 + glow용)
function chgColor(chg: number): string {
  const c = Math.max(-10, Math.min(10, chg))
  if (c >= 0) {
    const t = c / 10
    return `rgb(${Math.round(21 + t * 53)},${Math.round(128 + t * 94)},${Math.round(61 + t * 67)})`
  }
  const t = (-c) / 10
  return `rgb(${Math.round(100 + t * 75)},${Math.round(116 - t * 36)},${Math.round(139 - t * 59)})`
}

// 시총 → 반지름 (지수 0.95: 거의 선형 → 시총 격차가 크기로 직결)
function nodeRadius(capNorm: number): number {
  return 2.5 + Math.pow(capNorm, 0.95) * 31  // 범위 2.5px(소형) ~ 33.5px(대형)
}

// 종목명 표시 오버라이드 (길거나 어색한 이름 → 짧은 커스텀 레이블)
const DISPLAY_NAME: Record<string, string> = {
  'SK하이닉스': 'SK닉스',
  'KODEX 미국S&P500': 'S&P',
  'POSCO홀딩스': 'P홀',
  '포스코홀딩스': 'P홀',
  'LS마린솔루션': '마솔',
}
function displayName(name: string): string {
  return DISPLAY_NAME[name] ?? name
}

// 로고 없을 때 원 안 텍스트 결정
// - KODEX ETF: "KODEX 반도체" → "반도체", 공간 부족 시 첫 글자
// - 영문 종목: 앞 2자 대문자
// - 한글 종목: 첫 글자
function fallbackLabel(name: string, r: number): { text: string; fs: number } {
  const short = displayName(name)
  const baseFs = Math.max(7, r * 0.72)
  if (short.startsWith('KODEX ')) {
    const word = short.slice(6).split(/\s+/)[0]
    const fitFs = Math.min(baseFs, (r * 1.65) / (word.length * 0.62))
    return fitFs >= 6
      ? { text: word, fs: Math.max(6, fitFs) }
      : { text: word[0], fs: baseFs }
  }
  if (/^[A-Za-z]/.test(short)) {
    return { text: short.slice(0, 2).toUpperCase(), fs: Math.max(6, r * 0.62) }
  }
  // 오버라이드된 짧은 이름: 원에 들어가면 전체 표시
  const fitFs = Math.min(baseFs, (r * 1.65) / (short.length * 0.62))
  if (fitFs >= 6 && short.length > 1) return { text: short, fs: Math.max(6, fitFs) }
  return { text: short[0], fs: baseFs }
}

// CDN 오매핑 확인된 코드 — 폴백(첫 글자 원) 사용
const LOGO_SKIP = new Set([
  '060370', // LS마린솔루션 → CDN이 KT 로고 반환
])

// 로고 캐시 (crossOrigin 없음 → 외부 CDN 로드 가능, canvas는 display-only라 taint 무관)
type LogoEntry = HTMLImageElement | null | 'loading'
const logoCache = new Map<string, LogoEntry>()

function getOrLoadLogo(code: string): HTMLImageElement | null {
  if (LOGO_SKIP.has(code)) return null
  const cached = logoCache.get(code)
  if (cached === 'loading') return null
  if (cached !== undefined) return cached as HTMLImageElement | null
  logoCache.set(code, 'loading')
  const img = new Image()
  // crossOrigin 제거: CORS 헤더 없는 CDN도 drawImage로 표시 가능
  img.onload = () => logoCache.set(code, img)
  img.onerror = () => logoCache.set(code, null)
  img.src = `https://file.alphasquare.co.kr/media/images/stock_logo/kr/${code}.png`
  return null
}

export function PublicAiHistoryPage() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const graphRef = useRef<Graph | null>(null)
  const camRef = useRef({ scale: 1, tx: 0, ty: 0 })
  const targetCamRef = useRef<{ scale: number; tx: number; ty: number } | null>(null)
  const hoverRef = useRef<number>(-1)
  const highlightRef = useRef<Set<number> | null>(null)
  const alphaRef = useRef(0.0)
  const labelPosRef = useRef<Array<{ x: number; y: number }>>([])
  const timeRef = useRef(0)
  const starsRef = useRef<Star[]>([])
  // 물리 경계로 쓸 캔버스 크기 (렌더 루프에서 매 프레임 갱신)
  const cvSizeRef = useRef({ w: 900, h: 600 })

  const [q, setQ] = useState('')
  const [reply, setReply] = useState<string | null>(null)
  const [files, setFiles] = useState<string[]>([])
  const [reportTarget, setReportTarget] = useState<{ code: string; name: string } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dragRef = useRef<{ sx: number; sy: number; tx: number; ty: number } | null>(null)

  // ── 별 생성 ──
  useEffect(() => {
    const arr: Star[] = []
    for (let i = 0; i < 260; i++) {
      arr.push({
        x: Math.random(), y: Math.random(),
        r: 0.2 + Math.random() * 1.3,
        base: 0.12 + Math.random() * 0.6,
        phase: Math.random() * Math.PI * 2,
        speed: 0.15 + Math.random() * 0.5,
      })
    }
    starsRef.current = arr
  }, [])

  // ── 그래프 로드 + 초기 배치: 캔버스 전체 면적으로 흩뿌림 ──
  useEffect(() => {
    fetchPublicSnapshot<Graph>('public-stock-graph.json', '/api/public/stock-graph').then(g => {
      const sectors = Array.from(new Set(g.nodes.map(n => n.sector)))
      const secAngle: Record<string, number> = {}
      sectors.forEach((s, i) => { secAngle[s] = (i / sectors.length) * Math.PI * 2 })

      // 캔버스 크기를 기준으로 world 좌표계 결정
      const W = cvSizeRef.current.w, H = cvSizeRef.current.h
      const maxRx = W * 0.46, maxRy = H * 0.44

      g.nodes.forEach(n => {
        // 섹터별 방위각 + 랜덤 오프셋으로 고르게 퍼뜨림
        const a = (secAngle[n.sector] ?? 0) + (Math.random() - 0.5) * 1.1
        // 거리: 캔버스 전체 반경의 20% ~ 90% 사이 랜덤 배치
        const minR = 0.2, maxR = 0.88
        const t = minR + Math.random() * (maxR - minR)
        n.x = Math.cos(a) * maxRx * t
        n.y = Math.sin(a) * maxRy * t
        n.vx = 0; n.vy = 0
      })
      labelPosRef.current = g.nodes.map(n => ({ x: n.x, y: n.y }))
      graphRef.current = g
      alphaRef.current = 0.22   // 낮게 시작 → 조용한 안착
      // 그래프 도착 즉시 전체 로고 병렬 선로딩 (렌더 루프 첫 호출 전에 CDN 요청 시작)
      g.nodes.forEach(n => getOrLoadLogo(n.code))
    }).catch(() => { /* silent */ })
  }, [])

  // ── 물리 + 렌더 루프 ──
  useEffect(() => {
    let raf = 0
    const tick = () => {
      timeRef.current += 0.012
      const cv = canvasRef.current
      const g = graphRef.current
      if (cv) {
        const dpr = window.devicePixelRatio || 1
        const W = cv.clientWidth, H = cv.clientHeight
        if (cv.width !== W * dpr) { cv.width = W * dpr; cv.height = H * dpr }
        cvSizeRef.current = { w: W, h: H }
        const ctx = cv.getContext('2d')!
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

        // ── 우주 배경 그라데이션 ──
        const bg = ctx.createRadialGradient(W / 2, H * 0.45, 0, W / 2, H * 0.45, Math.max(W, H) * 0.78)
        bg.addColorStop(0, '#070f1a')
        bg.addColorStop(0.5, '#03080f')
        bg.addColorStop(1, '#010306')
        ctx.fillStyle = bg
        ctx.fillRect(0, 0, W, H)

        // ── 별 반짝임 (위치 고정, 밝기만 진동) ──
        const t = timeRef.current
        for (const s of starsRef.current) {
          const alpha = Math.max(0.04, Math.min(1, s.base + Math.sin(t * s.speed + s.phase) * 0.2))
          ctx.globalAlpha = alpha
          ctx.fillStyle = '#ddeeff'
          ctx.beginPath()
          ctx.arc(s.x * W, s.y * H, s.r, 0, Math.PI * 2)
          ctx.fill()
        }
        ctx.globalAlpha = 1

        if (g) {
          const a = alphaRef.current
          const bx = W * 0.46, by = H * 0.44  // 소프트 경계

          if (a > 0.003) {
            const N = g.nodes.length

            // ── 반발 + 충돌 회피 ──
            for (let i = 0; i < N; i++) {
              const ni = g.nodes[i]
              const ri = nodeRadius(ni.capNorm)
              for (let j = i + 1; j < N; j++) {
                const nj = g.nodes[j]
                const rj = nodeRadius(nj.capNorm)
                let dx = ni.x - nj.x, dy = ni.y - nj.y
                let d2 = dx * dx + dy * dy
                if (d2 < 0.1) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 0.1 }
                const d = Math.sqrt(d2)
                // 충돌 회피 (반지름 합 + 여유)
                const minD = ri + rj + 20
                if (d < minD) {
                  const push = ((minD - d) / minD) * 0.65
                  ni.vx += (dx / d) * push; ni.vy += (dy / d) * push
                  nj.vx -= (dx / d) * push; nj.vy -= (dy / d) * push
                }
                // 일반 반발: 멀리까지 작용
                if (d2 > 160000) continue
                const capScale = Math.sqrt((1 - 0.35 * ni.capNorm) * (1 - 0.35 * nj.capNorm))
                const f = (5500 * capScale / d2) * a * 0.7
                ni.vx += (dx / d) * f; ni.vy += (dy / d) * f
                nj.vx -= (dx / d) * f; nj.vy -= (dy / d) * f
              }
            }

            // ── 스프링 (유기적 호흡 + 질량 비대칭 힘 전달) ──
            // 가벼운 노드(밴더)가 무거운 노드(주도주) 쪽으로 더 많이 끌려감 —
            // 엣지 가중치 w가 인과 강도, 질량비가 힘 전달 방향을 결정
            for (const e of g.edges) {
              const na = g.nodes[e.a], nb = g.nodes[e.b]
              const dx = nb.x - na.x, dy = nb.y - na.y
              const d = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
              const breathPhase = (e.a * 1.618 + e.b * 0.927) % (Math.PI * 2)
              const L = 80 + (1 - e.w) * 200 + Math.sin(t * 0.35 + breathPhase) * 5
              // 같은 섹터 스프링 강화: 기후 boost × 고정 1.6배
              const boost = na.sector === nb.sector ? (g.sectorBoost[na.sector] ?? 1) * 1.6 : 1
              const f = 0.006 * e.w * boost * (d - L) * a
              const mA = 0.35 + na.capNorm * 1.8   // 질량 ∝ 시총
              const mB = 0.35 + nb.capNorm * 1.8
              na.vx += (dx / d) * f / mA; na.vy += (dy / d) * f / mA
              nb.vx -= (dx / d) * f / mB; nb.vy -= (dy / d) * f / mB
            }

            // ── 섹터 무게중심 인력: 엣지 없어도 같은 섹터끼리 모임 ──
            const cents = new Map<string, { x: number; y: number; n: number }>()
            for (const n of g.nodes) {
              if (n.sector === '기타' || n.sector === 'ETF') continue
              const c = cents.get(n.sector)
              if (c) { c.x += n.x; c.y += n.y; c.n++ }
              else cents.set(n.sector, { x: n.x, y: n.y, n: 1 })
            }
            for (const n of g.nodes) {
              const c = cents.get(n.sector)
              if (!c || c.n < 2) continue
              const cx = c.x / c.n, cy = c.y / c.n
              const dx = cx - n.x, dy = cy - n.y
              const d = Math.sqrt(dx * dx + dy * dy)
              if (d < 60) continue  // 이미 충분히 가까우면 무시 (과밀 방지)
              const f = 0.012 * (g.sectorBoost[n.sector] ?? 1) * a
              n.vx += (dx / d) * f * Math.min(d, 250)
              n.vy += (dy / d) * f * Math.min(d, 250)
            }

            // ── ETF → 구성종목 섹터의 중심으로 (엣지 가중치로 지배 섹터 판정) ──
            for (let i = 0; i < N; i++) {
              const n = g.nodes[i]
              if (!n.isEtf) continue
              const secW = new Map<string, number>()
              for (const e of g.edges) {
                const other = e.a === i ? g.nodes[e.b] : e.b === i ? g.nodes[e.a] : null
                if (!other || other.isEtf) continue
                if (!cents.has(other.sector)) continue
                secW.set(other.sector, (secW.get(other.sector) ?? 0) + e.w)
              }
              let domSec = ''; let domW = 0
              secW.forEach((w, s) => { if (w > domW) { domW = w; domSec = s } })
              const c = domSec ? cents.get(domSec) : undefined
              if (!c) continue
              const cx = c.x / c.n, cy = c.y / c.n
              const dx = cx - n.x, dy = cy - n.y
              const d = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
              if (d < 8) continue
              const f = 0.03 * a  // 섹터 인력보다 강하게 — 중심 점거
              n.vx += (dx / d) * f * Math.min(d, 300)
              n.vy += (dy / d) * f * Math.min(d, 300)
            }

            // ── 은하 회전: 느리게 표류하는 은하 중심 주위의 접선 흐름 ──
            const gcx = Math.sin(t * 0.045) * bx * 0.22
            const gcy = Math.cos(t * 0.032) * by * 0.22
            for (const n of g.nodes) {
              const dx = n.x - gcx, dy = n.y - gcy
              const d = Math.max(Math.sqrt(dx * dx + dy * dy), 30)
              // 접선 방향(반시계) — 거리에 비례하되 상한, 멀수록 느린 강체 아닌 나선 느낌
              const tang = 0.018 * Math.min(d, 380) / 380
              n.vx += (-dy / d) * tang
              n.vy += (dx / d) * tang
            }

            // ── 경계 반발 + 지속 미세 진동 ──
            g.nodes.forEach((n, i) => {
              const rx = Math.abs(n.x) / bx, ry = Math.abs(n.y) / by
              if (rx > 0.75) n.vx -= Math.sign(n.x) * (rx - 0.75) * 1.2 * a
              if (ry > 0.75) n.vy -= Math.sign(n.y) * (ry - 0.75) * 1.2 * a
              // 노드마다 위상 다른 sin 힘 → 완전히 멈추지 않고 살짝 흔들림
              const idlePhase = i * 2.399  // 황금각 간격
              n.vx += Math.sin(t * 0.28 + idlePhase) * 0.06
              n.vy += Math.cos(t * 0.21 + idlePhase * 1.4) * 0.06
              n.vx *= 0.82; n.vy *= 0.82
              n.x += n.vx; n.y += n.vy
            })
            // alpha 최솟값 0.018: 힘이 항상 살아있음
            alphaRef.current = Math.max(a * 0.9945, 0.018)
          }

          // ── 레이블 lag ──
          const lp = labelPosRef.current
          if (lp.length !== g.nodes.length) {
            labelPosRef.current = g.nodes.map(n => ({ x: n.x, y: n.y }))
          } else {
            for (let i = 0; i < g.nodes.length; i++) {
              lp[i].x += (g.nodes[i].x - lp[i].x) * 0.09
              lp[i].y += (g.nodes[i].y - lp[i].y) * 0.09
            }
          }

          // ── 카메라 보간 ──
          const cam = camRef.current
          const tgt = targetCamRef.current
          if (tgt) {
            cam.scale += (tgt.scale - cam.scale) * 0.055
            cam.tx += (tgt.tx - cam.tx) * 0.055
            cam.ty += (tgt.ty - cam.ty) * 0.055
            if (Math.abs(tgt.scale - cam.scale) < 0.004) targetCamRef.current = null
          }
          const toSX = (x: number) => W / 2 + (x + cam.tx) * cam.scale
          const toSY = (y: number) => H / 2 + (y + cam.ty) * cam.scale

          const hl = highlightRef.current

          // ── 엣지 ──
          for (let ei = 0; ei < g.edges.length; ei++) {
            const e = g.edges[ei]
            const na = g.nodes[e.a], nb = g.nodes[e.b]
            const dim = hl && !(hl.has(e.a) && hl.has(e.b))
            const ax = toSX(na.x), ay = toSY(na.y)
            const bx2 = toSX(nb.x), by2 = toSY(nb.y)
            // 주도주 → 밴더 빛 전달: 주도주 쪽이 밝게 빛나는 그라데이션 + 흐르는 광점
            const leaderEnd = !dim && (na.leader ? 'a' : nb.leader ? 'b' : null)
            if (leaderEnd) {
              const lx0 = leaderEnd === 'a' ? ax : bx2, ly0 = leaderEnd === 'a' ? ay : by2
              const vx0 = leaderEnd === 'a' ? bx2 : ax, vy0 = leaderEnd === 'a' ? by2 : ay
              const grad = ctx.createLinearGradient(lx0, ly0, vx0, vy0)
              const breathe = 0.65 + Math.sin(t * 0.9 + ei * 1.3) * 0.2
              grad.addColorStop(0, `rgba(134,239,172,${(0.5 * breathe + e.w * 0.25).toFixed(3)})`)
              grad.addColorStop(1, `rgba(148,163,184,${(0.08 + e.w * 0.12).toFixed(3)})`)
              ctx.strokeStyle = grad
              ctx.lineWidth = 1.0 + e.w * 1.6
              ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx2, by2); ctx.stroke()
              // 광점: 주도주에서 밴더 방향으로 흘러감 (가중치 높을수록 빠르게)
              const ph = ((t * (0.10 + e.w * 0.16) + ei * 0.37) % 1)
              const px = lx0 + (vx0 - lx0) * ph, py = ly0 + (vy0 - ly0) * ph
              ctx.fillStyle = `rgba(190,255,210,${(0.7 * (1 - ph * 0.6)).toFixed(3)})`
              ctx.beginPath(); ctx.arc(px, py, 1.6 + e.w * 1.2, 0, Math.PI * 2); ctx.fill()
            } else {
              ctx.strokeStyle = `rgba(148,163,184,${dim ? 0.03 : 0.12 + e.w * 0.25})`
              ctx.lineWidth = dim ? 0.4 : 0.7 + e.w * 1.2
              ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx2, by2); ctx.stroke()
            }
          }

          // ── 노드 (실시간) + 레이블 (lag) ──
          const lp2 = labelPosRef.current
          g.nodes.forEach((n, i) => {
            const r = nodeRadius(n.capNorm) * Math.min(cam.scale, 2.0)
            const x = toSX(n.x), y = toSY(n.y)
            const dim = hl && !hl.has(i)
            ctx.globalAlpha = dim ? 0.07 : 1

            const logo = getOrLoadLogo(n.code)
            const rising = n.chg1d > 0
            const fallRatio = n.chg1d < 0 ? Math.min((-n.chg1d) / 8, 1) : 0  // 0~1 하락 강도

            // ── 상승/정배열: glow 일렁임 ──
            // 정배열(aligned)이면 기본 글로우 강화, 강할수록(alignStr)
            // 녹색→청록→파랑으로 색이 일렁이는 오로라 느낌
            const aStr = n.aligned ? (n.alignStr ?? 0) : 0
            if ((rising || n.aligned) && !dim) {
              const glowBase = (n.aligned ? 9 : 5) + Math.min(Math.max(n.chg1d, 0) / 5, 1) * 14 + aStr * 10
              const glowAmp  = Math.min(Math.max(n.chg1d, 0) / 3, 1) * 14 + aStr * 8
              const glowPhase = i * 0.731  // 노드마다 다른 위상
              if (aStr > 0.15) {
                // 색 진동: hue 140(녹) ↔ 205(파랑) — 강도만큼 파랑 침투
                const hueT = (Math.sin(t * 1.1 + i * 0.83) + 1) / 2
                const hue = 140 + aStr * 65 * hueT
                ctx.shadowColor = `hsl(${hue.toFixed(0)} 90% ${(58 + aStr * 12).toFixed(0)}%)`
              } else {
                ctx.shadowColor = '#4ade80'
              }
              ctx.shadowBlur = Math.max(0, glowBase + Math.sin(t * 1.4 + glowPhase) * glowAmp)
            } else {
              ctx.shadowBlur = 0
            }

            // ── 하락: grayscale 필터 ──
            ctx.filter = fallRatio > 0 ? `grayscale(${Math.round(fallRatio * 90)}%)` : 'none'

            if (logo && r >= 5) {
              // 로고 원형 클립
              ctx.save()
              ctx.beginPath()
              ctx.arc(x, y, r, 0, Math.PI * 2)
              ctx.clip()
              ctx.drawImage(logo, x - r, y - r, r * 2, r * 2)
              ctx.restore()
              // 테두리: 상승=녹색, 하락=무채색
              ctx.filter = fallRatio > 0 ? `grayscale(${Math.round(fallRatio * 90)}%)` : 'none'
              ctx.strokeStyle = rising ? chgColor(n.chg1d) : `rgba(120,130,145,${0.6 - fallRatio * 0.3})`
              ctx.lineWidth = i === hoverRef.current ? 2.2 : 1.3
              ctx.beginPath()
              ctx.arc(x, y, r, 0, Math.PI * 2)
              ctx.stroke()
            } else {
              // 폴백: 색상 원 + 첫 글자
              ctx.fillStyle = chgColor(n.chg1d)
              ctx.beginPath()
              ctx.arc(x, y, r, 0, Math.PI * 2)
              ctx.fill()
              if (r >= 6) {
                ctx.shadowBlur = 0
                ctx.filter = 'none'
                const { text: fl, fs: ffs } = fallbackLabel(n.name, r)
                ctx.fillStyle = 'rgba(5,8,15,0.82)'
                ctx.font = `bold ${ffs}px sans-serif`
                ctx.textAlign = 'center'
                ctx.textBaseline = 'middle'
                ctx.fillText(fl, x, y)
                ctx.textBaseline = 'alphabetic'
              }
              if (i === hoverRef.current) {
                ctx.strokeStyle = '#f1f5f9'
                ctx.lineWidth = 1.5
                ctx.beginPath()
                ctx.arc(x, y, r, 0, Math.PI * 2)
                ctx.stroke()
              }
            }

            // 필터·그림자 리셋
            ctx.shadowBlur = 0
            ctx.filter = 'none'

            // ── '관종 신입' 뱃지 (편입 3일 이내) — 점멸하며 시선 유도 ──
            if (n.isNew && !dim && cam.scale > 0.3) {
              const pulse = 0.55 + Math.sin(t * 2.2 + i * 0.5) * 0.45
              const bx2 = x + r * 0.72, by2 = y - r * 0.72
              const txt = '신입'
              ctx.font = 'bold 9px sans-serif'
              const bw = ctx.measureText(txt).width + 8
              ctx.globalAlpha = pulse
              ctx.fillStyle = '#f59e0b'
              const rr = 6
              ctx.beginPath()
              ctx.roundRect(bx2 - bw / 2, by2 - rr, bw, rr * 2, rr)
              ctx.fill()
              ctx.fillStyle = '#1a1206'
              ctx.textAlign = 'center'
              ctx.textBaseline = 'middle'
              ctx.fillText(txt, bx2, by2 + 0.5)
              ctx.textBaseline = 'alphabetic'
              ctx.globalAlpha = 1
            }

            // ── 레이블 (lag 위치, 폰트 ∝ 원) ──
            const lx = toSX(lp2[i]?.x ?? n.x)
            const ly = toSY(lp2[i]?.y ?? n.y)
            if ((r > 6 || i === hoverRef.current || (hl && hl.has(i))) && cam.scale > 0.35) {
              const fs = Math.max(8, Math.min(16, r * 0.62))
              ctx.font = `${fs}px sans-serif`
              ctx.textAlign = 'center'
              ctx.textBaseline = 'alphabetic'
              const ty = ly + r + 10
              if (!dim) {
                // 검은 배경 박스 (시인성)
                const label = displayName(n.name)
                const tw = ctx.measureText(label).width
                const pad = 3
                ctx.fillStyle = 'rgba(2,5,14,0.72)'
                ctx.fillRect(lx - tw / 2 - pad, ty - fs - 1, tw + pad * 2, fs + 4)
                // 상승 강할수록 더 하얗게
                const brightness = dim ? 0.12 : Math.min(0.72 + Math.max(n.chg1d, 0) / 10 * 0.28, 1)
                ctx.fillStyle = `rgba(241,245,249,${brightness.toFixed(2)})`
              } else {
                ctx.fillStyle = 'rgba(241,245,249,0.12)'
              }
              ctx.fillText(displayName(n.name), lx, ty)
            }
            ctx.globalAlpha = 1
          })
        }
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])

  // ── 좌표 변환 ──
  const screenToWorld = (sx: number, sy: number) => {
    const cv = canvasRef.current!
    const cam = camRef.current
    return {
      x: (sx - cv.clientWidth / 2) / cam.scale - cam.tx,
      y: (sy - cv.clientHeight / 2) / cam.scale - cam.ty,
    }
  }
  const nodeAt = (sx: number, sy: number): number => {
    const g = graphRef.current; if (!g) return -1
    const p = screenToWorld(sx, sy)
    let best = -1, bd = 1e9
    g.nodes.forEach((n, i) => {
      const r = nodeRadius(n.capNorm) / Math.min(camRef.current.scale, 2.0) + 7
      const d = Math.hypot(n.x - p.x, n.y - p.y)
      if (d < r && d < bd) { best = i; bd = d }
    })
    return best
  }

  const zoomToNode = useCallback((i: number) => {
    const g = graphRef.current; if (!g) return
    const n = g.nodes[i]
    targetCamRef.current = { scale: 2.4, tx: -n.x, ty: -n.y }
  }, [])

  const openReport = useCallback((i: number) => {
    const g = graphRef.current; if (!g) return
    zoomToNode(i)
    const n = g.nodes[i]
    setTimeout(() => setReportTarget({ code: n.code, name: n.name }), 700)
  }, [zoomToNode])

  const handleLiveSearch = useCallback((text: string) => {
    const g = graphRef.current
    const t = text.trim()
    if (!t || !g) { highlightRef.current = null; return }
    const lower = t.toLowerCase()
    const hits = g.nodes
      .map((n, i) => ({ n, i }))
      .filter(({ n }) =>
        n.name.toLowerCase().includes(lower) || n.code.includes(t) ||
        lower.split(/\s+/).some(w => w.length >= 2 && n.name.toLowerCase().includes(w)))
    if (hits.length > 0) {
      hits.sort((a, b) => b.n.score - a.n.score)
      highlightRef.current = new Set(hits.map(h => h.i))
      const top = hits[0].n
      targetCamRef.current = { scale: 1.9, tx: -top.x, ty: -top.y }
    } else {
      highlightRef.current = null
    }
  }, [])

  // 리포트 없음 → 메시지 체인 + 백그라운드 분석 큐
  const queueAnalysis = useCallback((stockName: string, query: string) => {
    setReply(`${stockName}의 리포트를 찾고 있습니다`)
    setTimeout(() => setReply('곧 준비해 드리겠습니다'), 2200)
    setTimeout(() => setReply('준비된 뒤 말씀드리겠습니다'), 4600)
    setTimeout(() => setReply(null), 7500)
    fetch('/api/public/queue-analysis', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    }).catch(() => { /* silent */ })
  }, [])

  const handleQuery = useCallback((raw: string) => {
    const g = graphRef.current
    const text = raw.trim(); if (!text || !g) return
    setQ(''); highlightRef.current = null; setReply(null)
    const lower = text.toLowerCase()
    const nameHits = g.nodes
      .map((n, i) => ({ n, i }))
      .filter(({ n }) =>
        n.name.toLowerCase().includes(lower) || n.code.includes(text) ||
        lower.split(/\s+/).some(w => w.length >= 2 && n.name.toLowerCase().includes(w)))
    const sectorHit = KNOWN_SECTORS.find(s => text.includes(s))
    if (nameHits.length > 0) {
      nameHits.sort((a, b) => b.n.score - a.n.score)
      const top = nameHits[0]
      if (top.n.hasReport) {
        openReport(top.i)
      } else {
        zoomToNode(top.i)
        queueAnalysis(top.n.name, top.n.code)
      }
      return
    }
    if (sectorHit) {
      const ids = new Set(g.nodes.map((n, i) => (n.sector === sectorHit ? i : -1)).filter(i => i >= 0))
      highlightRef.current = ids
      const xs = [...ids].map(i => g.nodes[i].x), ys = [...ids].map(i => g.nodes[i].y)
      targetCamRef.current = {
        scale: 1.6,
        tx: -(xs.reduce((s, v) => s + v, 0) / xs.length),
        ty: -(ys.reduce((s, v) => s + v, 0) / ys.length),
      }
      return
    }
    // 그래프에 없는 종목 → 이름으로 분석 요청
    queueAnalysis(text, text)
  }, [openReport, zoomToNode, queueAnalysis])

  const onFiles = useCallback(async (list: FileList | null) => {
    if (!list?.length) return
    const names: string[] = []
    for (const f of Array.from(list).slice(0, 3)) {
      if (f.size > 5 * 1024 * 1024) continue
      const fd = new FormData()
      fd.append('file', f)
      try { await fetch('/api/public/upload', { method: 'POST', body: fd }); names.push(f.name) }
      catch { /* ignore */ }
    }
    if (names.length) setFiles(prev => [...prev, ...names])
  }, [])

  return (
    <div style={{
      position: 'relative', height: 'calc(100vh - 120px)', minHeight: 480,
      margin: '-8px 0', borderRadius: 14, overflow: 'hidden',
    }}>
      <canvas
        ref={canvasRef}
        style={{ width: '100%', height: '100%', display: 'block', cursor: 'grab' }}
        onWheel={e => {
          const cam = camRef.current
          cam.scale = Math.min(Math.max(cam.scale * (e.deltaY < 0 ? 1.12 : 0.9), 0.28), 5)
          targetCamRef.current = null
        }}
        onMouseDown={e => {
          dragRef.current = { sx: e.clientX, sy: e.clientY, tx: camRef.current.tx, ty: camRef.current.ty }
        }}
        onMouseMove={e => {
          const rect = canvasRef.current!.getBoundingClientRect()
          if (dragRef.current) {
            const cam = camRef.current
            cam.tx = dragRef.current.tx + (e.clientX - dragRef.current.sx) / cam.scale
            cam.ty = dragRef.current.ty + (e.clientY - dragRef.current.sy) / cam.scale
            targetCamRef.current = null
          } else {
            hoverRef.current = nodeAt(e.clientX - rect.left, e.clientY - rect.top)
          }
        }}
        onMouseUp={e => {
          const was = dragRef.current; dragRef.current = null
          if (was && Math.hypot(e.clientX - was.sx, e.clientY - was.sy) > 5) return
          const rect = canvasRef.current!.getBoundingClientRect()
          const i = nodeAt(e.clientX - rect.left, e.clientY - rect.top)
          if (i >= 0) openReport(i)
        }}
        onMouseLeave={() => { dragRef.current = null; hoverRef.current = -1 }}
      />

      {/* 상단 입력 영역 */}
      <div style={{
        position: 'absolute', top: 20, left: '50%', transform: 'translateX(-50%)',
        width: 'min(680px, 92%)',
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 7,
        pointerEvents: 'none',
      }}>
        <p style={{
          margin: 0, fontSize: 12, color: 'rgba(226,232,240,0.35)',
          fontWeight: 500, letterSpacing: '0.07em', pointerEvents: 'none',
        }}>준비되셨나요?</p>
        <div style={{
          pointerEvents: 'all', width: '100%',
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '6px 8px 6px 14px', borderRadius: 999,
          background: 'rgba(8,14,28,0.82)', border: '1px solid rgba(255,255,255,0.09)',
          boxShadow: '0 4px 28px rgba(0,0,0,0.65)', backdropFilter: 'blur(16px)',
        }}>
          <button type="button" onClick={() => fileInputRef.current?.click()}
            title="사진·보고서 첨부 (5MB 이하)"
            style={{ background: 'none', border: 'none', color: '#3d5068', fontSize: 22, cursor: 'pointer', lineHeight: 1, padding: '0 2px' }}>+</button>
          <input ref={fileInputRef} type="file" multiple
            accept=".png,.jpg,.jpeg,.webp,.gif,.pdf,.csv,.xlsx,.txt"
            style={{ display: 'none' }}
            onChange={e => { void onFiles(e.target.files); e.target.value = '' }} />
          <input value={q}
            onChange={e => { setQ(e.target.value); handleLiveSearch(e.target.value) }}
            onKeyDown={e => { if (e.key === 'Enter') handleQuery(q) }}
            placeholder="종목명 · 섹터 · 코드"
            style={{ flex: 1, background: 'none', border: 'none', outline: 'none', color: '#dde6f0', fontSize: 15, padding: '10px 0' }} />
          {files.length > 0 && (
            <span style={{ fontSize: 11, color: '#2d3e52', flexShrink: 0 }}>📎{files.length}</span>
          )}
          <button type="button" onClick={() => handleQuery(q)}
            style={{ width: 36, height: 36, borderRadius: 999, border: 'none', cursor: 'pointer', background: '#c8d4e4', color: '#08101e', fontSize: 16, fontWeight: 800, flexShrink: 0 }}>↑</button>
        </div>
      </div>

      {/* 응답 말풍선 */}
      {reply && (
        <div style={{
          position: 'absolute', top: 100, left: '50%', transform: 'translateX(-50%)',
          maxWidth: 420, padding: '10px 18px', borderRadius: 12,
          background: 'rgba(8,14,28,0.88)', border: '1px solid rgba(255,255,255,0.1)',
          color: 'rgba(226,232,240,0.9)', fontSize: 14, lineHeight: 1.6,
          textAlign: 'center', backdropFilter: 'blur(12px)',
          boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
          pointerEvents: 'none',
          animation: 'fadeIn 0.35s ease',
        }}>
          {reply}
        </div>
      )}

      {reportTarget && (
        <StockReportModal
          code={reportTarget.code}
          name={reportTarget.name}
          onClose={() => { setReportTarget(null); targetCamRef.current = { scale: 1, tx: 0, ty: 0 } }}
        />
      )}
    </div>
  )
}
