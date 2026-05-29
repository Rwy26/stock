import { useRef, useState } from 'react'
import { fetchJson } from '../lib/api'

// ─── Types ───────────────────────────────────────────────────────────────────

interface AiResult {
  symbol?: string
  timeframes?: string[]
  current_price?: string
  signal?: '매수' | '매도' | '관망'
  confidence?: number
  trend?: string
  summary?: string
  company_analysis?: {
    sector?: string
    key_products?: string
    current_position?: string
  }
  technical?: {
    trend_detail?: string
    ma_alignment?: string
    support_zones?: string[]
    resistance_zones?: string[]
    rsi?: string
    macd?: string
    bollinger?: string
    volume?: string
    patterns?: string
  }
  rise_reason?: {
    catalyst?: string
    sector_trend?: string
    news_factors?: string[]
  }
  targets?: {
    target_1?: string
    target_2?: string
    target_3?: string
    basis?: string
  }
  supply_demand?: {
    key_volume_zone?: string
    stop_loss_swing?: string
    stop_loss_short?: string
    risk_reward?: string
    entry_zone?: string
  }
  risks?: string[]
  outlook?: {
    short_term?: string
    mid_term?: string
  }
}

interface AnalysisResponse {
  symbol: string
  images_count?: number
  ai_result: AiResult
  analyzed_at: string
}

type TabKey = 'image' | 'symbol'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function signalColor(signal?: string) {
  if (signal === '매수') return '#22c55e'
  if (signal === '매도') return '#ef4444'
  return '#f59e0b'
}

function signalBg(signal?: string) {
  if (signal === '매수') return 'rgba(34,197,94,0.12)'
  if (signal === '매도') return 'rgba(239,68,68,0.12)'
  return 'rgba(245,158,11,0.12)'
}

function trendIcon(trend?: string) {
  if (!trend) return '—'
  if (trend.includes('상승')) return '▲ ' + trend
  if (trend.includes('하락')) return '▼ ' + trend
  return '→ ' + trend
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function SignalBadge({ result }: { result: AiResult }) {
  const color = signalColor(result.signal)
  const bg = signalBg(result.signal)
  return (
    <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', alignItems: 'center' }}>
      <div style={{
        padding: '0.5rem 1.4rem',
        borderRadius: '999px',
        background: bg,
        border: `1.5px solid ${color}`,
        color,
        fontWeight: 700,
        fontSize: '1.3rem',
        letterSpacing: '0.05em',
      }}>
        {result.signal ?? '—'}
      </div>
      <div style={{ color: 'var(--muted)', fontSize: '0.9rem' }}>
        확신도&nbsp;
        <span style={{ color: color, fontWeight: 700 }}>{result.confidence ?? '—'}%</span>
        &nbsp;·&nbsp;추세&nbsp;
        <span style={{ color: 'var(--fg)' }}>{trendIcon(result.trend)}</span>
      </div>
      {result.current_price && (
        <div style={{ color: 'var(--muted)', fontSize: '0.9rem' }}>
          현재가 <span style={{ color: 'var(--fg)', fontWeight: 600 }}>{result.current_price}</span>
        </div>
      )}
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="panel glass" style={{ marginBottom: '1rem' }}>
      <div className="panel-head" style={{ marginBottom: '0.75rem' }}>
        <h3>{title}</h3>
      </div>
      {children}
    </div>
  )
}

function Row({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null
  return (
    <div style={{ display: 'flex', gap: '0.75rem', padding: '0.4rem 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
      <span style={{ color: 'var(--muted)', minWidth: '110px', fontSize: '0.85rem', paddingTop: '0.1rem' }}>{label}</span>
      <span style={{ color: 'var(--fg)', fontSize: '0.9rem', lineHeight: 1.5 }}>{value}</span>
    </div>
  )
}

function PriceChip({ label, value, color }: { label: string; value?: string; color: string }) {
  if (!value) return null
  return (
    <div style={{
      background: `${color}18`,
      border: `1px solid ${color}55`,
      borderRadius: '8px',
      padding: '0.6rem 1rem',
      minWidth: '120px',
    }}>
      <div style={{ color: 'var(--muted)', fontSize: '0.75rem', marginBottom: '0.2rem' }}>{label}</div>
      <div style={{ color, fontWeight: 700, fontSize: '1rem' }}>{value}</div>
    </div>
  )
}

function ResultPanel({ data }: { data: AnalysisResponse }) {
  const r = data.ai_result
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
      {/* 헤더 */}
      <div className="panel glass" style={{ padding: '1.2rem 1.5rem', marginBottom: '0.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <div style={{ color: 'var(--muted)', fontSize: '0.8rem', marginBottom: '0.3rem' }}>
              {data.symbol}
              {r.company_analysis?.sector && <span> · {r.company_analysis.sector}</span>}
              {data.images_count != null && <span> · 이미지 {data.images_count}개 분석</span>}
            </div>
            <SignalBadge result={r} />
          </div>
          <div style={{ color: 'var(--muted)', fontSize: '0.75rem', textAlign: 'right' }}>
            분석 시각<br />
            {new Date(data.analyzed_at).toLocaleString('ko-KR')}
          </div>
        </div>

        {r.summary && (
          <div style={{
            marginTop: '1rem',
            padding: '0.9rem 1rem',
            background: 'rgba(255,255,255,0.04)',
            borderRadius: '8px',
            color: 'var(--fg)',
            fontSize: '0.92rem',
            lineHeight: 1.7,
            borderLeft: '3px solid var(--accent)',
          }}>
            {r.summary}
          </div>
        )}
      </div>

      {/* 목표가 / 손절가 */}
      {(r.targets || r.supply_demand) && (
        <Card title="📌 목표가 · 손절가">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem', marginBottom: r.targets?.basis ? '0.75rem' : 0 }}>
            <PriceChip label="1차 목표가" value={r.targets?.target_1} color="#22c55e" />
            <PriceChip label="2차 목표가" value={r.targets?.target_2} color="#86efac" />
            <PriceChip label="3차 목표가" value={r.targets?.target_3} color="#bbf7d0" />
            <PriceChip label="진입 구간" value={r.supply_demand?.entry_zone} color="#60a5fa" />
            <PriceChip label="스윙 손절" value={r.supply_demand?.stop_loss_swing} color="#f87171" />
            <PriceChip label="단기 손절" value={r.supply_demand?.stop_loss_short} color="#fca5a5" />
          </div>
          {r.targets?.basis && (
            <div style={{ color: 'var(--muted)', fontSize: '0.85rem', marginTop: '0.5rem' }}>
              근거: {r.targets.basis}
            </div>
          )}
          {r.supply_demand?.risk_reward && (
            <div style={{ color: 'var(--muted)', fontSize: '0.85rem', marginTop: '0.3rem' }}>
              리스크/리워드: <span style={{ color: 'var(--fg)' }}>{r.supply_demand.risk_reward}</span>
            </div>
          )}
        </Card>
      )}

      {/* 기업 분석 */}
      {r.company_analysis && (
        <Card title="🏢 기업 분석">
          <Row label="섹터" value={r.company_analysis.sector} />
          <Row label="핵심 제품" value={r.company_analysis.key_products} />
          <Row label="현재 평가" value={r.company_analysis.current_position} />
        </Card>
      )}

      {/* 기술적 분석 */}
      {r.technical && (
        <Card title="📊 기술적 분석">
          <Row label="추세" value={r.technical.trend_detail} />
          <Row label="이동평균" value={r.technical.ma_alignment} />
          <Row label="RSI" value={r.technical.rsi} />
          <Row label="MACD" value={r.technical.macd} />
          <Row label="볼린저밴드" value={r.technical.bollinger} />
          <Row label="거래량" value={r.technical.volume} />
          <Row label="패턴" value={r.technical.patterns} />
          {r.technical.support_zones && r.technical.support_zones.length > 0 && (
            <Row label="지지 구간" value={r.technical.support_zones.join(' / ')} />
          )}
          {r.technical.resistance_zones && r.technical.resistance_zones.length > 0 && (
            <Row label="저항 구간" value={r.technical.resistance_zones.join(' / ')} />
          )}
        </Card>
      )}

      {/* 상승 이유 */}
      {r.rise_reason && (
        <Card title="🚀 상승 이유 분석">
          <Row label="촉매" value={r.rise_reason.catalyst} />
          <Row label="섹터 트렌드" value={r.rise_reason.sector_trend} />
          {r.rise_reason.news_factors && r.rise_reason.news_factors.length > 0 && (
            <div style={{ padding: '0.4rem 0', display: 'flex', gap: '0.75rem' }}>
              <span style={{ color: 'var(--muted)', minWidth: '110px', fontSize: '0.85rem' }}>예상 이슈</span>
              <ul style={{ margin: 0, padding: '0 0 0 1rem', color: 'var(--fg)', fontSize: '0.9rem' }}>
                {r.rise_reason.news_factors.map((f, i) => <li key={i}>{f}</li>)}
              </ul>
            </div>
          )}
        </Card>
      )}

      {/* 수급 분석 */}
      {r.supply_demand && (
        <Card title="📦 수급 분석">
          <Row label="핵심 거래량 구간" value={r.supply_demand.key_volume_zone} />
        </Card>
      )}

      {/* 전망 */}
      {r.outlook && (
        <Card title="🔭 전망">
          <Row label="단기 (1~5일)" value={r.outlook.short_term} />
          <Row label="중기 (1~4주)" value={r.outlook.mid_term} />
        </Card>
      )}

      {/* 리스크 */}
      {r.risks && r.risks.length > 0 && (
        <Card title="⚠️ 리스크 요인">
          <ul style={{ margin: 0, padding: '0 0 0 1.2rem', color: 'var(--fg)', fontSize: '0.9rem', lineHeight: 2 }}>
            {r.risks.map((risk, i) => <li key={i}>{risk}</li>)}
          </ul>
        </Card>
      )}

      <p style={{ color: 'var(--muted)', fontSize: '0.75rem', textAlign: 'center', marginTop: '0.5rem' }}>
        ⚠️ AI 분석은 참고용입니다. 투자 결정의 책임은 본인에게 있습니다.
      </p>
    </div>
  )
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export function AiChartPage() {
  const [tab, setTab] = useState<TabKey>('image')

  // Image tab state
  const [symbol, setSymbol] = useState('')
  const [extraContext, setExtraContext] = useState('')
  const [images, setImages] = useState<File[]>([])
  const [previews, setPreviews] = useState<string[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Symbol tab state
  const [symCode, setSymCode] = useState('')
  const [period, setPeriod] = useState('6mo')
  const [interval, setInterval] = useState('1d')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AnalysisResponse | null>(null)

  // ── Image handlers ──────────────────────────────────────────────────────────

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []).slice(0, 6)
    setImages(files)
    const urls = files.map(f => URL.createObjectURL(f))
    setPreviews(prev => { prev.forEach(u => URL.revokeObjectURL(u)); return urls })
  }

  function removeImage(idx: number) {
    setImages(prev => prev.filter((_, i) => i !== idx))
    setPreviews(prev => {
      URL.revokeObjectURL(prev[idx])
      return prev.filter((_, i) => i !== idx)
    })
  }

  // ── Submit handlers ─────────────────────────────────────────────────────────

  async function submitImage(e: React.FormEvent) {
    e.preventDefault()
    if (!symbol.trim()) { setError('종목명을 입력하세요'); return }
    if (images.length === 0) { setError('차트 이미지를 1개 이상 업로드하세요'); return }

    setLoading(true); setError(null); setResult(null)
    try {
      const form = new FormData()
      images.forEach(f => form.append('files', f))

      const token = (await import('../lib/auth')).getAccessToken()
      const params = new URLSearchParams({ symbol: symbol.trim() })
      if (extraContext.trim()) params.set('extra_context', extraContext.trim())

      const resp = await fetch(`/api/ai/chart-analysis/image?${params}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      })
      const data = await resp.json()
      if (!resp.ok) throw new Error(data.detail ?? `서버 오류 ${resp.status}`)
      setResult(data as AnalysisResponse)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  async function submitSymbol(e: React.FormEvent) {
    e.preventDefault()
    if (!symCode.trim()) { setError('종목코드를 입력하세요'); return }

    setLoading(true); setError(null); setResult(null)
    try {
      const data = await fetchJson<AnalysisResponse>('/api/ai/chart-analysis', {
        method: 'POST',
        body: JSON.stringify({ symbol: symCode.trim(), period, interval }),
      })
      setResult(data)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <main className="bolinzer-shell">
      <header className="topbar glass">
        <div>
          <p className="top-label">AI CHART ANALYSIS</p>
          <h2>AI 차트 분석</h2>
          <p className="subtle">TradingView 차트 이미지 또는 종목코드로 AI 종합 분석</p>
        </div>
      </header>

      {/* 탭 */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
        <button
          type="button"
          onClick={() => { setTab('image'); setResult(null); setError(null) }}
          style={{
            padding: '0.55rem 1.4rem',
            borderRadius: '999px',
            border: tab === 'image' ? '1.5px solid var(--accent)' : '1px solid rgba(255,255,255,0.15)',
            background: tab === 'image' ? 'rgba(99,102,241,0.18)' : 'transparent',
            color: tab === 'image' ? 'var(--accent)' : 'var(--muted)',
            fontWeight: tab === 'image' ? 700 : 400,
            cursor: 'pointer',
            fontSize: '0.9rem',
          }}
        >
          📸 차트 이미지 분석
        </button>
        <button
          type="button"
          onClick={() => { setTab('symbol'); setResult(null); setError(null) }}
          style={{
            padding: '0.55rem 1.4rem',
            borderRadius: '999px',
            border: tab === 'symbol' ? '1.5px solid var(--accent)' : '1px solid rgba(255,255,255,0.15)',
            background: tab === 'symbol' ? 'rgba(99,102,241,0.18)' : 'transparent',
            color: tab === 'symbol' ? 'var(--accent)' : 'var(--muted)',
            fontWeight: tab === 'symbol' ? 700 : 400,
            cursor: 'pointer',
            fontSize: '0.9rem',
          }}
        >
          🔢 종목코드 분석
        </button>
      </div>

      {/* 이미지 분석 탭 */}
      {tab === 'image' && (
        <div className="panel glass reveal" style={{ marginBottom: '1rem' }}>
          <div className="panel-head"><h3>📸 TradingView 스크린샷 업로드</h3></div>

          <div style={{
            padding: '0.8rem 1rem',
            background: 'rgba(99,102,241,0.07)',
            borderRadius: '8px',
            marginBottom: '1.2rem',
            fontSize: '0.85rem',
            color: 'var(--muted)',
            lineHeight: 1.8,
          }}>
            <strong style={{ color: 'var(--fg)' }}>사용법:</strong><br />
            1. TradingView 차트 열기 → 상단 <strong style={{ color: 'var(--fg)' }}>📷 카메라 아이콘</strong> 클릭 → PNG 저장<br />
            2. 일봉 · 4시간봉 · 1시간봉 등 <strong style={{ color: 'var(--fg)' }}>여러 타임프레임을 각각 저장</strong>해서 함께 업로드<br />
            3. 종목명 입력 후 <strong style={{ color: 'var(--fg)' }}>분석 시작</strong> 클릭 (최대 6개)
          </div>

          <form onSubmit={submitImage}>
            <div className="settings-grid" style={{ marginBottom: '1rem' }}>
              <label>
                종목명 / 코드 <span style={{ color: '#ef4444' }}>*</span>
                <input
                  value={symbol}
                  onChange={e => setSymbol(e.target.value)}
                  placeholder="예: 삼성전기, 009150, AAPL"
                />
              </label>
              <label>
                추가 정보 (선택)
                <input
                  value={extraContext}
                  onChange={e => setExtraContext(e.target.value)}
                  placeholder="예: 현재 보유 중, 평단 1,800,000원"
                />
              </label>
            </div>

            {/* 드롭존 */}
            <div
              onClick={() => fileInputRef.current?.click()}
              style={{
                border: '2px dashed rgba(99,102,241,0.4)',
                borderRadius: '12px',
                padding: '2rem',
                textAlign: 'center',
                cursor: 'pointer',
                marginBottom: '1rem',
                background: 'rgba(99,102,241,0.04)',
                transition: 'border-color 0.2s',
              }}
            >
              <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>📂</div>
              <div style={{ color: 'var(--fg)', fontWeight: 600 }}>이미지 클릭하여 선택</div>
              <div style={{ color: 'var(--muted)', fontSize: '0.82rem', marginTop: '0.3rem' }}>
                PNG, JPG, WEBP · 최대 6개 · 파일당 10MB
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                multiple
                style={{ display: 'none' }}
                onChange={handleFileChange}
              />
            </div>

            {/* 미리보기 */}
            {previews.length > 0 && (
              <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
                {previews.map((url, i) => (
                  <div key={i} style={{ position: 'relative' }}>
                    <img
                      src={url}
                      alt={`차트 ${i + 1}`}
                      style={{
                        width: '160px',
                        height: '100px',
                        objectFit: 'cover',
                        borderRadius: '8px',
                        border: '1px solid rgba(255,255,255,0.15)',
                      }}
                    />
                    <div style={{ color: 'var(--muted)', fontSize: '0.72rem', textAlign: 'center', marginTop: '0.2rem' }}>
                      {images[i]?.name?.length > 20 ? images[i].name.slice(0, 18) + '…' : images[i]?.name}
                    </div>
                    <button
                      type="button"
                      onClick={() => removeImage(i)}
                      style={{
                        position: 'absolute',
                        top: '4px',
                        right: '4px',
                        background: 'rgba(0,0,0,0.65)',
                        border: 'none',
                        borderRadius: '50%',
                        color: '#fff',
                        width: '22px',
                        height: '22px',
                        cursor: 'pointer',
                        fontSize: '0.75rem',
                        lineHeight: '22px',
                        textAlign: 'center',
                      }}
                    >✕</button>
                  </div>
                ))}
              </div>
            )}

            <button className="btn" type="submit" disabled={loading} style={{ width: '100%', padding: '0.75rem' }}>
              {loading ? '🤖 AI가 차트를 분석 중입니다... (30~60초)' : '🚀 AI 분석 시작'}
            </button>
          </form>
        </div>
      )}

      {/* 종목코드 분석 탭 */}
      {tab === 'symbol' && (
        <div className="panel glass reveal" style={{ marginBottom: '1rem' }}>
          <div className="panel-head"><h3>🔢 종목코드로 자동 분석</h3></div>

          <div style={{
            padding: '0.8rem 1rem',
            background: 'rgba(99,102,241,0.07)',
            borderRadius: '8px',
            marginBottom: '1.2rem',
            fontSize: '0.85rem',
            color: 'var(--muted)',
            lineHeight: 1.8,
          }}>
            <strong style={{ color: 'var(--fg)' }}>사용법:</strong> 종목코드 입력하면 Yahoo Finance에서 자동으로 데이터를 가져와 분석합니다.<br />
            코스피: <code style={{ color: 'var(--fg)' }}>005930</code> · 코스닥: <code style={{ color: 'var(--fg)' }}>035720</code> · 미국: <code style={{ color: 'var(--fg)' }}>AAPL</code>
          </div>

          <form onSubmit={submitSymbol}>
            <div className="settings-grid" style={{ marginBottom: '1rem' }}>
              <label>
                종목코드 <span style={{ color: '#ef4444' }}>*</span>
                <input
                  value={symCode}
                  onChange={e => setSymCode(e.target.value)}
                  placeholder="예: 009150, 005930, AAPL"
                />
              </label>
              <label>
                조회 기간
                <select value={period} onChange={e => setPeriod(e.target.value)}>
                  <option value="1mo">1개월</option>
                  <option value="3mo">3개월</option>
                  <option value="6mo">6개월</option>
                  <option value="1y">1년</option>
                  <option value="2y">2년</option>
                </select>
              </label>
              <label>
                봉 단위
                <select value={interval} onChange={e => setInterval(e.target.value)}>
                  <option value="1d">일봉</option>
                  <option value="1wk">주봉</option>
                  <option value="1mo">월봉</option>
                </select>
              </label>
            </div>

            <button className="btn" type="submit" disabled={loading} style={{ width: '100%', padding: '0.75rem' }}>
              {loading ? '🤖 AI가 분석 중입니다... (30~60초)' : '🚀 AI 분석 시작'}
            </button>
          </form>
        </div>
      )}

      {/* 오류 메시지 */}
      {error && (
        <div style={{
          padding: '0.9rem 1rem',
          background: 'rgba(239,68,68,0.1)',
          border: '1px solid rgba(239,68,68,0.4)',
          borderRadius: '8px',
          color: '#fca5a5',
          marginBottom: '1rem',
          fontSize: '0.9rem',
        }}>
          ❌ {error}
        </div>
      )}

      {/* 분석 결과 */}
      {result && <ResultPanel data={result} />}
    </main>
  )
}
