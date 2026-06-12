/* AI 분석 — 관심종목 네트워크 그래프 (우주 배경 + 로고 노드 + 별 반짝임).
   Force Directed Graph: spring + repulsion + 충돌회피 + 점수 기반 중심 인력
   + 유기적 호흡 + 레이블 lag(텍스트 < 노드·선 이동속도). */

import { useCallback, useEffect, useRef, useState } from 'react'
import { publicFetch } from '../../lib/publicApi'
import { StockReportModal } from '../../components/StockReportModal'

type GNode = {
  code: string; name: string; sector: string
  cap: number; capNorm: number; score: number
  signal: string | null; hasReport: boolean; chg1d: number
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

// 등락률(%) → 색상: 밝은녹 → 진한녹 → 무채색 → 탁한 붉은색
function chgColor(chg: number): string {
  const c = Math.max(-10, Math.min(10, chg))
  if (c >= 0) {
    const t = c / 10
    return `rgb(${Math.round(21 + t * 53)},${Math.round(128 + t * 94)},${Math.round(61 + t * 67)})`
  }
  const t = (-c) / 10
  return `rgb(${Math.round(100 + t * 75)},${Math.round(116 - t * 36)},${Math.round(139 - t * 59)})`
}

// 로고 캐시: code → HTMLImageElement | null('failed') | undefined('not yet')
type LogoState = HTMLImageElement | null
const logoCache = new Map<string, LogoState | 'loading'>()

function getOrLoadLogo(code: string): LogoState {
  const cached = logoCache.get(code)
  if (cached === 'loading') return null
  if (cached !== undefined) return cached as LogoState
  logoCache.set(code, 'loading')
  const img = new Image()
  img.crossOrigin = 'anonymous'
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
  const alphaRef = useRef(0)           // 시작 0 → 첫 틱에서 0.28로 set
  const labelPosRef = useRef<Array<{ x: number; y: number }>>([])
  const timeRef = useRef(0)
  const starsRef = useRef<Star[]>([])

  const [q, setQ] = useState('')
  const [files, setFiles] = useState<string[]>([])
  const [reportTarget, setReportTarget] = useState<{ code: string; name: string } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dragRef = useRef<{ sx: number; sy: number; tx: number; ty: number } | null>(null)

  // ── 별 생성 (최초 1회) ──
  useEffect(() => {
    const arr: Star[] = []
    for (let i = 0; i < 220; i++) {
      arr.push({
        x: Math.random(),
        y: Math.random(),
        r: 0.25 + Math.random() * 1.1,
        base: 0.15 + Math.random() * 0.65,
        phase: Math.random() * Math.PI * 2,
        speed: 0.18 + Math.random() * 0.55,
      })
    }
    starsRef.current = arr
  }, [])

  // ── 그래프 로드 + 초기 배치 ──
  useEffect(() => {
    publicFetch<Graph>('/api/public/stock-graph').then(g => {
      const sectors = Array.from(new Set(g.nodes.map(n => n.sector)))
      const secAngle: Record<string, number> = {}
      sectors.forEach((s, i) => { secAngle[s] = (i / sectors.length) * Math.PI * 2 })
      g.nodes.forEach(n => {
        // 높은 점수 → 안쪽, 하락 종목 → 바깥
        const decay = n.chg1d < 0 ? 1 + (-n.chg1d / 10) * 0.45 : 1
        const base = (200 + Math.random() * 120) * (1.1 - n.score * 0.38) * decay
        const a = (secAngle[n.sector] ?? 0) + (Math.random() - 0.5) * 0.85
        n.x = Math.cos(a) * base
        n.y = Math.sin(a) * base
        n.vx = 0; n.vy = 0
      })
      labelPosRef.current = g.nodes.map(n => ({ x: n.x, y: n.y }))
      graphRef.current = g
      alphaRef.current = 0.28   // 낮게 시작 → 드라마틱한 몰려드는 효과 없음
    }).catch(() => { /* 조용히 */ })
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
        const ctx = cv.getContext('2d')!
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

        // ── 우주 배경 ──
        const bg = ctx.createRadialGradient(W / 2, H * 0.42, 0, W / 2, H * 0.42, Math.max(W, H) * 0.75)
        bg.addColorStop(0, '#0c1828')
        bg.addColorStop(0.55, '#060d18')
        bg.addColorStop(1, '#020508')
        ctx.fillStyle = bg
        ctx.fillRect(0, 0, W, H)

        // ── 별 (반짝임: 위치 고정, 밝기만 흔들림) ──
        const t = timeRef.current
        for (const s of starsRef.current) {
          const alpha = Math.max(0.05, Math.min(1, s.base + Math.sin(t * s.speed + s.phase) * 0.18))
          ctx.globalAlpha = alpha
          ctx.fillStyle = '#e8f0ff'
          ctx.beginPath()
          ctx.arc(s.x * W, s.y * H, s.r, 0, Math.PI * 2)
          ctx.fill()
        }
        ctx.globalAlpha = 1

        if (g) {
          const a = alphaRef.current
          if (a > 0.003) {
            const N = g.nodes.length

            // 반발 + 충돌 회피
            for (let i = 0; i < N; i++) {
              const ni = g.nodes[i]
              const ri = 4 + ni.capNorm * 9
              for (let j = i + 1; j < N; j++) {
                const nj = g.nodes[j]
                const rj = 4 + nj.capNorm * 9
                let dx = ni.x - nj.x, dy = ni.y - nj.y
                let d2 = dx * dx + dy * dy
                if (d2 < 0.1) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 0.1 }
                const d = Math.sqrt(d2)
                // 충돌 회피
                const minD = ri + rj + 18
                if (d < minD) {
                  const push = ((minD - d) / minD) * 0.6
                  ni.vx += (dx / d) * push; ni.vy += (dy / d) * push
                  nj.vx -= (dx / d) * push; nj.vy -= (dy / d) * push
                }
                if (d2 > 120000) continue
                // 일반 반발 (더 강하게)
                const capScale = Math.sqrt((1 - 0.38 * ni.capNorm) * (1 - 0.38 * nj.capNorm))
                const f = (3200 * capScale / d2) * a * 0.7
                ni.vx += (dx / d) * f; ni.vy += (dy / d) * f
                nj.vx -= (dx / d) * f; nj.vy -= (dy / d) * f
              }
            }

            // 스프링 (엣지) + 유기적 호흡
            for (const e of g.edges) {
              const na = g.nodes[e.a], nb = g.nodes[e.b]
              const dx = nb.x - na.x, dy = nb.y - na.y
              const d = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
              const breathPhase = (e.a * 1.618 + e.b * 0.927) % (Math.PI * 2)
              const L = 70 + (1 - e.w) * 180 + Math.sin(t * 0.35 + breathPhase) * 5
              const boost = na.sector === nb.sector ? (g.sectorBoost[na.sector] ?? 1) : 1
              const f = 0.007 * e.w * boost * (d - L) * a
              na.vx += (dx / d) * f; na.vy += (dy / d) * f
              nb.vx -= (dx / d) * f; nb.vy -= (dy / d) * f
            }

            // 중심 인력 (점수 높은 종목 강하게, 하락 종목 약하게)
            for (const n of g.nodes) {
              const scorePull = 0.0012 + n.score * 0.004
              const chgFactor = n.chg1d < 0 ? Math.max(0.2, 1 + n.chg1d / 12) : 1.0
              n.vx += -n.x * scorePull * chgFactor * a
              n.vy += -n.y * scorePull * chgFactor * a
              n.vx *= 0.82; n.vy *= 0.82
              n.x += n.vx; n.y += n.vy
            }
            alphaRef.current = Math.max(a * 0.9945, 0.003)
          }

          // 레이블 lag
          const lp = labelPosRef.current
          if (lp.length !== g.nodes.length) {
            labelPosRef.current = g.nodes.map(n => ({ x: n.x, y: n.y }))
          } else {
            for (let i = 0; i < g.nodes.length; i++) {
              lp[i].x += (g.nodes[i].x - lp[i].x) * 0.1
              lp[i].y += (g.nodes[i].y - lp[i].y) * 0.1
            }
          }

          // 카메라 보간
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

          // 엣지 (노드 실시간 위치)
          for (const e of g.edges) {
            const na = g.nodes[e.a], nb = g.nodes[e.b]
            const dim = hl && !(hl.has(e.a) && hl.has(e.b))
            ctx.strokeStyle = `rgba(148,163,184,${dim ? 0.025 : 0.04 + e.w * 0.12})`
            ctx.lineWidth = dim ? 0.4 : 0.4 + e.w * 0.8
            ctx.beginPath()
            ctx.moveTo(toSX(na.x), toSY(na.y))
            ctx.lineTo(toSX(nb.x), toSY(nb.y))
            ctx.stroke()
          }

          // 노드 (실시간) + 레이블 (lag 위치)
          const lp2 = labelPosRef.current
          g.nodes.forEach((n, i) => {
            const r = (4 + n.capNorm * 9) * Math.min(cam.scale, 1.8)
            const x = toSX(n.x), y = toSY(n.y)
            const color = chgColor(n.chg1d)
            const dim = hl && !hl.has(i)
            ctx.globalAlpha = dim ? 0.08 : 1

            // ── 로고 또는 폴백 ──
            const logo = getOrLoadLogo(n.code)
            if (logo && r >= 5) {
              ctx.save()
              ctx.beginPath()
              ctx.arc(x, y, r, 0, Math.PI * 2)
              ctx.clip()
              ctx.drawImage(logo, x - r, y - r, r * 2, r * 2)
              ctx.restore()
              // 등락률 색상 테두리
              ctx.strokeStyle = color
              ctx.lineWidth = i === hoverRef.current ? 2 : 1.2
              ctx.beginPath()
              ctx.arc(x, y, r, 0, Math.PI * 2)
              ctx.stroke()
            } else {
              // 폴백: 색상 원 + 첫 글자
              ctx.fillStyle = color
              ctx.beginPath()
              ctx.arc(x, y, r, 0, Math.PI * 2)
              ctx.fill()
              if (r >= 6) {
                ctx.fillStyle = 'rgba(5,8,15,0.82)'
                const fs = Math.max(7, r * 0.72)
                ctx.font = `bold ${fs}px sans-serif`
                ctx.textAlign = 'center'
                ctx.textBaseline = 'middle'
                ctx.fillText(n.name[0], x, y)
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

            // 레이블: lag 위치, 폰트 크기 ∝ 원 크기
            const lx = toSX(lp2[i]?.x ?? n.x)
            const ly = toSY(lp2[i]?.y ?? n.y)
            const labelR = (4 + n.capNorm * 9) * Math.min(cam.scale, 1.8)
            if ((labelR > 6 || i === hoverRef.current || (hl && hl.has(i))) && cam.scale > 0.45) {
              const fs = Math.max(8, Math.min(14, labelR * 0.78))
              ctx.fillStyle = dim ? 'rgba(241,245,249,0.15)' : 'rgba(241,245,249,0.82)'
              ctx.font = `${fs}px sans-serif`
              ctx.textAlign = 'center'
              ctx.textBaseline = 'alphabetic'
              ctx.fillText(n.name, lx, ly + labelR + 10)
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
      const r = (5 + n.capNorm * 9) / Math.min(camRef.current.scale, 1.8) + 6
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

  // ── 타이핑 실시간 줌 (가장 높은 score 매칭 종목으로) ──
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

  // ── 검색 제출 ──
  const handleQuery = useCallback((raw: string) => {
    const g = graphRef.current
    const text = raw.trim(); if (!text || !g) return
    setQ(''); highlightRef.current = null
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
      if (top.n.hasReport) openReport(top.i)
      else zoomToNode(top.i)
      return
    }
    if (sectorHit) {
      const ids = new Set(
        g.nodes.map((n, i) => (n.sector === sectorHit ? i : -1)).filter(i => i >= 0))
      highlightRef.current = ids
      const xs = [...ids].map(i => g.nodes[i].x)
      const ys = [...ids].map(i => g.nodes[i].y)
      targetCamRef.current = {
        scale: 1.6,
        tx: -(xs.reduce((s, v) => s + v, 0) / xs.length),
        ty: -(ys.reduce((s, v) => s + v, 0) / ys.length),
      }
    }
  }, [openReport, zoomToNode])

  // ── 첨부 ──
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
          cam.scale = Math.min(Math.max(cam.scale * (e.deltaY < 0 ? 1.12 : 0.9), 0.3), 4.5)
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
          margin: 0, fontSize: 12, color: 'rgba(226,232,240,0.38)',
          fontWeight: 500, letterSpacing: '0.07em', pointerEvents: 'none',
        }}>
          준비되셨나요?
        </p>
        <div style={{
          pointerEvents: 'all', width: '100%',
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '6px 8px 6px 14px', borderRadius: 999,
          background: 'rgba(10,16,32,0.85)', border: '1px solid rgba(255,255,255,0.1)',
          boxShadow: '0 4px 28px rgba(0,0,0,0.6)', backdropFilter: 'blur(14px)',
        }}>
          <button
            type="button" onClick={() => fileInputRef.current?.click()}
            title="사진·보고서 첨부 (5MB 이하)"
            style={{ background: 'none', border: 'none', color: '#4b5e7a', fontSize: 22, cursor: 'pointer', lineHeight: 1, padding: '0 2px' }}
          >+</button>
          <input ref={fileInputRef} type="file" multiple
            accept=".png,.jpg,.jpeg,.webp,.gif,.pdf,.csv,.xlsx,.txt"
            style={{ display: 'none' }}
            onChange={e => { void onFiles(e.target.files); e.target.value = '' }}
          />
          <input
            value={q}
            onChange={e => { setQ(e.target.value); handleLiveSearch(e.target.value) }}
            onKeyDown={e => { if (e.key === 'Enter') handleQuery(q) }}
            placeholder="종목명 · 섹터 · 코드"
            style={{ flex: 1, background: 'none', border: 'none', outline: 'none', color: '#e2e8f0', fontSize: 15, padding: '10px 0' }}
          />
          {files.length > 0 && (
            <span style={{ fontSize: 11, color: '#3d4e63', flexShrink: 0 }}>📎{files.length}</span>
          )}
          <button
            type="button" onClick={() => handleQuery(q)}
            style={{ width: 36, height: 36, borderRadius: 999, border: 'none', cursor: 'pointer', background: '#d1dae8', color: '#0a1020', fontSize: 16, fontWeight: 800, flexShrink: 0 }}
          >↑</button>
        </div>
      </div>

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
