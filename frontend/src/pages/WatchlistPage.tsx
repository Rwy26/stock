import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchJson } from '../lib/api'
import { publicFetch } from '../lib/publicApi'
import { formatNumber, formatPercent } from '../lib/format'

// ── Types ────────────────────────────────────────────────────────────
type WatchItem = {
  name: string; code: string; price: number
  changeRate: number; score: number; sector: string; icon?: string
  marketCap?: number
}
type WatchlistResponse = { items: WatchItem[] }
type StockRow = { name: string; code: string; price: number; changeRate: number; score: number }
type SearchResponse = { items: StockRow[] }
type TRect = { id: string; x: number; y: number; w: number; h: number }

const WATCHLIST_CACHE_KEY = 'moon-watchlist-cache-v1'

// ── Squarified Treemap ───────────────────────────────────────────────
function squarify(
  items: Array<{ id: string; value: number }>,
  x0: number, y0: number, w0: number, h0: number,
  gap = 0,
): TRect[] {
  if (!items.length || w0 < 0.5 || h0 < 0.5) return []
  const total = items.reduce((s, i) => s + Math.max(i.value, 0.001), 0)
  const area = w0 * h0
  const sorted = [...items]
    .sort((a, b) => b.value - a.value)
    .map(i => ({ id: i.id, a: (Math.max(i.value, 0.001) / total) * area }))
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
  '자동차·로봇': '🚗',
  '2차전지': '🔋',
  '바이오': '🧬',
  '금융': '🏦',
  '우주항공': '🛰',
  '전력기기': '⚡',
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

function toKoreanSectorAbbr(sector: string): string {
  const s = (sector || '').trim()
  if (!s) return '기타'
  const map: Record<string, string> = {
    '반도체': '반도체',
    '로봇·AI수혜': '로봇·AI',
    '기타수급': '기타수급',
    '2차전지·ESS': '2차전지',
    '자동차·로봇': '자동차·로봇',
    'MLCC·반도체기판': 'MLCC·기판',
    '금융': '금융',
    '바이오': '바이오',
  }
  return map[s] ?? abbreviateKoreanName(s, 6)
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

// Space allocation uses deadzone + asymptotic compression to avoid extreme area gaps.
const AREA_MIN_WEIGHT   = 1
const AREA_MAX_BOOST    = 3.2
const AREA_DEADZONE     = 15
const AREA_CURVE_FACTOR = 3.6

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(Math.max(n, lo), hi)
}

function scoreToAreaWeight(score: number): number {
  const s = Math.min(Math.max(score, 0), 100)
  if (s <= AREA_DEADZONE) return AREA_MIN_WEIGHT
  const normalized = (s - AREA_DEADZONE) / (100 - AREA_DEADZONE)
  const asymptotic = 1 - Math.exp(-AREA_CURVE_FACTOR * normalized)
  return AREA_MIN_WEIGHT + AREA_MAX_BOOST * asymptotic
}

// Tile/sector area weight = 시가총액(market cap). Falls back to a score-based
// weight (comparable scale) when market cap is unavailable (e.g. admin view).
function stockWeight(item: WatchItem): number {
  const cap = typeof item.marketCap === 'number' ? item.marketCap : 0
  if (cap > 0) return cap
  return Math.max(scoreToAreaWeight(item.score), 0.001) * 1e11
}

export function WatchlistPage({ publicMode = false }: { publicMode?: boolean } = {}) {
  const [data, setData]           = useState<WatchlistResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [busyCode, setBusyCode]   = useState<string | null>(null)
  const [q, setQ]                 = useState('')
  const [searchRows, setSearchRows] = useState<StockRow[]>([])
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

  const loadWatchlist = useCallback(
    (): Promise<WatchlistResponse> =>
      publicMode
        ? publicFetch<WatchlistResponse>('/api/public/watchlist')
        : loadWatchlist(),
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
    if (!q.trim()) { setSearchRows([]); return }
    const h = setTimeout(() => {
      fetchJson<SearchResponse>(
        `/api/stocks/search?q=${encodeURIComponent(q)}&market=ALL&sort=${encodeURIComponent('관련도')}`
      ).then(p => setSearchRows(p.items.slice(0, 8))).catch(() => setSearchRows([]))
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

    const secs = Array.from(secMap.entries()).map(([sec, stocks]) => {
      const total = stocks.length || 1
      const avgChange = stocks.reduce((s, i) => s + i.changeRate, 0) / total
      const avgScore = stocks.reduce((s, i) => s + (i.score || 0), 0) / total
      const downRatio = stocks.filter(s => s.changeRate < 0).length / total
      const isEtc = sec.includes('기타')
      const isDownSector = isEtc || avgChange <= -0.4 || downRatio >= 0.65

      // Rank member stocks by market cap (largest first).
      const rankedStocks = [...stocks].sort((a, b) => stockWeight(b) - stockWeight(a))

      const positiveRatio = stocks.filter(s => s.changeRate > 0).length / total
      const strongRatio = clamp(0.44 + positiveRatio * 0.34 + Math.max(avgChange, 0) * 0.05, 0.3, 1)
      const weakRatio = clamp(0.28 + positiveRatio * 0.16, 0.2, 0.55)
      const visibleRatio = isDownSector ? weakRatio : strongRatio
      const visibleCount = clamp(Math.round(stocks.length * visibleRatio), Math.min(2, stocks.length), stocks.length)
      const visibleStocks = rankedStocks.slice(0, visibleCount)

      // Sector area = 시가총액 합 × (주도/상승 가중). 큰 시총·주도·상승일수록 커져서 좌상단으로,
      // 작은 시총·소외·하락일수록 작아져서 우하단으로 배치된다.
      const capSum = visibleStocks.reduce((s, i) => s + stockWeight(i), 0)
      const momentum = 1 + clamp(avgChange, -3, 3) * 0.10 + (clamp(avgScore, 0, 100) / 100) * 0.20
      const value = capSum * Math.max(momentum, 0.3)

      return { id: sec, sec, stocks, visibleStocks, value, avgChange, isDownSector }
    })

    // Single squarified layout sorted by the composite value:
    // leading large-cap rising sectors → top-left, neglected small-cap falling → bottom-right.
    const secRects: TRect[] = squarify(
      secs.map(s => ({ id: s.id, value: s.value })),
      0, 0, dims.w, dims.h, SEC_GAP,
    )

    return secRects.map(sr => {
      const sd    = secs.find(s => s.id === sr.id)!
      const stkH  = Math.max(sr.h - SEC_H, 0)
      const tiles = stkH > 4
        ? squarify(
            sd.visibleStocks.map(s => ({ id: s.code, value: stockWeight(s) })),
            0, SEC_H, sr.w, stkH, STK_GAP,
          )
        : []
      const stockMap = new Map(sd.visibleStocks.map(s => [s.code, s]))
      return {
        ...sr, sec: sd.sec,
        totalCount: sd.stocks.length,
        shownCount: sd.visibleStocks.length,
        stocks: tiles.map(r => ({ ...r, item: stockMap.get(r.id)! })).filter(r => !!r.item),
      }
    })
  }, [items, dims])

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
                            fetchJson<{ ok: boolean }>('/api/watchlist', {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({ code: row.code }),
                            }).then(() => { refresh(); setQ('') }).finally(() => setAddBusyCode(null))
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
            {/* Sector header */}
            <div
              style={{
                position: 'absolute', inset: '0 0 auto 0', height: SEC_H,
                display: 'flex', alignItems: 'center', padding: '0 7px',
                background: 'rgba(10,15,24,0.84)',
                zIndex: 2, pointerEvents: 'none',
                fontSize: '0.62rem', fontWeight: 800,
                letterSpacing: '0.04em', color: 'rgba(255,255,255,0.72)',
                whiteSpace: 'nowrap', overflow: 'hidden',
              }}
            >
              {toKoreanSectorAbbr(sec.sec)}
              <span style={{ marginLeft: 5, opacity: 0.42, fontWeight: 400 }}>
                {sec.shownCount}/{sec.totalCount}
              </span>
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
                  onClick={() =>
                    window.open(`https://finance.naver.com/item/main.naver?code=${item.code}`, '_blank', 'noreferrer')
                  }
                  title={`${item.name} (${item.code})  ${item.price > 0 ? formatNumber(item.price) + '원  ' : ''}${formatPercent(item.changeRate)}  점수 ${item.score}`}
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
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 4,
                      }}>
                        {icon.startsWith('/') || icon.startsWith('http') ? (
                          <img
                            src={icon}
                            alt=""
                            style={{
                              width: showFull ? 18 : 14,
                              height: showFull ? 18 : 14,
                              objectFit: 'contain',
                              borderRadius: 3,
                              flexShrink: 0,
                            }}
                          />
                        ) : (
                          <span style={{ fontSize: showFull ? '0.85rem' : '0.72rem', lineHeight: 1 }}>
                            {icon}
                          </span>
                        )}
                        {item.name}
                      </span>

                      {showFull && (
                        <>
                          <span style={{
                            fontSize: showXL ? '0.96rem' : '0.82rem', fontWeight: 700, marginTop: 3,
                            userSelect: 'none',
                            color: 'rgba(255,255,255,0.92)',
                          }}>
                            {item.price > 0 ? formatPercent(item.changeRate) : '—'}
                          </span>
                        </>
                      )}
                    </>
                  )}
                </div>
              )
            })}
          </div>
        ))}

      </div>
    </>
  )
}

