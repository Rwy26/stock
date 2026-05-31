import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchJson } from '../lib/api'
import { formatNumber, formatPercent } from '../lib/format'

// ── Types ────────────────────────────────────────────────────────────
type WatchItem = {
  name: string; code: string; price: number
  changeRate: number; score: number; sector: string
}
type WatchlistResponse = { items: WatchItem[] }
type StockRow = { name: string; code: string; price: number; changeRate: number; score: number }
type SearchResponse = { items: StockRow[] }
type TRect = { id: string; x: number; y: number; w: number; h: number }

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

// ── Score → Color (dark-gray → dark-red → bright-red) ────────────────
function scoreColor(score: number): string {
  const t = Math.min(Math.max(score, 0), 100) / 100
  const sat = (t * 84).toFixed(0)
  const light = (9 + t * 34).toFixed(0)
  return `hsl(0,${sat}%,${light}%)`
}

// ── Constants ────────────────────────────────────────────────────────
const SEC_GAP = 3   // gap between sector blocks
const STK_GAP = 1   // gap between stock tiles
const SEC_H   = 22  // sector label bar height

export function WatchlistPage() {
  const [data, setData]           = useState<WatchlistResponse | null>(null)
  const [busyCode, setBusyCode]   = useState<string | null>(null)
  const [q, setQ]                 = useState('')
  const [searchRows, setSearchRows] = useState<StockRow[]>([])
  const [addBusyCode, setAddBusyCode] = useState<string | null>(null)
  const [showSearch, setShowSearch]   = useState(false)
  const [hovered, setHovered]     = useState<string | null>(null)
  const containerRef              = useRef<HTMLDivElement>(null)
  const [dims, setDims]           = useState({ w: 900, h: 620 })

  const refresh = useCallback(() => {
    fetchJson<WatchlistResponse>('/api/watchlist').then(p => setData(p)).catch(() => setData(null))
  }, [])

  // Poll every 30 s
  useEffect(() => {
    let dead = false
    const load = () =>
      fetchJson<WatchlistResponse>('/api/watchlist')
        .then(p => { if (!dead) setData(p) })
        .catch(() => { if (!dead) setData(null) })
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

  const items     = useMemo(() => data?.items ?? [], [data])
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

    const secs = Array.from(secMap.entries()).map(([sec, stocks]) => ({
      id: sec, sec, stocks,
      value: stocks.reduce((s, i) => s + Math.max(i.score, 1), 0),
    }))

    const secRects = squarify(
      secs.map(s => ({ id: s.id, value: s.value })),
      0, 0, dims.w, dims.h, SEC_GAP,
    )

    return secRects.map(sr => {
      const sd    = secs.find(s => s.id === sr.id)!
      const stkH  = Math.max(sr.h - SEC_H, 0)
      const tiles = stkH > 4
        ? squarify(
            sd.stocks.map(s => ({ id: s.code, value: Math.max(s.score, 1) })),
            0, SEC_H, sr.w, stkH, STK_GAP,
          )
        : []
      return {
        ...sr, sec: sd.sec,
        stocks: tiles.map(r => ({ ...r, item: sd.stocks.find(s => s.code === r.id)! })),
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
          <button className="btn" type="button" onClick={() => setShowSearch(v => !v)}>
            {showSearch ? '✕ 닫기' : '＋ 종목 추가'}
          </button>
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
          background: '#07070f',
        }}
      >
        {data === null && (
          <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'rgba(255,255,255,0.28)', fontSize: '0.9rem' }}>
            데이터를 불러오는 중…
          </div>
        )}
        {data !== null && !items.length && (
          <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'rgba(255,255,255,0.28)', fontSize: '0.9rem' }}>
            관심 종목이 없습니다
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
              border: '1px solid rgba(255,255,255,0.08)',
              borderRadius: 3,
              overflow: 'hidden',
            }}
          >
            {/* Sector header */}
            <div
              style={{
                position: 'absolute', inset: '0 0 auto 0', height: SEC_H,
                display: 'flex', alignItems: 'center', padding: '0 7px',
                background: 'rgba(7,7,15,0.78)',
                zIndex: 2, pointerEvents: 'none',
                fontSize: '0.64rem', fontWeight: 700,
                letterSpacing: '0.06em', color: 'rgba(255,255,255,0.6)',
                whiteSpace: 'nowrap', overflow: 'hidden',
              }}
            >
              {sec.sec}
              <span style={{ marginLeft: 5, opacity: 0.42, fontWeight: 400 }}>
                {sec.stocks.length}
              </span>
            </div>

            {/* Stock tiles */}
            {sec.stocks.map(({ id, x, y, w, h, item }) => {
              if (!item) return null
              const isHov     = hovered === id
              const showCode  = w >= 34 && h >= 26
              const showName  = w >= 52 && h >= 38
              const showFull  = w >= 72 && h >= 56

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
                    background: scoreColor(item.score),
                    border: isHov
                      ? '1.5px solid rgba(255,255,255,0.55)'
                      : '0.5px solid rgba(0,0,0,0.3)',
                    borderRadius: 2,
                    overflow: 'hidden',
                    cursor: 'pointer',
                    display: 'flex', flexDirection: 'column',
                    alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  {/* Hover: delete button */}
                  {isHov && (
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

                  {showCode && !showName && (
                    <span style={{
                      fontSize: '0.6rem', fontWeight: 700,
                      color: 'rgba(255,255,255,0.75)',
                      userSelect: 'none', letterSpacing: '0.03em',
                    }}>
                      {item.code}
                    </span>
                  )}

                  {showName && (
                    <>
                      <span style={{
                        fontSize: showFull ? '0.78rem' : '0.68rem',
                        fontWeight: 700,
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
                        <>
                          <span style={{
                            fontSize: '0.7rem', fontWeight: 600, marginTop: 3,
                            userSelect: 'none',
                            color: item.changeRate > 0
                              ? '#86efac'
                              : item.changeRate < 0
                              ? '#fca5a5'
                              : 'rgba(255,255,255,0.5)',
                          }}>
                            {item.price > 0 ? formatPercent(item.changeRate) : '—'}
                          </span>
                          <span style={{
                            fontSize: '0.58rem', marginTop: 2,
                            userSelect: 'none',
                            color: 'rgba(255,255,255,0.38)',
                          }}>
                            {item.score}점
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

        {/* Score legend */}
        {items.length > 0 && (
          <div style={{
            position: 'absolute', bottom: 8, right: 10,
            display: 'flex', alignItems: 'center', gap: 4,
            pointerEvents: 'none',
          }}>
            <span style={{ fontSize: '0.6rem', color: 'rgba(255,255,255,0.32)' }}>낮음</span>
            {[0, 15, 30, 45, 60, 75, 90].map(v => (
              <div
                key={v}
                style={{
                  width: 16, height: 10, borderRadius: 2,
                  background: scoreColor(v),
                  border: '0.5px solid rgba(255,255,255,0.1)',
                }}
              />
            ))}
            <span style={{ fontSize: '0.6rem', color: 'rgba(255,255,255,0.32)' }}>높음 (점수)</span>
          </div>
        )}
      </div>
    </>
  )
}

