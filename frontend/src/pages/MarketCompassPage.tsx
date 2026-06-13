import { useCallback, useEffect, useState } from 'react'
import { fetchJson } from '../lib/api'

// ─── Types ───────────────────────────────────────────────────────────────────

interface Regime { label: string; evidence: string[] }
interface LadderGroup { avgScore: number; avgIntraday: number; sectors: string[] }
interface Ladder { position: string; groups: Record<string, LadderGroup>; ladder: string[] }
interface RankRow {
  rank: number; sector: string; score: number; lifecycle?: string; intradayPct?: number
}
interface ProbBand { up: number; down: number }
interface GlobalSentiment {
  available: boolean
  scores?: Record<string, number>
  composite?: number | null
  flow?: string | null
  probabilities?: { method?: string; n?: number | null } & Record<string, ProbBand | string | number | null>
  krSectors?: Record<string, number>
  evidence?: Record<string, string[]>
  asof?: string
  error?: string
}
interface MarketData {
  asOf: string
  vkospi: { value: number | null; level: string }
  globalSentiment?: GlobalSentiment
  regime: Regime
  rotationLadder: Ladder
  sectorRanking: RankRow[]
  aiReport: string | null
  aiProvider: string
  cached: boolean
}

interface TargetItem { price: number | null; note?: string; excluded?: boolean }
interface StockData {
  asOf: string
  stock: {
    code: string; name: string; sector: string | null
    sectorRank: number | null; sectorScore: number | null; currentPrice: number
  }
  mtf: {
    alignment: { summary: string }
    timeframes: Array<{
      label: string; trend?: string; emaState?: string; rsi14?: number | null
      structureEvent?: { type: string; level: number } | null
      cdv?: { direction?: string }; error?: string
    }>
  }
  targets: { list: Record<string, TargetItem>; avgTarget: number | null; avgTargetUpside: number | null }
  stops: Record<string, { price: number | null; basis: string }>
  probability: Record<string, unknown>
  composite: { score: number; grade: string; parts: Record<string, number>; riskReward: number | null }
  aiReport: string | null
  aiProvider: string
}

// ─── 간이 마크다운 렌더러 (외부 의존성 없음) ─────────────────────────────────

function Markdown({ text }: { text: string }) {
  const lines = text.split('\n')
  const out: React.ReactNode[] = []
  lines.forEach((raw, i) => {
    const line = raw.replace(/\*\*(.+?)\*\*/g, '⟪$1⟫') // bold 마커 임시 치환
    const bold = (s: string) =>
      s.split(/(⟪.+?⟫)/).map((seg, j) =>
        seg.startsWith('⟪')
          ? <b key={j} style={{ color: '#f1f5f9' }}>{seg.slice(1, -1)}</b>
          : seg)
    if (line.startsWith('# ')) {
      out.push(<h3 key={i} style={{ margin: '18px 0 8px', color: '#93c5fd' }}>{line.slice(2)}</h3>)
    } else if (line.startsWith('## ')) {
      out.push(<h4 key={i} style={{ margin: '14px 0 6px', color: '#a5b4fc' }}>{line.slice(3)}</h4>)
    } else if (line.trim() === '---') {
      out.push(<hr key={i} style={{ border: 'none', borderTop: '1px solid rgba(255,255,255,0.1)', margin: '12px 0' }} />)
    } else if (/^\s*[*-]\s+/.test(line)) {
      out.push(
        <p key={i} style={{ margin: '3px 0 3px 14px', lineHeight: 1.65 }}>
          <span style={{ color: '#64748b' }}>•</span> {bold(line.replace(/^\s*[*-]\s+/, ''))}
        </p>,
      )
    } else if (line.trim() === '') {
      out.push(<div key={i} style={{ height: 6 }} />)
    } else {
      out.push(<p key={i} style={{ margin: '3px 0', lineHeight: 1.65 }}>{bold(line)}</p>)
    }
  })
  return <div style={{ fontSize: 13.5, color: 'rgba(241,245,249,0.85)' }}>{out}</div>
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fmt = (n: number | null | undefined) => (n == null ? 'N/A' : n.toLocaleString())
const GRADE_COLOR: Record<string, string> = { S: '#fbbf24', A: '#34d399', B: '#60a5fa', C: '#eab308', D: '#f87171' }
const panel: React.CSSProperties = {
  background: 'rgba(6,9,22,0.92)', border: '1px solid rgba(255,255,255,0.08)',
  borderRadius: 14, padding: '16px 18px', marginBottom: 18,
}

// ─── 글로벌 투자심리 (0단계) ─────────────────────────────────────────────────

const SCORE_LABELS: Record<string, string> = {
  risk_appetite: '위험선호', liquidity: '유동성', ai_cycle: 'AI 사이클', growth: '경기',
  inflation: '물가안정', geopolitics: '지정학(완화)', us_equity: '미국증시', kr_equity: '한국증시',
}
// composite 가중치 순서 (선행지표 먼저)
const SCORE_ORDER = ['risk_appetite', 'liquidity', 'ai_cycle', 'growth', 'inflation', 'geopolitics', 'us_equity', 'kr_equity']

// 점수↑ = 우호(물가안정·지정학완화 포함 부호 일관) → 60↑ 강세, 40↓ 약세
const scoreColor = (v: number) => (v >= 60 ? '#34d399' : v >= 40 ? '#fbbf24' : '#f87171')

function ScoreBar({ k, v, evidence }: { k: string; v: number; evidence?: string[] }) {
  return (
    <div title={evidence?.join('\n')} style={{ marginBottom: 7, cursor: evidence?.length ? 'help' : 'default' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, marginBottom: 2 }}>
        <span style={{ color: 'rgba(241,245,249,0.75)' }}>{SCORE_LABELS[k] ?? k}</span>
        <span style={{ fontWeight: 700, color: scoreColor(v) }}>{v}</span>
      </div>
      <div style={{ height: 6, borderRadius: 99, background: 'rgba(255,255,255,0.07)', overflow: 'hidden' }}>
        <div style={{ width: `${v}%`, height: '100%', background: scoreColor(v), transition: 'width .4s' }} />
      </div>
    </div>
  )
}

function GlobalSentimentPanel({ g }: { g: GlobalSentiment }) {
  if (!g.available) {
    return (
      <div style={panel}>
        <h4 style={{ margin: 0, color: '#93c5fd' }}>🌐 글로벌 투자심리</h4>
        <p style={{ fontSize: 12.5, color: '#64748b', margin: '6px 0 0' }}>
          데이터 N/A — {g.error ?? '엔진 일시 불가'} (시장 분석은 정상 진행)
        </p>
      </div>
    )
  }
  const scores = g.scores ?? {}
  const comp = g.composite ?? null
  const compColor = comp == null ? '#94a3b8' : scoreColor(comp)
  const prob = g.probabilities ?? {}
  const method = prob.method === 'frequency' ? `빈도 기반 (n=${prob.n})` : '로지스틱 (표본 누적 전)'
  const bands: Array<[string, string]> = [['1w', '1주'], ['1m', '1개월'], ['3m', '3개월']]

  return (
    <div style={{ ...panel, borderColor: 'rgba(96,165,250,0.3)' }}>
      <h4 style={{ margin: '0 0 12px', color: '#93c5fd' }}>
        🌐 글로벌 투자심리 (0단계 — 국내 판정 선행)
        <span style={{ marginLeft: 8, fontSize: 11, color: '#475569' }}>{g.asof?.replace('T', ' ')}</span>
      </h4>

      <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: 20, alignItems: 'start' }}>
        {/* 종합 + 확률 */}
        <div>
          <div style={{ textAlign: 'center', padding: '10px 0' }}>
            <div style={{ fontSize: 11, color: '#64748b', letterSpacing: 1 }}>COMPOSITE</div>
            <div style={{ fontSize: 44, fontWeight: 800, color: compColor, lineHeight: 1.1 }}>{comp ?? 'N/A'}</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: compColor }}>{g.flow ?? ''}</div>
          </div>
          <div style={{ height: 1, background: 'rgba(255,255,255,0.08)', margin: '8px 0' }} />
          <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>상승확률 ({method})</div>
          {bands.map(([key, label]) => {
            const b = prob[key] as ProbBand | undefined
            if (!b) return null
            return (
              <div key={key} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, padding: '2px 0' }}>
                <span style={{ color: 'rgba(241,245,249,0.65)' }}>{label}</span>
                <span style={{ color: b.up >= 50 ? '#34d399' : '#f87171', fontWeight: 700 }}>
                  ▲{b.up}% <span style={{ color: '#475569', fontWeight: 400 }}>/ ▼{b.down}%</span>
                </span>
              </div>
            )
          })}
        </div>

        {/* 8 점수 바 */}
        <div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 24 }}>
            {SCORE_ORDER.filter(k => scores[k] != null).map(k => (
              <ScoreBar key={k} k={k} v={scores[k]} evidence={g.evidence?.[k]} />
            ))}
          </div>
        </div>
      </div>

      {/* 한국 7섹터 매핑 */}
      {g.krSectors && (
        <>
          <div style={{ height: 1, background: 'rgba(255,255,255,0.08)', margin: '12px 0 10px' }} />
          <div style={{ fontSize: 11, color: '#64748b', marginBottom: 6 }}>글로벌 → 한국 섹터 영향</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {Object.entries(g.krSectors).sort((a, b) => b[1] - a[1]).map(([sec, v]) => (
              <span key={sec} style={{
                padding: '4px 10px', borderRadius: 99, fontSize: 12.5,
                background: 'rgba(255,255,255,0.05)', border: `1px solid ${scoreColor(v)}55`, color: scoreColor(v),
              }}>
                {sec} <b>{v}</b>
              </span>
            ))}
          </div>
        </>
      )}
      <p style={{ fontSize: 11, color: '#475569', margin: '10px 0 0' }}>
        점수 50=중립 · 높을수록 우호(물가안정·지정학완화 포함) · 점수에 마우스를 올리면 원천 근거 표시
      </p>
    </div>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

export function MarketCompassPage() {
  const [market, setMarket] = useState<MarketData | null>(null)
  const [mLoading, setMLoading] = useState(false)
  const [mErr, setMErr] = useState<string | null>(null)

  const [code, setCode] = useState('')
  const [stock, setStock] = useState<StockData | null>(null)
  const [sLoading, setSLoading] = useState(false)
  const [sErr, setSErr] = useState<string | null>(null)

  const loadMarket = useCallback((force = false) => {
    setMLoading(true)
    setMErr(null)
    fetchJson<MarketData>(`/api/admin/market-compass${force ? '?force=1' : ''}`)
      .then(setMarket)
      .catch(e => setMErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setMLoading(false))
  }, [])

  useEffect(() => { loadMarket() }, [loadMarket])

  const analyzeStock = useCallback(async () => {
    const q = code.trim()
    if (!q) return
    setSLoading(true)
    setSErr(null)
    setStock(null)
    try {
      let c = q
      if (!/^\d{6}$/.test(q)) {
        // 이름 검색 → 첫 매치 코드
        const r = await fetchJson<{ items: Array<{ code: string }> }>(
          `/api/stocks/search?q=${encodeURIComponent(q)}&market=ALL&sort=${encodeURIComponent('관련도')}`)
        if (!r.items.length) throw new Error(`'${q}' 검색 결과 없음`)
        c = r.items[0].code
      }
      const data = await fetchJson<StockData & { excluded?: boolean; message?: string }>(`/api/admin/stock-compass?code=${c}`)
      if (data.excluded) {
        // 거래 제외 종목 — 분석 대신 '투자 주의' 메시지 발행 (HTTP 200)
        setSErr(data.message ?? '[투자 주의] 거래 제외 종목입니다.')
        return
      }
      setStock(data)
    } catch (e) {
      setSErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSLoading(false)
    }
  }, [code])

  return (
    <div>
      <header className="topbar glass">
        <div>
          <p className="top-label">Market Compass</p>
          <h2>📡 시장 나침반 (AI 자금흐름 분석)</h2>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn" type="button" disabled={mLoading} onClick={() => loadMarket(true)}>
            {mLoading ? '계산 중…' : '시장 재분석'}
          </button>
        </div>
      </header>

      {/* ── 시장 차원 (1~7단계) ─────────────────────────────── */}
      {mErr && <p style={{ color: '#f87171' }}>시장 분석 실패: {mErr}</p>}
      {mLoading && !market && <p style={{ color: '#94a3b8' }}>시장 데이터 계산 중… (최대 1분)</p>}

      {market && (
        <>
          {market.globalSentiment && <GlobalSentimentPanel g={market.globalSentiment} />}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
            <div style={panel}>
              <h4 style={{ margin: '0 0 10px', color: '#93c5fd' }}>
                시장 구조 — {market.regime.label}
                <span style={{ marginLeft: 8, fontSize: 12, color: '#64748b' }}>
                  {market.asOf}{market.cached ? ' (캐시)' : ''}
                </span>
              </h4>
              {market.regime.evidence.map((e, i) => (
                <p key={i} style={{ fontSize: 13, margin: '4px 0', color: 'rgba(241,245,249,0.75)' }}>• {e}</p>
              ))}
              <p style={{ fontSize: 13, marginTop: 8 }}>
                VKOSPI <b style={{ color: '#f87171' }}>{market.vkospi.value}</b> ({market.vkospi.level})
              </p>
            </div>

            <div style={panel}>
              <h4 style={{ margin: '0 0 10px', color: '#93c5fd' }}>
                섹터 순환 사다리 — 현재 <b style={{ color: '#fbbf24' }}>{market.rotationLadder.position}</b>
              </h4>
              {Object.entries(market.rotationLadder.groups).map(([g, p]) => (
                <div key={g} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '3px 0' }}>
                  <span style={{ color: g === market.rotationLadder.position ? '#fbbf24' : 'rgba(241,245,249,0.7)' }}>
                    {g} <span style={{ color: '#475569', fontSize: 11 }}>({p.sectors.join('·')})</span>
                  </span>
                  <span style={{ fontWeight: 700, color: p.avgIntraday >= 0 ? '#34d399' : '#f87171' }}>
                    {p.avgIntraday >= 0 ? '+' : ''}{p.avgIntraday}%
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div style={panel}>
            <h4 style={{ margin: '0 0 10px', color: '#93c5fd' }}>주도 섹터 순위</h4>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {market.sectorRanking.map(s => (
                <span key={s.sector} style={{
                  padding: '4px 10px', borderRadius: 99, fontSize: 12.5,
                  background: s.rank <= 3 ? 'rgba(251,191,36,0.12)' : 'rgba(255,255,255,0.05)',
                  border: `1px solid ${s.rank <= 3 ? 'rgba(251,191,36,0.4)' : 'rgba(255,255,255,0.1)'}`,
                  color: s.rank <= 3 ? '#fbbf24' : 'rgba(241,245,249,0.7)',
                }}>
                  {s.rank}위 {s.sector} {s.score}
                  <span style={{ marginLeft: 5, color: (s.intradayPct ?? 0) >= 0 ? '#34d399' : '#f87171' }}>
                    {(s.intradayPct ?? 0) >= 0 ? '+' : ''}{s.intradayPct}%
                  </span>
                </span>
              ))}
            </div>
          </div>

          {market.aiReport && (
            <div style={panel}>
              <h4 style={{ margin: '0 0 4px', color: '#93c5fd' }}>
                AI 종합 리포트 <span style={{ fontSize: 11, color: '#475569' }}>{market.aiProvider}</span>
              </h4>
              <Markdown text={market.aiReport} />
            </div>
          )}
        </>
      )}

      {/* ── 종목 차원 (12단계 통합) ───────────────────────────── */}
      <div style={{ ...panel, borderColor: 'rgba(96,165,250,0.3)' }}>
        <h4 style={{ margin: '0 0 10px', color: '#93c5fd' }}>종목 종합 평가 (12단계)</h4>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            value={code}
            onChange={e => setCode(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') analyzeStock() }}
            placeholder="종목코드 또는 이름 (예: 005930, 삼성전자)"
            style={{
              flex: 1, padding: '9px 12px', borderRadius: 8,
              border: '1px solid rgba(255,255,255,0.15)',
              background: 'rgba(255,255,255,0.05)', color: '#f1f5f9',
            }}
          />
          <button className="btn" type="button" disabled={sLoading} onClick={analyzeStock}>
            {sLoading ? '분석 중… (~30초)' : '분석'}
          </button>
        </div>
        {sErr && <p style={{ color: '#f87171', marginTop: 8 }}>{sErr}</p>}
      </div>

      {stock && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 18 }}>
            <div style={panel}>
              <h4 style={{ margin: '0 0 8px', color: '#93c5fd' }}>
                {stock.stock.name} <span style={{ color: '#64748b', fontSize: 12 }}>{stock.stock.code}</span>
              </h4>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                <span style={{ fontSize: 34, fontWeight: 800, color: GRADE_COLOR[stock.composite.grade] ?? '#94a3b8' }}>
                  {stock.composite.grade}
                </span>
                <span style={{ fontSize: 20, fontWeight: 700 }}>{stock.composite.score}점</span>
              </div>
              {Object.entries(stock.composite.parts).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, padding: '2px 0' }}>
                  <span style={{ color: 'rgba(241,245,249,0.6)' }}>{k}</span><span>{v}</span>
                </div>
              ))}
              <p style={{ fontSize: 12.5, marginTop: 6, color: '#94a3b8' }}>
                손익비 {stock.composite.riskReward ?? 'N/A'} ·
                섹터 {stock.stock.sector} {stock.stock.sectorRank}위
              </p>
            </div>

            <div style={panel}>
              <h4 style={{ margin: '0 0 8px', color: '#93c5fd' }}>목표가 (5종 평균: {fmt(stock.targets.avgTarget)})</h4>
              {Object.entries(stock.targets.list).map(([k, t]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, padding: '2px 0' }}>
                  <span style={{ color: 'rgba(241,245,249,0.6)', textDecoration: t.excluded ? 'line-through' : 'none' }}>{k}</span>
                  <span style={{ color: t.excluded ? '#64748b' : '#34d399' }}>{fmt(t.price)}</span>
                </div>
              ))}
              <p style={{ fontSize: 12.5, marginTop: 6, color: '#94a3b8' }}>
                현재가 {fmt(stock.stock.currentPrice)} → 상승여력 {stock.targets.avgTargetUpside}%
              </p>
            </div>

            <div style={panel}>
              <h4 style={{ margin: '0 0 8px', color: '#93c5fd' }}>손절가 · 확률</h4>
              {Object.entries(stock.stops).map(([k, s]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, padding: '2px 0' }}>
                  <span style={{ color: 'rgba(241,245,249,0.6)' }}>{k}</span>
                  <span style={{ color: '#f87171' }}>{fmt(s.price)}</span>
                </div>
              ))}
              <div style={{ height: 1, background: 'rgba(255,255,255,0.08)', margin: '8px 0' }} />
              {['continueUpPct', 'reachTargetPct', 'hitStopPct'].map(k => (
                stock.probability[k] != null && (
                  <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, padding: '2px 0' }}>
                    <span style={{ color: 'rgba(241,245,249,0.6)' }}>
                      {k === 'continueUpPct' ? '상승 지속' : k === 'reachTargetPct' ? '목표 선도달' : '손절 선이탈'}
                    </span>
                    <span>{String(stock.probability[k])}%</span>
                  </div>
                )
              ))}
              {stock.probability.sample != null && (
                <p style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>
                  표본 {String(stock.probability.sample)}건 빈도 기반
                </p>
              )}
            </div>
          </div>

          <div style={panel}>
            <h4 style={{ margin: '0 0 8px', color: '#93c5fd' }}>멀티 타임프레임 — {stock.mtf.alignment.summary}</h4>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {stock.mtf.timeframes.map(t => (
                <div key={t.label} style={{
                  flex: '1 1 160px', padding: '8px 10px', borderRadius: 8,
                  background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
                  fontSize: 12,
                }}>
                  <b style={{ color: '#a5b4fc' }}>{t.label}</b>
                  {t.error ? (
                    <p style={{ color: '#64748b', margin: '4px 0 0' }}>{t.error}</p>
                  ) : (
                    <>
                      <p style={{ margin: '4px 0 0', color: String(t.trend).includes('상승') ? '#34d399' : String(t.trend).includes('하락') ? '#f87171' : '#94a3b8' }}>
                        {t.trend}
                      </p>
                      <p style={{ margin: '2px 0 0', color: 'rgba(241,245,249,0.55)' }}>
                        RSI {t.rsi14} · {t.cdv?.direction}
                        {t.structureEvent ? ` · ${t.structureEvent.type}` : ''}
                      </p>
                    </>
                  )}
                </div>
              ))}
            </div>
          </div>

          {stock.aiReport && (
            <div style={panel}>
              <h4 style={{ margin: '0 0 4px', color: '#93c5fd' }}>
                AI 최종 리포트 <span style={{ fontSize: 11, color: '#475569' }}>{stock.aiProvider}</span>
              </h4>
              <Markdown text={stock.aiReport} />
            </div>
          )}
        </>
      )}

      <p style={{ fontSize: 11.5, color: '#475569', marginTop: 4 }}>
        모든 수치는 데이터 레이어가 계산하고 AI는 해석만 합니다 · 확률은 과거 빈도 기반 추정 — 투자 권유가 아닙니다
      </p>
    </div>
  )
}
