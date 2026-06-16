import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchJson } from '../lib/api'
import { publicFetch } from '../lib/publicApi'
import { StockReportModal } from '../components/StockReportModal'
import { CAUTION_BANNER_STYLE, type ExclusionInfo, type OkOrCaution } from '../lib/exclusion'
import { formatNumber, formatPercent } from '../lib/format'
import type { StockRow, SearchResponse } from '../lib/types'

// ── Types ────────────────────────────────────────────────────────────
type WatchItem = {
  name: string; code: string; price: number
  changeRate: number; score: number; sector: string; icon?: string
  marketCap?: number
  exclusion?: ExclusionInfo   // 거래 제외 종목이면 '투자 주의' 정보 동봉
  isLeader?: boolean          // 주도 섹터의 주도주 — 상위 배치·제외 면제
  isEtf?: boolean             // ETF/ETN — 주도주와 동일 레벨로 보호·상위 배치
  leaderSectorRank?: number | null
  leaderStockRank?: number | null
}
type WatchlistResponse = { items: WatchItem[]; quoteBasis?: string }
type TRect = { id: string; x: number; y: number; w: number; h: number }

const WATCHLIST_CACHE_KEY = 'moon-watchlist-cache-v1'

// ── Squarified Treemap ───────────────────────────────────────────────
function squarify(
  items: Array<{ id: string; value: number }>,
  x0: number, y0: number, w0: number, h0: number,
  gap = 0,
  preserveOrder = false,   // true면 입력 순서대로 배치 (면적은 그대로, 위치만 입력 순서)
): TRect[] {
  if (!items.length || w0 < 0.5 || h0 < 0.5) return []
  const total = items.reduce((s, i) => s + Math.max(i.value, 0.001), 0)
  const area = w0 * h0
  const ordered = preserveOrder ? [...items] : [...items].sort((a, b) => b.value - a.value)
  const sorted = ordered.map(i => ({ id: i.id, a: (Math.max(i.value, 0.001) / total) * area }))
  const out: TRect[] = []

  function worst(row: typeof sorted, side: number): number {
    const s = row.reduce((t, r) => t + r.a, 0)
    const mx = Math.max(...row.map(r => r.a))
    const mn = Math.min(...row.map(r => r.a))
    if (!mn || !side) return Infinity
    return Math.max((s * s) / (side * side * mn), (side * side * mx) / (s * s))
  }

  function place(nodes: typeof sorted, x: number, y: number, w: number, h: number) {
    if (!nodes.length || w < 0.5 || h < 0.5) return
    if (nodes.length === 1) { out.push({ id: nodes[0].id, x, y, w, h }); return }
    const hz = w >= h
    const side = hz ? h : w
    let row = [nodes[0]]; let i = 1
    while (i < nodes.length) {
      const c = [...row, nodes[i]]
      if (worst(c, side) <= worst(row, side)) { row = c; i++ } else break
    }
    const ra = row.reduce((t, r) => t + r.a, 0)
    const tk = ra / side
    if (hz) {
      let ty = y
      for (const r of row) { const rh = r.a / tk; out.push({ id: r.id, x, y: ty, w: tk, h: rh }); ty += rh }
      place(nodes.slice(i), x + tk, y, w - tk, h)
    } else {
      let tx = x
      for (const r of row) { const rw = r.a / tk; out.push({ id: r.id, x: tx, y, w: rw, h: tk }); tx += rw }
      place(nodes.slice(i), x, y + tk, w, h - tk)
    }
  }

  place(sorted, x0, y0, w0, h0)
  if (!gap) return out
  return out.map(r => ({ ...r, x: r.x + gap / 2, y: r.y + gap / 2, w: Math.max(r.w - gap, 0.5), h: Math.max(r.h - gap, 0.5) }))
}

// ── Return → Heat Color (TradingView-like diverging palette) ─────────
function changeColor(changeRate: number): string {
  const clamped = Math.max(-3, Math.min(3, changeRate))
  const absRate = Math.abs(clamped)
  const deadzone = 0.15
  if (absRate <= deadzone) return 'hsl(216, 20%, 16%)'

  const t = (absRate - deadzone) / (3 - deadzone)
  if (clamped > 0) {
    const sat = Math.round(28 + t * 20)
    const light = Math.round(16 + t * 14)
    return `hsl(141, ${sat}%, ${light}%)`
  }

  const sat = Math.round(30 + t * 18)
  const light = Math.round(16 + t * 15)
  return `hsl(2, ${sat}%, ${light}%)`
}

const STOCK_ABBR_OVERRIDES: Record<string, string> = {
  '삼성전자': '삼전',
  '현대자동차': '현차',
  'SK하이닉스': '하닉',
  'LG에너지솔루션': '엘엔솔',
  '포스코퓨처엠': '포퓨엠',
  '하나금융지주': '하나금융',
}

const SECTOR_ICONS: Record<string, string> = {
  '반도체': '💾',
  'MLCC·기판': '🧩',
  '로봇·AI': '🤖',
  '로봇 AI': '🤖',
  'AI 생태계': '🌐',
  '자동차·로봇': '🚗',
  '2차전지': '🔋',
  '바이오': '🧬',
  '금융': '🏦',
  '우주항공': '🛰',
  '전력기기': '⚡',
  '전력 인프라': '⚡',
  '방산': '🛡',
  '화학': '⚗',
  '소비재': '🛍',
  '조선': '🚢',
  '외국인 코스피': '🌍',
  '외국인 코스닥': '🌍',
  '기관 코스피': '🏛',
  '기관 코스닥': '🏛',
  'LG그룹주': '🟣',
  '인터넷': '🌐',
  '피지컬AI': '🤖',
}

const CORE_SUFFIXES = [
  '전자', '전기', '전선', '자동차', '모비스', '에너지', '화학', '금융', '증권',
  '보험', '생명', '제약', '바이오', '로보틱스', '로봇', '반도체', '미디어',
  '인터내셔널', '솔루션',
]

function splitTokens(label: string): string[] {
  return label
    .replace(/\(주\)|㈜|주식회사|유한회사/g, ' ')
    .split(/[\s·/\\|,()\-]+/)
    .map(t => t.trim())
    .filter(Boolean)
}

function isHangulToken(token: string): boolean {
  return /[가-힣]/.test(token)
}

function cutLoanword(token: string): string {
  const noSpace = token.replace(/\s+/g, '')
  if (noSpace.length <= 3) return noSpace
  return noSpace.slice(0, 3)
}

function shortenSingleHangulWord(token: string): string {
  for (const suffix of CORE_SUFFIXES) {
    if (token.endsWith(suffix) && token.length > suffix.length) {
      const head = token[0]
      return `${head}${suffix[0]}`
    }
  }

  if (token.length >= 5) return token.slice(0, 3)
  if (token.length === 4) return token.slice(0, 2)
  return token
}

function makeInitialism(tokens: string[], targetLen = 3): string {
  const initials = tokens.map(t => t[0]).join('')
  if (initials.length >= targetLen) return initials.slice(0, targetLen)

  const sorted = [...tokens].sort((a, b) => b.length - a.length)
  let out = initials
  for (const tok of sorted) {
    for (let i = 1; i < tok.length && out.length < targetLen; i++) {
      out += tok[i]
    }
    if (out.length >= targetLen) break
  }
  return out
}

function abbreviateKoreanName(name: string, max = 4): string {
  const raw = name.trim()
  if (!raw) return ''
  if (raw.length <= max) return raw
  if (STOCK_ABBR_OVERRIDES[raw]) return STOCK_ABBR_OVERRIDES[raw]

  const tokens = splitTokens(raw)
  if (!tokens.length) return raw.slice(0, max)

  // Rule 1: multi-word initialism with 3-syllable preference.
  if (tokens.length >= 2) {
    const core = tokens
      .map(t => {
        if (!isHangulToken(t)) return cutLoanword(t)
        return t
      })
      .filter(Boolean)
    const byInitial = makeInitialism(core, Math.min(3, max))
    if (byInitial.length >= 2) return byInitial.slice(0, max)
  }

  const merged = tokens.join('')

  // Rule 2/3: single-word core morpheme extraction with 2/3/4 rhythm.
  if (isHangulToken(merged)) {
    const short = shortenSingleHangulWord(merged)
    if (short.length >= 2) return short.slice(0, max)
    return merged.slice(0, Math.min(3, max))
  }

  // Rule 4: loanword truncation to Korean-friendly 2~3 syllables.
  return cutLoanword(merged).slice(0, max)
}

// 섹터 로테이션 점수 → 헤더 강조색 (강세 녹 → 유입 청 → 중립 황 → 약세 적)
function sectorHeatColor(score: number): string {
  if (score < 0) return 'rgba(255,255,255,0.5)'   // 점수 없음
  if (score >= 75) return '#34d399'
  if (score >= 55) return '#60a5fa'
  if (score >= 40) return '#fbbf24'
  return '#f87171'
}
function sectorHeatBg(score: number): string {
  if (score < 0) return 'rgba(10,15,24,0.84)'
  if (score >= 75) return 'rgba(16,80,65,0.86)'
  if (score >= 55) return 'rgba(12,68,124,0.86)'
  if (score >= 40) return 'rgba(99,72,11,0.84)'
  return 'rgba(80,30,30,0.84)'
}

// 섹터 추세 형태 판정 — 2구간(중기 모멘텀 → 당일)으로 궤적 모양 결정
type TrendShape = 'strongUp' | 'up' | 'upStall' | 'upDown' | 'downUp' | 'down' | 'strongDown' | 'flat' | 'none'
function computeTrendShape(rot: { mom: number; today: number } | undefined, avgChange: number): TrendShape {
  // 나침반 데이터 있으면 중기(mom)+당일(today) 2구간, 없으면 당일 평균 1구간
  if (!rot) {
    if (avgChange >= 1.5) return 'strongUp'
    if (avgChange >= 0.3) return 'up'
    if (avgChange <= -1.5) return 'strongDown'
    if (avgChange <= -0.3) return 'down'
    return 'flat'
  }
  const m = rot.mom, t = rot.today
  const mUp = m >= 0.3, mDn = m <= -0.3
  const tUp = t >= 0.3, tFlat = Math.abs(t) < 0.3, tDn = t <= -0.3
  if (mUp && tUp) return (m >= 3 && t >= 1) ? 'strongUp' : 'up'
  if (mUp && tFlat) return 'upStall'
  if (mUp && tDn) return 'upDown'
  if (mDn && tUp) return 'downUp'
  if (mDn && tDn) return (m <= -3 && t <= -1) ? 'strongDown' : 'down'
  if (mDn && tFlat) return 'down'
  return 'flat'
}

// 추세 궤적 글리프 (작은 SVG: 꺾은선 + 끝 화살표)
const TREND_DEF: Record<TrendShape, { pts: string; head: 'ur' | 'r' | 'dr'; ex: number; ey: number; color: string }> = {
  strongUp:   { pts: '2,12 21,2',        head: 'ur', ex: 21, ey: 2,  color: '#34d399' },
  up:         { pts: '2,10 21,4',        head: 'ur', ex: 21, ey: 4,  color: '#34d399' },
  upStall:    { pts: '2,10 11,4 21,4',   head: 'r',  ex: 21, ey: 4,  color: '#fbbf24' },
  upDown:     { pts: '2,10 11,3 21,10',  head: 'dr', ex: 21, ey: 10, color: '#fb923c' },
  downUp:     { pts: '2,4 11,11 21,5',   head: 'ur', ex: 21, ey: 5,  color: '#60a5fa' },
  down:       { pts: '2,4 21,10',        head: 'dr', ex: 21, ey: 10, color: '#f87171' },
  strongDown: { pts: '2,2 21,12',        head: 'dr', ex: 21, ey: 12, color: '#f87171' },
  flat:       { pts: '2,7 21,7',         head: 'r',  ex: 21, ey: 7,  color: 'rgba(255,255,255,0.55)' },
  none:       { pts: '', head: 'r', ex: 0, ey: 0, color: 'transparent' },
}
function TrendGlyph({ shape }: { shape: TrendShape }) {
  if (shape === 'none') return null
  const d = TREND_DEF[shape]
  const { ex, ey } = d
  // 화살촉 삼각형 (끝 방향별)
  const head =
    d.head === 'ur' ? `${ex},${ey} ${ex - 5.5},${ey + 1} ${ex - 1},${ey + 5.5}` :
    d.head === 'dr' ? `${ex},${ey} ${ex - 5.5},${ey - 1} ${ex - 1},${ey - 5.5}` :
    `${ex},${ey} ${ex - 5.5},${ey - 3} ${ex - 5.5},${ey + 3}`
  return (
    <svg width="24" height="14" viewBox="0 0 24 14" style={{ marginLeft: 4, flexShrink: 0, overflow: 'visible' }} aria-hidden="true">
      <polyline points={d.pts} fill="none" stroke={d.color} strokeWidth="1.7" strokeLinejoin="round" strokeLinecap="round" />
      <polygon points={head} fill={d.color} />
    </svg>
  )
}

function toKoreanSectorAbbr(sector: string): string {
  const s = (sector || '').trim()
  if (!s) return '기타'
  const map: Record<string, string> = {
    '반도체': '반도체',
    '로봇 AI': '로봇 AI',
    '로봇·AI수혜': '로봇·AI',
    'AI 생태계': 'AI 생태계',
    'AI 인프라': 'AI 인프라',
    '전력 인프라': '전력 인프라',
    '우주항공·태양광': '우주항공·태양광',
    '2차전지': '2차전지',
    '2차전지·ESS': '2차전지',
    '자동차·로봇': '자동차·로봇',
    'MLCC·반도체기판': 'MLCC·기판',
    '금융': '금융',
    '바이오': '바이오',
    '방산': '방산',
    '조선': '조선',
    '화학': '화학',
    '철강': '철강',
    '소비재': '소비재',
    '기타': '기타',
  }
  return map[s] ?? s
}

function stockIcon(item: WatchItem): string {
  if (item.icon && item.icon.trim()) return item.icon.trim()

  const name = (item.name || '').trim()
  if (name === 'NAVER') return '🌐'

  const sectorAbbr = toKoreanSectorAbbr(item.sector)
  if (sectorAbbr && SECTOR_ICONS[sectorAbbr]) return SECTOR_ICONS[sectorAbbr]

  if ((item.code || '').startsWith('0')) return '📈'
  return '⬤'
}

// ── Constants ────────────────────────────────────────────────────────
const SEC_GAP = 3   // gap between sector blocks
const STK_GAP = 1   // gap between stock tiles
const SEC_H   = 22  // sector label bar height

// 섹터별 대표 ETF 태그 (코드·이름 네이버 검증 완료 2026-06-10). 클릭 시 네이버 시세로 이동.
const SECTOR_ETFS: Record<string, { code: string; label: string }[]> = {
  '반도체':      [{ code: '471990', label: 'AI반도체핵심장비' }],
  '전력 인프라': [{ code: '487240', label: 'AI전력핵심설비' }, { code: '0098F0', label: '원자력SMR' }],
  '로봇 AI':     [{ code: '445290', label: '로봇액티브' }],
  '방산':        [{ code: '0080G0', label: '방산TOP10' }, { code: '0167Z0', label: '미국우주항공' }],
  '2차전지':     [{ code: '305720', label: '2차전지산업' }],
  '기타':        [{ code: '117700', label: '건설' }],
}
// 시장 전체 기준 ETF — 페이지 상단에 표시
const MARKET_ETF = { code: '069500', label: 'KODEX 200' }

function openNaverItem(code: string) {
  window.open(`https://finance.naver.com/item/main.naver?code=${code}`, '_blank', 'noreferrer')
}

// 면적 배분: 거듭제곱(점진) 압축 + 최소 면적 플로어(데드존).
//   w = FLOOR + (1-FLOOR) × (시총/전역최대시총)^ALPHA
// - 단조: 시총이 크면 반드시 더 큰 면적 (전역 최대 = 1.0 기준)
// - 점진: ALPHA<1 거듭제곱이 절대 격차(수천 배)를 점진적으로 좁힘 — 로그보다 차이가 또렷이 남는다
// - 데드존: 초소형은 FLOOR 면적으로 수렴, 그 이하로 내려가지 않음
const AREA_FLOOR = 0.18 // 최소 면적 비율 — 최대 종목 대비 약 5.6배 이내
const AREA_ALPHA = 0.38 // 거듭제곱 지수 — 낮추면 평준화, 높이면 시총 비례 강화

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(Math.max(n, lo), hi)
}

// 원시 규모값 = 시가총액. 시총이 없으면 점수 기반 의사값(단조)으로 폴백.
function rawCap(item: WatchItem): number {
  const cap = typeof item.marketCap === 'number' ? item.marketCap : 0
  return cap > 0 ? cap : Math.max(item.score, 1) * 1e10
}

function compress(value: number, all: number[]): number {
  const max = Math.max(...all)
  if (!(max > 0)) return AREA_FLOOR
  const share = clamp(value / max, 0, 1)
  return AREA_FLOOR + (1 - AREA_FLOOR) * Math.pow(share, AREA_ALPHA)
}

export function WatchlistPage({ publicMode = false }: { publicMode?: boolean } = {}) {
  const [data, setData]           = useState<WatchlistResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [busyCode, setBusyCode]   = useState<string | null>(null)
  const [q, setQ]                 = useState('')
  const [searchRows, setSearchRows] = useState<StockRow[]>([])
  const [searchCaution, setSearchCaution] = useState<string | null>(null)
  const [addBusyCode, setAddBusyCode] = useState<string | null>(null)
  const [showSearch, setShowSearch]   = useState(false)
  const [hovered, setHovered]     = useState<string | null>(null)
  const [cachedItems, setCachedItems] = useState<WatchItem[]>(() => {
    try {
      const raw = localStorage.getItem(WATCHLIST_CACHE_KEY)
      if (!raw) return []
      const parsed = JSON.parse(raw)
      if (!Array.isArray(parsed)) return []
      return parsed as WatchItem[]
    } catch {
      return []
    }
  })
  const containerRef              = useRef<HTMLDivElement>(null)
  const [dims, setDims]           = useState({ w: 900, h: 620 })
  const [etfQuotes, setEtfQuotes] = useState<Record<string, { price: number; changeRate: number }>>({})
  const [reportTarget, setReportTarget] = useState<{ code: string; name: string } | null>(null)
  // 섹터 로테이션: 섹터명 → {점수, 순위, 라이프사이클, 중기모멘텀%, 당일%} (나침반 연동)
  const [sectorRot, setSectorRot] = useState<Map<string, { score: number; rank: number; lifecycle: string; mom: number; today: number }>>(new Map())

  // ETF 태그 시세 (공개 엔드포인트, 서버측 60초 캐시)
  useEffect(() => {
    let dead = false
    const load = () => {
      fetch('/api/public/etf-quotes')
        .then(r => r.json())
        .then(d => { if (!dead) setEtfQuotes(d.items ?? {}) })
        .catch(() => {})
    }
    load()
    const t = setInterval(load, 60_000)
    return () => { dead = true; clearInterval(t) }
  }, [])

  // 섹터 로테이션 점수·순위 (나침반과 동일 소스, 장중 15분 캐시)
  useEffect(() => {
    let dead = false
    const load = () => {
      fetch('/api/public/sector-rotation')
        .then(r => r.json())
        .then((d: { sectors?: { sector: string; score: number; lifecycle?: string; detail?: { momentumPct?: number; intradayPct?: number } }[] }) => {
          if (dead) return
          const m = new Map<string, { score: number; rank: number; lifecycle: string; mom: number; today: number }>()
          ;(d.sectors ?? []).forEach((s, i) => {
            m.set(s.sector, {
              score: s.score, rank: i + 1, lifecycle: s.lifecycle ?? '',
              mom: s.detail?.momentumPct ?? 0, today: s.detail?.intradayPct ?? 0,
            })
          })
          setSectorRot(m)
        })
        .catch(() => {})
    }
    load()
    const t = setInterval(load, 5 * 60_000)
    return () => { dead = true; clearInterval(t) }
  }, [])

  const loadWatchlist = useCallback(
    (): Promise<WatchlistResponse> =>
      publicMode
        ? publicFetch<WatchlistResponse>('/api/public/watchlist')
        : fetchJson<WatchlistResponse>('/api/watchlist'),
    [publicMode],
  )

  const refresh = useCallback(() => {
    setIsLoading(true)
    loadWatchlist()
      .then(p => {
        setData(p)
        setCachedItems(p.items)
        try {
          localStorage.setItem(WATCHLIST_CACHE_KEY, JSON.stringify(p.items))
        } catch {
          // ignore storage write errors
        }
      })
      .catch(() => setData(null))
      .finally(() => setIsLoading(false))
  }, [])

  // Poll every 30 s
  useEffect(() => {
    let dead = false
    const load = () => {
      if (!dead) setIsLoading(true)
      loadWatchlist()
        .then(p => {
          if (dead) return
          setData(p)
          setCachedItems(p.items)
          try {
            localStorage.setItem(WATCHLIST_CACHE_KEY, JSON.stringify(p.items))
          } catch {
            // ignore storage write errors
          }
        })
        .catch(() => { if (!dead) setData(null) })
        .finally(() => { if (!dead) setIsLoading(false) })
    }
    load()
    const id = setInterval(load, 30_000)
    return () => { dead = true; clearInterval(id) }
  }, [])

  // Debounced search
  useEffect(() => {
    if (!q.trim()) { setSearchRows([]); setSearchCaution(null); return }
    const h = setTimeout(() => {
      fetchJson<SearchResponse>(
        `/api/stocks/search?q=${encodeURIComponent(q)}&market=ALL&sort=${encodeURIComponent('관련도')}`
      ).then(p => {
        setSearchRows(p.items.slice(0, 8))
        // 거래 제외 종목 문의 시 '투자 주의' 메시지 발행
        setSearchCaution(p.cautionMessage ?? null)
      }).catch(() => { setSearchRows([]); setSearchCaution(null) })
    }, 200)
    return () => clearTimeout(h)
  }, [q])

  // Measure container for treemap layout
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const update = () => setDims({ w: el.clientWidth, h: el.clientHeight })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const items     = useMemo(() => data?.items ?? cachedItems, [data, cachedItems])
  const showingCachedLayout = data === null && cachedItems.length > 0
  const itemCodes = useMemo(() => new Set(items.map(x => x.code)), [items])

  // Two-level squarified treemap: sectors → stocks
  const layout = useMemo(() => {
    if (!items.length || dims.w < 10 || dims.h < 10) return []

    const secMap = new Map<string, WatchItem[]>()
    for (const it of items) {
      const s = it.sector || '기타'
      if (!secMap.has(s)) secMap.set(s, [])
      secMap.get(s)!.push(it)
    }

    const secsRaw = Array.from(secMap.entries()).map(([sec, stocks]) => {
      const total = stocks.length || 1
      const avgChange = stocks.reduce((s, i) => s + i.changeRate, 0) / total
      const avgScore = stocks.reduce((s, i) => s + (i.score || 0), 0) / total
      const downRatio = stocks.filter(s => s.changeRate < 0).length / total
      const isEtc = sec.includes('기타')
      const isDownSector = isEtc || avgChange <= -0.4 || downRatio >= 0.65

      // Rank member stocks by raw market cap (largest first); ordering stays cap-based.
      const rankedStocks = [...stocks].sort((a, b) => rawCap(b) - rawCap(a))

      const sectorCap = stocks.reduce((s, i) => s + rawCap(i), 0)
      const momentum = 1 + clamp(avgChange, -3, 3) * 0.10 + (clamp(avgScore, 0, 100) / 100) * 0.20

      // 섹터 로테이션 점수(나침반). 없으면 -1 → 정렬 시 뒤로.
      const rot = sectorRot.get(sec)
      return {
        id: sec, sec, stocks, rankedStocks, sectorCap, momentum, avgChange, isDownSector,
        rotScore: rot?.score ?? -1, rotRank: rot?.rank ?? 0, lifecycle: rot?.lifecycle ?? '',
      }
    })

    // 전역 단조성 보장: 모든 종목을 단일 척도(관심종목 전체, 최대 시총=1.0)로 압축하고
    // 섹터 면적 = 보이는 타일 가중치의 합 → 섹터 면적은 같을 필요 없이 비중대로 벌어진다.
    // "시총이 더 작은 종목이 더 큰 공간을 가질 수 없다"가 섹터 경계를 넘어 성립한다.
    // 소외 섹터(하락/기타 + 시총 비중 8% 미만)만 공간이 작으므로 시총 상위 4개로 한정,
    // 그 외 섹터는 공간이 충분하므로 전 종목 노출.
    const allCaps = items.map(it => rawCap(it))
    const totalCap = allCaps.reduce((a, b) => a + b, 0)
    const secs = secsRaw.map(s => {
      const marginal = s.isDownSector && totalCap > 0 && s.sectorCap / totalCap < 0.08
      const visibleStocks = marginal ? s.rankedStocks.slice(0, 4) : s.rankedStocks
      const value = visibleStocks.reduce((sum, st) => sum + compress(rawCap(st), allCaps), 0)
      return { ...s, visibleStocks, value }
    })
    // 로테이션 점수 내림차순 — 강한 섹터가 좌상단에 배치 (면적은 시총대로 유지, 순서만 점수순)
    secs.sort((a, b) => b.rotScore - a.rotScore)

    const secRects: TRect[] = squarify(
      secs.map(s => ({ id: s.id, value: s.value })),
      0, 0, dims.w, dims.h, SEC_GAP,
      true,   // preserveOrder: 입력(점수순) 순서 유지 — squarify 내부 면적 재정렬 비활성
    )

    return secRects.map(sr => {
      const sd    = secs.find(s => s.id === sr.id)!
      const stkH  = Math.max(sr.h - SEC_H, 0)
      // 타일도 섹터 면적과 같은 전역 척도를 사용 — 섹터 면적이 타일 가중 합이므로
      // 어느 섹터에 있든 같은 시총이면 같은 면적, 더 큰 시총이면 더 큰 면적.
      const tiles = stkH > 4
        ? squarify(
            sd.visibleStocks.map(s => ({ id: s.code, value: compress(rawCap(s), allCaps) })),
            0, SEC_H, sr.w, stkH, STK_GAP,
          )
        : []
      const stockMap = new Map(sd.visibleStocks.map(s => [s.code, s]))
      return {
        ...sr, sec: sd.sec,
        totalCount: sd.stocks.length,
        shownCount: sd.visibleStocks.length,
        rotScore: sd.rotScore, rotRank: sd.rotRank, lifecycle: sd.lifecycle, avgChange: sd.avgChange,
        stocks: tiles.map(r => ({ ...r, item: stockMap.get(r.id)! })).filter(r => !!r.item),
      }
    })
  }, [items, dims, sectorRot])

  const handleDelete = useCallback((code: string) => {
    setBusyCode(code)
    fetchJson<{ ok: boolean }>(`/api/watchlist/${encodeURIComponent(code)}`, { method: 'DELETE' })
      .then(() => refresh()).finally(() => setBusyCode(null))
  }, [refresh])

  return (
    <>
      <header className="topbar glass">
        <div>
          <p className="top-label">Watchlist</p>
          <h2>관심 종목</h2>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div
            className="status-pill"
            onClick={() => openNaverItem(MARKET_ETF.code)}
            title={`${MARKET_ETF.label} (${MARKET_ETF.code}) — 네이버 시세 보기`}
            style={{ cursor: 'pointer', color: '#93c5fd' }}
          >
            ETF {MARKET_ETF.label}
            {etfQuotes[MARKET_ETF.code] != null && (
              <span style={{
                marginLeft: 5, fontWeight: 800,
                color: etfQuotes[MARKET_ETF.code].changeRate >= 0 ? '#34d399' : '#f87171',
              }}>
                {formatPercent(etfQuotes[MARKET_ETF.code].changeRate)}
              </span>
            )}
          </div>
          {data?.quoteBasis === 'prevClose' && (
            <div className="status-pill" style={{ color: '#fbbf24' }}>
              🕘 장 시작 전 · 전일 등락 기준
            </div>
          )}
          <div className="status-pill">총 {items.length}개</div>
          {!publicMode && (
            <button className="btn" type="button" onClick={() => setShowSearch(v => !v)}>
              {showSearch ? '✕ 닫기' : '＋ 종목 추가'}
            </button>
          )}
        </div>
      </header>

      {showSearch && (
        <div className="panel glass" style={{ padding: '0.75rem 1rem' }}>
          <div className="form-row is-1col" style={{ marginBottom: searchRows.length ? '0.5rem' : 0 }}>
            <label>
              <input
                placeholder="종목명 또는 코드 (예: 삼성전자 / 005930)"
                value={q}
                onChange={e => setQ(e.target.value)}
                autoFocus
              />
            </label>
          </div>
          {searchCaution && (
            <div style={CAUTION_BANNER_STYLE}>
              <span style={{ fontSize: 15, lineHeight: 1 }}>⚠️</span>
              <div><b>{searchCaution}</b></div>
            </div>
          )}
          {searchRows.length > 0 && (
            <table style={{ fontSize: '0.82rem', width: '100%' }}>
              <tbody>
                {searchRows.map(row => {
                  const already = itemCodes.has(row.code)
                  return (
                    <tr key={`sr-${row.code}`} style={{ height: 34 }}>
                      <td>
                        <b>{row.name}</b>{' '}
                        <span style={{ fontSize: '0.74rem', color: 'rgba(255,255,255,0.38)' }}>{row.code}</span>
                      </td>
                      <td style={{ width: 70, textAlign: 'right' }}>
                        <button
                          className="btn" type="button"
                          style={{ padding: '2px 10px', fontSize: '0.8rem' }}
                          disabled={already || addBusyCode === row.code}
                          onClick={() => {
                            setAddBusyCode(row.code)
                            fetchJson<OkOrCaution>('/api/watchlist', {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({ code: row.code }),
                            }).then((resp) => {
                              if (resp.excluded) {
                                // 거래 제외 종목 — 등록 대신 '투자 주의' 메시지 발행
                                setSearchCaution(resp.message ?? '[투자 주의] 거래 제외 종목입니다.')
                                return
                              }
                              refresh(); setQ('')
                            }).finally(() => setAddBusyCode(null))
                          }}
                        >
                          {already ? '추가됨' : '추가'}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ─── Heatmap canvas ─────────────────────────────────────── */}
      <div
        ref={containerRef}
        style={{
          position: 'relative',
          width: '100%',
          height: 'calc(100vh - 170px)',
          minHeight: 420,
          borderRadius: 14,
          overflow: 'hidden',
          background: 'linear-gradient(180deg, #0b1220 0%, #090f1a 100%)',
        }}
      >
        {data === null && !cachedItems.length && (
          <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'rgba(255,255,255,0.28)', fontSize: '0.9rem' }}>
            데이터를 불러오는 중…
          </div>
        )}
        {data !== null && !items.length && (
          <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'rgba(255,255,255,0.28)', fontSize: '0.9rem' }}>
            관심 종목이 없습니다
          </div>
        )}

        {showingCachedLayout && (
          <div style={{
            position: 'absolute', top: 8, right: 10,
            zIndex: 20,
            background: 'rgba(8,12,20,0.82)',
            border: '1px solid rgba(255,255,255,0.14)',
            borderRadius: 8,
            color: 'rgba(255,255,255,0.78)',
            fontSize: '0.68rem',
            fontWeight: 700,
            padding: '4px 8px',
          }}>
            캐시 배치 표시 중
          </div>
        )}

        {isLoading && items.length > 0 && (
          <div style={{
            position: 'absolute', top: 8, left: 10,
            zIndex: 20,
            background: 'rgba(18,83,56,0.82)',
            border: '1px solid rgba(134,239,172,0.45)',
            borderRadius: 8,
            color: 'rgba(220,252,231,0.9)',
            fontSize: '0.68rem',
            fontWeight: 700,
            padding: '4px 8px',
          }}>
            최신 데이터 동기화 중…
          </div>
        )}

        {/* Sector blocks */}
        {layout.map(sec => (
          <div
            key={sec.sec}
            style={{
              position: 'absolute',
              left: sec.x, top: sec.y, width: sec.w, height: sec.h,
              boxSizing: 'border-box',
                border: '1px solid rgba(255,255,255,0.12)',
                borderRadius: 2,
              overflow: 'hidden',
            }}
          >
            {/* Sector header — 로테이션 점수에 따라 좌측 색 띠 + 순위·점수 표기 */}
            <div
              style={{
                position: 'absolute', inset: '0 0 auto 0', height: SEC_H,
                display: 'flex', alignItems: 'center', padding: '0 7px',
                background: sectorHeatBg(sec.rotScore),
                borderLeft: sec.rotScore >= 0 ? `3px solid ${sectorHeatColor(sec.rotScore)}` : 'none',
                zIndex: 2, pointerEvents: 'none',
                fontSize: '0.62rem', fontWeight: 800,
                letterSpacing: '0.04em', color: 'rgba(255,255,255,0.78)',
                whiteSpace: 'nowrap', overflow: 'hidden',
              }}
            >
              {sec.rotRank > 0 && (
                <span style={{
                  marginRight: 5, padding: '0 4px', borderRadius: 3,
                  fontSize: '0.6rem', fontWeight: 800,
                  color: sectorHeatColor(sec.rotScore),
                  background: 'rgba(0,0,0,0.35)',
                }}>#{sec.rotRank}</span>
              )}
              {toKoreanSectorAbbr(sec.sec)}
              <TrendGlyph shape={computeTrendShape(sectorRot.get(sec.sec), sec.avgChange)} />
              {sec.rotScore >= 0 && (
                <span style={{ marginLeft: 2, fontWeight: 800, color: sectorHeatColor(sec.rotScore) }}>
                  {sec.rotScore.toFixed(1)}
                </span>
              )}
              {sec.lifecycle && (
                <span style={{ marginLeft: 4, opacity: 0.6, fontWeight: 400 }}>{sec.lifecycle}</span>
              )}
              <span style={{ marginLeft: 5, opacity: 0.42, fontWeight: 400 }}>
                {sec.shownCount}/{sec.totalCount}
              </span>
              {(SECTOR_ETFS[sec.sec] ?? []).map(etf => {
                const q = etfQuotes[etf.code]
                return (
                  <span
                    key={etf.code}
                    onClick={e => { e.stopPropagation(); openNaverItem(etf.code) }}
                    title={`KODEX ${etf.label} (${etf.code}) — 네이버 시세 보기`}
                    style={{
                      marginLeft: 6, padding: '1px 7px',
                      fontSize: '0.66rem', fontWeight: 600, letterSpacing: 0,
                      color: '#93c5fd', background: 'rgba(96,165,250,0.12)',
                      border: '1px solid rgba(96,165,250,0.3)', borderRadius: 99,
                      pointerEvents: 'auto', cursor: 'pointer',
                      overflow: 'hidden', textOverflow: 'ellipsis',
                    }}
                  >
                    ETF {etf.label}
                    {q != null && (
                      <span style={{
                        marginLeft: 4, fontWeight: 800,
                        color: q.changeRate >= 0 ? '#34d399' : '#f87171',
                      }}>
                        {formatPercent(q.changeRate)}
                      </span>
                    )}
                  </span>
                )
              })}
            </div>

            {/* Stock tiles */}
            {sec.stocks.map(({ id, x, y, w, h, item }) => {
              if (!item) return null
              const isHov     = hovered === id
              const showTiny  = w >= 28 && h >= 20
              const showName  = w >= 62 && h >= 38
              const showFull  = w >= 84 && h >= 62
              const showXL    = w >= 170 && h >= 110
              const shortName = abbreviateKoreanName(item.name)
              const icon = stockIcon(item)

              return (
                <div
                  key={id}
                  onMouseEnter={() => setHovered(id)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => setReportTarget({ code: item.code, name: item.name })}
                  title={
                    `${item.name} (${item.code})  ${item.price > 0 ? formatNumber(item.price) + '원  ' : ''}${formatPercent(item.changeRate)}  점수 ${item.score} — 클릭: AI 분석`
                    + (item.isLeader ? `\n👑 주도주 (주도 섹터 ${item.leaderSectorRank ?? '-'}위 · 섹터 내 ${item.leaderStockRank ?? '-'}위) — 제외 면제` : '')
                    + (!item.isLeader && item.isEtf ? '\n📊 ETF — 제외 면제 (주도주와 동일 레벨)' : '')
                    + (item.exclusion ? `\n${item.exclusion.message}${item.exclusion.detail ? `\n${item.exclusion.detail}` : ''}` : '')
                  }
                  style={{
                    position: 'absolute', left: x, top: y, width: w, height: h,
                    boxSizing: 'border-box',
                    background: changeColor(item.changeRate),
                    border: isHov
                      ? '1.5px solid rgba(255,255,255,0.55)'
                      : '0.7px solid rgba(0,0,0,0.34)',
                    borderRadius: 1,
                    overflow: 'hidden',
                    cursor: 'pointer',
                    display: 'flex', flexDirection: 'column',
                    alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  {/* 주도주 — 👑 뱃지 (주도 섹터의 주도주, 제외 면제) */}
                  {item.isLeader && showTiny && (
                    <span
                      style={{
                        position: 'absolute', top: 2, left: 2,
                        fontSize: w >= 62 ? '0.66rem' : '0.56rem',
                        lineHeight: 1,
                        padding: '1px 4px',
                        background: 'rgba(250,204,21,0.18)',
                        border: '1px solid rgba(250,204,21,0.55)',
                        borderRadius: 3,
                        color: '#facc15',
                        fontWeight: 800,
                        zIndex: 4,
                        pointerEvents: 'none',
                      }}
                    >
                      👑{w >= 84 ? ' 주도주' : ''}
                    </span>
                  )}

                  {/* ETF — 주도주와 동일 레벨 보호 뱃지 (주도주가 아닐 때 표시) */}
                  {!item.isLeader && item.isEtf && showTiny && (
                    <span
                      style={{
                        position: 'absolute', top: 2, left: 2,
                        fontSize: w >= 62 ? '0.66rem' : '0.56rem',
                        lineHeight: 1,
                        padding: '1px 4px',
                        background: 'rgba(96,165,250,0.18)',
                        border: '1px solid rgba(96,165,250,0.55)',
                        borderRadius: 3,
                        color: '#60a5fa',
                        fontWeight: 800,
                        zIndex: 4,
                        pointerEvents: 'none',
                      }}
                    >
                      📊{w >= 84 ? ' ETF' : ''}
                    </span>
                  )}

                  {/* 거래 제외 종목 — '투자 주의' 뱃지 (주도주·ETF가 아닐 때만; 툴팁에 사유) */}
                  {item.exclusion && !item.isLeader && !item.isEtf && showTiny && (
                    <span
                      style={{
                        position: 'absolute', top: 2, left: 2,
                        fontSize: w >= 62 ? '0.66rem' : '0.56rem',
                        lineHeight: 1,
                        padding: '1px 4px',
                        background: 'rgba(251,191,36,0.18)',
                        border: '1px solid rgba(251,191,36,0.5)',
                        borderRadius: 3,
                        color: '#fbbf24',
                        fontWeight: 800,
                        zIndex: 4,
                        pointerEvents: 'none',
                      }}
                    >
                      ⚠{w >= 84 ? ' 투자 주의' : ''}
                    </span>
                  )}

                  {/* Hover: delete button */}
                  {isHov && !publicMode && (
                    <button
                      type="button"
                      onClick={e => { e.stopPropagation(); handleDelete(item.code) }}
                      disabled={busyCode === item.code}
                      style={{
                        position: 'absolute', top: 2, right: 2,
                        width: 16, height: 16,
                        background: 'rgba(0,0,0,0.6)', border: 'none', borderRadius: 3,
                        color: 'rgba(255,255,255,0.8)', fontSize: '0.6rem',
                        cursor: 'pointer', display: 'grid', placeItems: 'center', zIndex: 5,
                      }}
                    >×</button>
                  )}

                  {showTiny && !showName && (
                    <span style={{
                      fontSize: '0.62rem',
                      fontWeight: 800,
                      color: 'rgba(255,255,255,0.86)',
                      userSelect: 'none',
                      letterSpacing: '0.01em',
                    }}>
                      {shortName}
                    </span>
                  )}

                  {showName && (
                    <>
                      {/* Logo above name — size scales with tile */}
                      {icon.startsWith('/') || icon.startsWith('http') ? (
                        <img
                          src={icon}
                          alt=""
                          style={{
                            width:  showXL ? 40 : showFull ? 26 : 18,
                            height: showXL ? 40 : showFull ? 26 : 18,
                            objectFit: 'contain',
                            borderRadius: showXL ? 10 : 4,
                            flexShrink: 0,
                            marginBottom: showXL ? 7 : showFull ? 4 : 2,
                          }}
                        />
                      ) : (
                        <span style={{
                          fontSize: showXL ? '1.6rem' : showFull ? '1.1rem' : '0.85rem',
                          lineHeight: 1,
                          marginBottom: showXL ? 7 : showFull ? 4 : 2,
                        }}>
                          {icon}
                        </span>
                      )}

                      {/* Name */}
                      <span style={{
                        fontSize: showXL ? '1.14rem' : showFull ? '0.96rem' : '0.7rem',
                        fontWeight: 800,
                        color: 'rgba(255,255,255,0.92)',
                        textAlign: 'center',
                        padding: '0 4px',
                        maxWidth: '100%',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        userSelect: 'none',
                      }}>
                        {item.name}
                      </span>

                      {showFull && (
                        <span style={{
                          fontSize: showXL ? '0.96rem' : '0.82rem', fontWeight: 700, marginTop: 3,
                          userSelect: 'none',
                          color: 'rgba(255,255,255,0.92)',
                        }}>
                          {item.price > 0 ? formatPercent(item.changeRate) : '—'}
                        </span>
                      )}
                    </>
                  )}
                </div>
              )
            })}
          </div>
        ))}

      </div>

      {/* 종목 클릭 → AI 분석 리포트 */}
      {reportTarget && (
        <StockReportModal
          code={reportTarget.code}
          name={reportTarget.name}
          onClose={() => setReportTarget(null)}
        />
      )}
    </>
  )
}

