import { useCallback, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchJson } from '../lib/api'
import { getAccessToken } from '../lib/auth'
import { getGuest } from '../lib/publicApi'
import { StockReportModal } from '../components/StockReportModal'

// ─── Types ───────────────────────────────────────────────────────────────────

interface AiResult {
  symbol?: string
  stock_name?: string
  code_in_chart?: string
  directive_response?: string
  current_price?: string
  signal?: '매수' | '매도' | '관망'
  confidence?: number
  rise_probability?: number
  fall_probability?: number
  valuation?: '저평가' | '적정' | '고평가'
  trend?: string
  summary?: string
  ict_analysis?: { order_block?: string; fvg?: string; liquidity?: string; market_structure?: string; zone?: string }
  company_analysis?: { sector?: string; key_products?: string; current_position?: string }
  technical?: {
    trend_detail?: string; ma_alignment?: string
    support_zones?: string[]; resistance_zones?: string[]
    rsi?: string; macd?: string; bollinger?: string; volume?: string; patterns?: string
  }
  catalysts?: { news_materials?: string; sector_expectation?: string; risk_factors?: string[] }
  rise_reason?: { catalyst?: string; sector_trend?: string; news_factors?: string[] }
  targets?: { entry_zone?: string; target_1?: string; target_2?: string; stop_loss?: string; risk_reward?: string; basis?: string; target_3?: string }
  supply_demand?: { key_volume_zone?: string; stop_loss_swing?: string; stop_loss_short?: string; risk_reward?: string; entry_zone?: string }
  risks?: string[]
  outlook?: { short_term?: string; mid_term?: string }
  data_needed?: string | null
}

interface CrossvalField { field: string; verdict: 'ok' | 'caution' | 'no'; note: string }
interface CrossvalDataNature {
  ok: boolean; kind?: string; rows?: number; count?: number
  columns?: string[]
  layers?: { price: string[]; meta: string[]; derived: string[] }
  date_range?: [string | null, string | null]
  timeframe_inferred?: string | null
  adjusted_price?: string
  crossval_usable_fields?: CrossvalField[]
  crossval_ready?: boolean
  crossval?: string
  blockers?: string[]
}
interface CrossvalIntake { stored: boolean; folder?: string; reason?: string; sha256?: string; timeframe?: string }
interface CrossvalExisting { found: boolean; file_count?: number; last_uploaded?: string; files?: string[] }
interface CrossvalTf { rows: number; first: string; last: string; files: number; added_this_run: number }
interface CrossvalMerge {
  ok: boolean; timeframes?: Record<string, CrossvalTf>
  total_rows?: number; file_count?: number; last_close?: number; last_data_at?: string; added_this_run?: number
}
interface CrossvalInfo {
  existing_data?: CrossvalExisting
  intake?: CrossvalIntake | CrossvalIntake[]
  data_nature?: CrossvalDataNature
  merge?: CrossvalMerge
  reference_only?: boolean
}

// 데이터 작업 요구 (요구 6)
interface WorkRequest {
  stock_code: string; stock_name?: string
  priority: 'high' | 'medium' | 'low'
  reason: string; total_rows: number; last_data_at?: string | null; suggested_action: string
}
interface WorkRequestsResp { watchlist_total: number; covered: number; request_count: number; requests: WorkRequest[] }

interface InflectionPoint { date: string; price: number; type: string; swing_pct: number }
interface AnalysisBasis {
  timeframe: string; bars: number; inflection_count: number; inflections?: InflectionPoint[]
  mtf_used?: boolean
  reference_signals?: { cvd?: string | null; smartmoney_zone?: string | null }
}
interface AnalysisResponse {
  symbol: string
  stock_name?: string
  codeVerified?: boolean
  identityNote?: string
  learningSamples?: { sufficient: boolean; bars: number; multiTimeframe: boolean; request: string }
  images_count?: number
  ai_result: AiResult
  analyzed_at: string
  crossval?: CrossvalInfo
  analysis_basis?: AnalysisBasis
}

// 언어학습 발전 가능성 (요구 4)
interface DevIdea { title: string; what: string; data_needed: string; feasibility: 'now' | 'soon' | 'later'; caution: string }
interface DevSuggestions { headline: string; readiness: string; ideas: DevIdea[]; next_actions: string[] }
interface DevResponse {
  corpus: { csv_count?: number; image_count?: number; symbol_count?: number; avg_verified_ratio?: number | null }
  suggestions: DevSuggestions
  provider: string; model: string
}

type DroppedFile = { file: File; previewUrl?: string; type: 'image' | 'csv' }
type Mode = 'drop' | 'code'

// 텍스트 추출 우선 인식 결과 (시장데이터 표·미인식 등)
interface ExEntity { type: 'stock' | 'sector'; name: string; code?: string | null; inWatchlist?: boolean; known?: boolean }
interface Extraction {
  content_type?: string
  confidence?: number
  extracted_summary?: string
  stocks?: { name?: string; code?: string | null; inWatchlist?: boolean; code_in_image?: string | null; sector?: string | null; context?: string }[]
  sectors?: { sector?: string; theme?: string; stocks?: string[]; known?: boolean }[]
  single_stock?: { name?: string | null; code_in_image?: string | null }
  user_intent?: string
  intent_response?: string
  entities?: ExEntity[]
  canonicalSectors?: string[]
  error?: string
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function extractSymbolFromFilename(name: string): string {
  // 코드 위치 한정: 파일명 '시작' 또는 '_' 바로 뒤의 6자리만 코드로 인정.
  // (예: "009150_2026-05-30.png" → 009150) — 끝에 붙는 타임스탬프
  // "...외인 기관 매수 163259.png"(16:32:59)를 코드로 오인하지 않기 위함.
  const code6 = name.match(/(?:^|_)(\d{6})(?:[_\-.]|$)/)
  if (code6) return code6[1]
  // 한글 종목명: 파일 시작의 한글 토큰 (TF·해시 앞까지). 예: "두산에너빌러티 60_95484.csv" → "두산에너빌러티"
  // 백엔드가 KRX/네이버로 코드·정식명 검증·교정함 (오타도 퍼지 매칭).
  const kr = name.match(/^([가-힣][가-힣A-Za-z0-9&·]+)/)
  if (kr) return kr[1]
  // AAPL_... 형태: 대문자 알파벳 2~5자
  const ticker = name.match(/^([A-Z]{2,5})[_\-\s,.]/)
  if (ticker) return ticker[1]
  return ''
}

function extractSymbolFromCsv(text: string): string {
  const lines = text.split('\n').filter(Boolean)
  if (!lines.length) return ''
  const combined = lines.slice(0, 3).join(' ')
  const code6 = combined.match(/\b(\d{6})\b/)
  if (code6) return code6[1]
  const ticker = combined.match(/\b([A-Z]{2,5})\b/)
  if (ticker) return ticker[1]
  return ''
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

function signalClass(signal?: string) {
  if (signal === '매수') return 'buy'
  if (signal === '매도') return 'sell'
  return 'hold'
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function DetailRow({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null
  return (
    <div className="ai-detail-row">
      <span className="ai-detail-label">{label}</span>
      <span className="ai-detail-val">{value}</span>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="panel glass reveal">
      <div className="panel-head"><h3>{title}</h3></div>
      {children}
    </div>
  )
}

// 교차검증 창구 적재 결과 + 데이터 성격 표시 (요구 1·2·3)
function CrossvalBadge({ info }: { info: CrossvalInfo }) {
  const intakes = Array.isArray(info.intake) ? info.intake : info.intake ? [info.intake] : []
  const stored = intakes.filter(x => x?.stored)
  const nat = info.data_nature
  const isCsv = nat?.kind === 'csv'
  const vColor = (v: string) => v === 'ok' ? '#22c55e' : v === 'caution' ? '#f59e0b' : '#94a3b8'
  const vLabel = (v: string) => v === 'ok' ? '검증가능' : v === 'caution' ? '주의' : '대상아님'
  return (
    <div className="panel glass" style={{ marginTop: 12, padding: '12px 14px', display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 700, color: 'var(--text-main)' }}>
        🗄️ 교차검증 창구 적재
        <span style={{ fontSize: '0.7rem', padding: '1px 8px', borderRadius: 999,
          background: 'rgba(148,163,184,0.18)', color: 'var(--text-soft)' }}>참고용 · 재가공 안 함</span>
      </div>
      <div style={{ fontSize: '0.8rem', color: 'var(--text-soft)', lineHeight: 1.6 }}>
        {stored.length > 0
          ? <>✅ {stored.length}건 적재됨 → <code>{stored[0].folder}</code>
              {!isCsv && <span> (수치 교차검증 불가 — 참고 증거 보관)</span>}</>
          : <>⚠️ 적재 안 됨{intakes[0]?.reason ? `: ${intakes[0].reason}` : ' (교차검증 드라이브 확인)'}</>}
      </div>

      {info.existing_data?.found && (
        <div style={{ fontSize: '0.78rem', color: '#60a5fa' }}>
          📁 과거 자료 {info.existing_data.file_count}건 발견 (최근 {info.existing_data.last_uploaded}) → 같은 종목 폴더에서 병합
        </div>
      )}
      {info.merge?.ok && (
        <div style={{ fontSize: '0.78rem', color: 'var(--text-soft)', lineHeight: 1.6 }}>
          🔗 병합·업데이트: 총 <strong style={{ color: 'var(--text-main)' }}>{info.merge.total_rows?.toLocaleString()}봉</strong>
          {(info.merge.added_this_run ?? 0) > 0 && <span style={{ color: '#22c55e' }}> (이번 +{info.merge.added_this_run?.toLocaleString()})</span>}
          {' · '}TF {Object.keys(info.merge.timeframes ?? {}).join(', ') || '—'}
          {info.merge.last_close != null && <> · 최신종가 {info.merge.last_close.toLocaleString()}원</>}
          <span style={{ marginLeft: 6, opacity: 0.7 }}>· 인덱스/노드 DB 갱신됨</span>
        </div>
      )}

      {isCsv && nat && (
        <>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-soft)' }}>
            {nat.rows}행 · {nat.timeframe_inferred ?? '?'} · {nat.date_range?.[0] ?? '?'}~{nat.date_range?.[1] ?? '?'}
            <span style={{ marginLeft: 8, color: nat.crossval_ready ? '#22c55e' : '#f59e0b' }}>
              {nat.crossval_ready ? '교차검증 준비됨' : '교차검증 보류'}
            </span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {(nat.crossval_usable_fields ?? []).map((f, i) => (
              <span key={i} title={f.note} style={{ fontSize: '0.72rem', padding: '2px 8px', borderRadius: 999,
                background: vColor(f.verdict) + '1f', color: vColor(f.verdict), border: `1px solid ${vColor(f.verdict)}44` }}>
                {f.field} · {vLabel(f.verdict)}
              </span>
            ))}
          </div>
          {nat.layers && (
            <div style={{ fontSize: '0.74rem', color: 'var(--text-soft)', opacity: 0.9 }}>
              가격층 [{nat.layers.price.join(', ') || '—'}] · 파생층 [{nat.layers.derived.join(', ') || '—'}]
            </div>
          )}
          {nat.adjusted_price && (
            <div style={{ fontSize: '0.74rem', color: '#fbbf24', opacity: 0.9 }}>⚠ {nat.adjusted_price}</div>
          )}
          {(nat.blockers?.length ?? 0) > 0 && (
            <div style={{ fontSize: '0.74rem', color: '#f87171' }}>보류 사유: {nat.blockers!.join(' · ')}</div>
          )}
        </>
      )}
      {!isCsv && nat?.crossval && (
        <div style={{ fontSize: '0.78rem', color: 'var(--text-soft)' }}>{nat.crossval}</div>
      )}
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="ai-loading-state">
      <div className="panel glass" style={{ padding: '1.4rem 1.5rem' }}>
        <div className="ai-loading-bar short" style={{ marginBottom: '12px' }} />
        <div className="ai-loading-bar xlarge" />
        <div className="ai-loading-bar medium" style={{ marginTop: '12px' }} />
      </div>
      <div className="panel glass" style={{ padding: '1.4rem 1.5rem' }}>
        <div className="ai-loading-bar medium" style={{ marginBottom: '12px' }} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: '8px' }}>
          {[...Array(6)].map((_, i) => (
            <div key={i} className="ai-loading-bar" style={{ height: '60px' }} />
          ))}
        </div>
      </div>
      <div className="panel glass" style={{ padding: '1.4rem 1.5rem' }}>
        <div className="ai-loading-bar medium" style={{ marginBottom: '10px' }} />
        {[...Array(4)].map((_, i) => <div key={i} className="ai-loading-bar long" style={{ marginBottom: '8px' }} />)}
      </div>
    </div>
  )
}

// ─── One-pager Report Generator ──────────────────────────────────────────────

function buildReportHtml(data: AnalysisResponse, images: string[]): string {
  const r = data.ai_result
  const date = new Date(data.analyzed_at).toLocaleString('ko-KR')
  const signal = r.signal ?? '—'
  const signalColor = signal === '매수' ? '#16a34a' : signal === '매도' ? '#dc2626' : '#d97706'
  const valColor = r.valuation === '저평가' ? '#16a34a' : r.valuation === '고평가' ? '#dc2626' : '#2563eb'

  const row = (label: string, val?: string | null) =>
    val ? `<tr><td class="lbl">${label}</td><td>${val}</td></tr>` : ''

  const imgHtml = images.length
    ? `<div class="img-row">${images.map(src =>
        `<img src="${src}" alt="chart" />`).join('')}</div>`
    : ''

  const targetsHtml = (r.targets || r.supply_demand) ? `
  <div class="section">
    <div class="sec-title">📌 목표가 · 진입 · 손절</div>
    <div class="price-grid">
      ${r.targets?.entry_zone || r.supply_demand?.entry_zone ? `<div class="pc entry"><div class="pc-l">진입 구간</div><div class="pc-v">${r.targets?.entry_zone ?? r.supply_demand?.entry_zone}</div></div>` : ''}
      ${r.targets?.target_1 ? `<div class="pc t1"><div class="pc-l">1차 목표가</div><div class="pc-v">${r.targets.target_1}</div></div>` : ''}
      ${r.targets?.target_2 ? `<div class="pc t2"><div class="pc-l">2차 목표가</div><div class="pc-v">${r.targets.target_2}</div></div>` : ''}
      ${r.targets?.target_3 ? `<div class="pc t3"><div class="pc-l">3차 목표가</div><div class="pc-v">${r.targets.target_3}</div></div>` : ''}
      ${r.targets?.stop_loss || r.supply_demand?.stop_loss_swing ? `<div class="pc stop"><div class="pc-l">⚠️ 손절</div><div class="pc-v">${r.targets?.stop_loss ?? r.supply_demand?.stop_loss_swing}</div></div>` : ''}
      ${r.targets?.risk_reward || r.supply_demand?.risk_reward ? `<div class="pc rr"><div class="pc-l">R/R</div><div class="pc-v">${r.targets?.risk_reward ?? r.supply_demand?.risk_reward}</div></div>` : ''}
    </div>
    ${r.targets?.basis ? `<p class="basis">📎 ${r.targets.basis}</p>` : ''}
  </div>` : ''

  const ictHtml = r.ict_analysis ? `
  <div class="section">
    <div class="sec-title">🧠 ICT 스마트머니</div>
    <table>${row('Order Block', r.ict_analysis.order_block)}${row('FVG', r.ict_analysis.fvg)}${row('유동성', r.ict_analysis.liquidity)}${row('시장 구조', r.ict_analysis.market_structure)}${row('Zone', r.ict_analysis.zone)}</table>
  </div>` : ''

  const techHtml = r.technical ? `
  <div class="section">
    <div class="sec-title">📊 기술적 분석</div>
    <table>${row('추세', r.technical.trend_detail)}${row('이동평균', r.technical.ma_alignment)}${row('RSI', r.technical.rsi)}${row('MACD', r.technical.macd)}${row('볼린저', r.technical.bollinger)}${row('거래량', r.technical.volume)}${row('패턴', r.technical.patterns)}${row('지지', r.technical.support_zones?.join(' / '))}${row('저항', r.technical.resistance_zones?.join(' / '))}</table>
  </div>` : ''

  const catalystsHtml = r.catalysts ? `
  <div class="section">
    <div class="sec-title">📈 상승 재료</div>
    <table>${row('뉴스/공시', r.catalysts.news_materials)}${row('섹터 기대감', r.catalysts.sector_expectation)}${r.catalysts.risk_factors?.length ? `<tr><td class="lbl">리스크</td><td>${r.catalysts.risk_factors.map(f => `• ${f}`).join('<br>')}</td></tr>` : ''}</table>
  </div>` : ''

  const companyHtml = r.company_analysis ? `
  <div class="section">
    <div class="sec-title">🏢 기업 분석</div>
    <table>${row('섹터', r.company_analysis.sector)}${row('핵심 제품', r.company_analysis.key_products)}${row('평가', r.company_analysis.current_position)}</table>
  </div>` : ''

  const outlookHtml = r.outlook ? `
  <div class="section">
    <div class="sec-title">🔭 전망</div>
    <table>${row('단기 (1~5일)', r.outlook.short_term)}${row('중기 (1~4주)', r.outlook.mid_term)}</table>
  </div>` : ''

  const risksHtml = r.risks?.length ? `
  <div class="section">
    <div class="sec-title">⚠️ 리스크</div>
    <ul>${r.risks.map(rk => `<li>${rk}</li>`).join('')}</ul>
  </div>` : ''

  return `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>${data.symbol} AI 분석 보고서 ${date.slice(0, 10)}</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', -apple-system, sans-serif; font-size: 13px; background: #f8fafc; color: #1e293b; padding: 24px; line-height: 1.55; }
  .page { max-width: 900px; margin: 0 auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,.1); overflow: hidden; }
  /* Header */
  .header { background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); color: #fff; padding: 20px 28px; display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
  .h-left h1 { font-size: 1.5rem; font-weight: 700; letter-spacing: .02em; }
  .h-left .sub { font-size: 0.8rem; color: #94a3b8; margin-top: 4px; }
  .signal-pill { display: inline-block; padding: 6px 18px; border-radius: 20px; font-size: 1.1rem; font-weight: 700; background: ${signalColor}22; border: 2px solid ${signalColor}; color: ${signalColor}; }
  .h-right { text-align: right; }
  .conf-bar { width: 120px; height: 8px; background: rgba(255,255,255,.15); border-radius: 4px; margin-top: 6px; overflow: hidden; }
  .conf-fill { height: 100%; background: ${signalColor}; border-radius: 4px; width: ${r.confidence ?? 0}%; }
  /* Prob chips */
  .prob-row { display: flex; gap: 8px; padding: 12px 28px; background: #f1f5f9; flex-wrap: wrap; align-items: center; }
  .chip { padding: 4px 12px; border-radius: 20px; font-size: 0.82rem; font-weight: 600; }
  .chip.up   { background: #dcfce7; color: #16a34a; border: 1px solid #86efac; }
  .chip.down { background: #fee2e2; color: #dc2626; border: 1px solid #fca5a5; }
  .chip.val  { background: #dbeafe; color: ${valColor}; border: 1px solid #93c5fd; }
  .summary { padding: 14px 28px; font-size: 0.9rem; color: #334155; background: #f8fafc; border-bottom: 1px solid #e2e8f0; }
  /* Images */
  .img-row { display: flex; gap: 8px; padding: 16px 28px; flex-wrap: wrap; background: #0f172a; }
  .img-row img { flex: 1; min-width: 0; max-height: 220px; object-fit: contain; border-radius: 6px; border: 1px solid #334155; }
  /* Body */
  .body { padding: 16px 28px; display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .body .full { grid-column: 1 / -1; }
  .section { border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }
  .sec-title { background: #f1f5f9; padding: 7px 12px; font-weight: 700; font-size: 0.82rem; color: #475569; border-bottom: 1px solid #e2e8f0; }
  table { width: 100%; border-collapse: collapse; }
  table tr { border-bottom: 1px solid #f1f5f9; }
  table tr:last-child { border-bottom: none; }
  td { padding: 5px 10px; font-size: 0.8rem; vertical-align: top; }
  td.lbl { white-space: nowrap; font-weight: 600; color: #64748b; width: 90px; }
  /* Price grid */
  .price-grid { display: flex; flex-wrap: wrap; gap: 8px; padding: 10px 12px; }
  .pc { padding: 6px 12px; border-radius: 6px; text-align: center; min-width: 90px; }
  .pc-l { font-size: 0.68rem; color: #64748b; font-weight: 600; margin-bottom: 2px; }
  .pc-v { font-size: 0.92rem; font-weight: 700; }
  .pc.entry { background: #f0fdf4; border: 1px solid #86efac; color: #16a34a; }
  .pc.t1    { background: #eff6ff; border: 1px solid #93c5fd; color: #2563eb; }
  .pc.t2    { background: #eff6ff; border: 1px solid #6ea8fe; color: #1d4ed8; }
  .pc.t3    { background: #eef2ff; border: 1px solid #a5b4fc; color: #4338ca; }
  .pc.stop  { background: #fef2f2; border: 1px solid #fca5a5; color: #dc2626; }
  .pc.rr    { background: #faf5ff; border: 1px solid #d8b4fe; color: #7c3aed; }
  .basis { font-size: 0.75rem; color: #64748b; padding: 4px 12px 10px; }
  ul { padding: 8px 12px 8px 24px; }
  li { font-size: 0.8rem; margin-bottom: 3px; }
  /* Footer */
  .footer { padding: 10px 28px; text-align: center; font-size: 0.72rem; color: #94a3b8; border-top: 1px solid #e2e8f0; background: #f8fafc; }
  @media print {
    body { padding: 0; background: #fff; }
    .page { box-shadow: none; border-radius: 0; }
    @page { margin: 10mm; size: A4; }
  }
</style>
</head>
<body>
<div class="page">
  <div class="header">
    <div class="h-left">
      <h1>${data.symbol} <span style="font-weight:400;font-size:1rem;color:#94a3b8">${r.company_analysis?.sector ?? ''}</span></h1>
      <div class="sub">AI 종목 분석 보고서 · ${date}${data.images_count ? ` · ${data.images_count}개 이미지 분석` : ''}</div>
    </div>
    <div class="h-right">
      <div class="signal-pill">${signal}</div>
      <div class="conf-bar"><div class="conf-fill"></div></div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-top:4px">확신도 ${r.confidence ?? '—'}%</div>
    </div>
  </div>

  ${(r.rise_probability != null || r.fall_probability != null || r.valuation) ? `
  <div class="prob-row">
    ${r.rise_probability != null ? `<span class="chip up">▲ 상승 ${r.rise_probability}%</span>` : ''}
    ${r.fall_probability != null ? `<span class="chip down">▼ 하락 ${r.fall_probability}%</span>` : ''}
    ${r.valuation ? `<span class="chip val">${r.valuation === '저평가' ? '💹' : r.valuation === '고평가' ? '📈' : '⚖️'} ${r.valuation}</span>` : ''}
    ${r.targets?.risk_reward || r.supply_demand?.risk_reward ? `<span class="chip val" style="background:#faf5ff;border-color:#d8b4fe;color:#7c3aed">R/R ${r.targets?.risk_reward ?? r.supply_demand?.risk_reward}</span>` : ''}
  </div>` : ''}

  ${r.summary ? `<div class="summary">💡 ${r.summary}</div>` : ''}

  ${imgHtml}

  <div class="body">
    ${targetsHtml ? `<div class="full">${targetsHtml}</div>` : ''}
    ${ictHtml}${techHtml}
    ${catalystsHtml}${companyHtml}
    ${outlookHtml}
    ${risksHtml ? `<div class="full">${risksHtml}</div>` : ''}
    ${r.data_needed ? `<div class="full"><div class="section"><div class="sec-title">ℹ️ 추가 정보 요청</div><div style="padding:8px 12px;font-size:0.8rem;color:#92400e">📌 ${r.data_needed}</div></div></div>` : ''}
  </div>

  <div class="footer">⚠️ 본 보고서는 AI가 생성한 참고 자료입니다. 투자 결정의 책임은 본인에게 있습니다. · MOON STOCK</div>
</div>
<script>
  // Auto open print dialog when loaded with ?print=1
  if (location.search.includes('print=1')) { window.addEventListener('load', () => window.print()) }
</script>
</body>
</html>`
}

// 추출 텍스트 안의 관심종목·정식섹터 이름을 파란 클릭 링크로 변환
function linkifyEntities(
  text: string, entities: ExEntity[],
  onStock: (code: string, name: string) => void, onSector: (name: string) => void,
): React.ReactNode[] {
  const links = entities.filter(e =>
    (e.type === 'stock' && e.inWatchlist && e.code) || (e.type === 'sector' && e.known))
  if (!links.length) return [text]
  // 긴 이름 우선 (부분 겹침 방지)
  const sorted = [...links].sort((a, b) => b.name.length - a.name.length)
  const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const re = new RegExp(`(${sorted.map(e => esc(e.name)).join('|')})`, 'g')
  const out: React.ReactNode[] = []
  let key = 0
  text.split(re).forEach(seg => {
    const ent = links.find(e => e.name === seg)
    if (ent) {
      out.push(
        <span key={key++} onClick={() => ent.type === 'stock' ? onStock(ent.code!, ent.name) : onSector(ent.name)}
          style={{ color: '#60a5fa', cursor: 'pointer', fontWeight: 700, textDecoration: 'underline' }}
          title={ent.type === 'stock' ? '리포트 보기' : '섹터 나침반으로 이동'}>
          {seg}
        </span>,
      )
    } else if (seg) {
      out.push(<span key={key++}>{seg}</span>)
    }
  })
  return out
}

// 시장데이터 표 · 미인식 결과 — 단일종목 리포트(관망/목표가) 대신 추출 내용·의도 응답만 표시
function DocView({ mode, ex, onOpenReport, publicMode }: {
  mode: string; ex: Extraction; onOpenReport: (code: string, name: string) => void; publicMode?: boolean
}) {
  const navigate = useNavigate()
  const isUnrec = mode === 'unrecognized'
  const onSector = (_name: string) => navigate('/sector-rotation')
  const link = (t?: string) => t ? linkifyEntities(t, ex.entities ?? [], onOpenReport, onSector) : null
  // 편입 대상: 관심종목에 아직 없는 종목들
  const newStocks = (ex.stocks ?? []).filter(s => s.name && !s.inWatchlist)
  const [inducting, setInducting] = useState(false)
  const [inductMsg, setInductMsg] = useState<string | null>(null)
  async function induct() {
    setInducting(true); setInductMsg(null)
    try {
      const token = getAccessToken()
      const resp = await fetch('/api/ai/extract/induct', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ stocks: newStocks.map(s => ({ name: s.name, code: s.code })) }),
      })
      const d = await resp.json()
      if (!resp.ok) throw new Error(d.detail ?? `오류 ${resp.status}`)
      const added = (d.results ?? []).filter((r: { status: string }) => r.status === 'added')
      const excluded = (d.results ?? []).filter((r: { status: string }) => r.status === 'excluded')
      setInductMsg(`편입 ${added.length}건 (리포트 생성 중) · 제외 ${excluded.length}건 · 이미보유/미확인 ${(d.results?.length ?? 0) - added.length - excluded.length}건`)
    } catch (e) {
      setInductMsg(`편입 실패: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setInducting(false)
    }
  }
  return (
    <div className="ai-right">
      <div className="panel glass" style={{
        padding: '14px 16px', marginBottom: 12,
        border: `1px solid ${isUnrec ? 'rgba(239,68,68,0.4)' : 'rgba(96,165,250,0.35)'}`,
        background: isUnrec ? 'rgba(239,68,68,0.08)' : 'rgba(96,165,250,0.06)',
      }}>
        <div style={{ fontSize: '1rem', fontWeight: 800, color: isUnrec ? '#fca5a5' : '#93c5fd' }}>
          {isUnrec
            ? '⚠️ 종목 미인식 — 분석 결과를 생성하지 않았습니다'
            : '📊 시장데이터 인식 — 단일 종목 차트가 아닙니다'}
        </div>
        <div style={{ fontSize: '0.82rem', color: 'var(--text-soft)', marginTop: 6, lineHeight: 1.6 }}>
          {isUnrec
            ? '이미지에서 분석 가능한 단일 종목 차트를 식별하지 못했습니다. 아래 추출 내용을 확인하고, 종목 차트라면 종목코드를 입력해 다시 시도하세요. 잘못된 종목 리포트를 만드는 대신 인식 결과만 보고합니다.'
            : '여러 종목·섹터가 포함된 시장 데이터(순매수·시황 등)로 인식되어, 가짜 종목 리포트 대신 추출·분류 결과를 제공합니다.'}
        </div>
      </div>

      {ex.extracted_summary && (
        <Section title="📝 추출 내용 (이미지에서 읽은 텍스트)">
          <div className="ai-summary-box" style={{ lineHeight: 1.7 }}>{link(ex.extracted_summary)}</div>
          <p className="hint" style={{ marginTop: 6 }}>※ <span style={{ color: '#60a5fa', fontWeight: 700 }}>파란 종목/섹터</span>는 관심종목·정식섹터 — 눌러서 리포트·나침반으로 이동</p>
        </Section>
      )}

      {ex.intent_response && (
        <Section title="💬 지시 수행 결과">
          <div className="ai-summary-box" style={{ borderLeft: '3px solid #a78bfa', background: 'rgba(167,139,250,0.08)', lineHeight: 1.7 }}>
            {ex.user_intent && <div style={{ fontSize: '0.74rem', color: '#a78bfa', marginBottom: 6 }}>요청: {ex.user_intent}</div>}
            {link(ex.intent_response)}
          </div>
        </Section>
      )}

      {newStocks.length > 0 && !publicMode && (
        <Section title="➕ 신규 종목 관심종목 편입">
          <p className="hint" style={{ marginBottom: 8 }}>
            관심종목에 없는 {newStocks.length}개 종목: {newStocks.map(s => s.name).join(', ')}
            <br />편입 시 제외원칙 필터를 통과한 종목만 등록되고, 엔진·LLM 리포트가 생성됩니다.
          </p>
          <button type="button" className="ai-export-btn" disabled={inducting} onClick={induct}
            style={{ opacity: inducting ? 0.6 : 1 }}>
            {inducting ? '편입 중…' : `➕ ${newStocks.length}개 종목 편입 + 리포트 생성`}
          </button>
          {inductMsg && <p className="hint" style={{ marginTop: 8, color: '#34d399' }}>{inductMsg}</p>}
        </Section>
      )}

      {Array.isArray(ex.sectors) && ex.sectors.length > 0 && (
        <Section title="🗂️ 섹터 분류">
          <div style={{ display: 'grid', gap: 8 }}>
            {ex.sectors.map((s, i) => (
              <div key={i} className="ai-summary-box" style={{ padding: '8px 12px' }}>
                {s.known
                  ? <b onClick={() => onSector(s.sector!)} style={{ color: '#60a5fa', cursor: 'pointer', textDecoration: 'underline' }} title="섹터 나침반으로 이동">{s.sector}</b>
                  : <b style={{ color: '#93c5fd' }}>{s.sector}</b>}
                {s.theme && <span style={{ color: 'var(--text-soft)', fontSize: '0.78rem' }}> · {s.theme}</span>}
                <div style={{ fontSize: '0.84rem', marginTop: 4 }}>{link((s.stocks ?? []).join(', ')) }</div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {Array.isArray(ex.stocks) && ex.stocks.length > 0 && (
        <Section title="📋 등장 종목">
          <div style={{ display: 'grid', gap: 4 }}>
            {ex.stocks.map((s, i) => (
              <div key={i} style={{ fontSize: '0.84rem', display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                {s.inWatchlist && s.code
                  ? <b onClick={() => onOpenReport(s.code!, s.name!)} style={{ color: '#60a5fa', cursor: 'pointer', textDecoration: 'underline' }} title="리포트 보기">{s.name}</b>
                  : <b>{s.name}</b>}
                {s.inWatchlist && <span style={{ fontSize: '0.68rem', color: '#34d399', border: '1px solid rgba(52,211,153,0.4)', borderRadius: 4, padding: '0 4px' }}>관심</span>}
                {s.sector && <span style={{ color: '#60a5fa' }}>{s.sector}</span>}
                {s.context && <span style={{ color: 'var(--text-soft)' }}>· {s.context}</span>}
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  )
}

function ResultView({ data, onExport }: { data: AnalysisResponse; onExport?: () => void }) {
  const r = data.ai_result
  const cls = signalClass(r.signal)

  // 종목명 우선순위: 백엔드 주입(검증된 stocks/FDR) → AI가 차트에서 읽은 이름(숫자코드 제외)
  const aiReadName = r.symbol && !/^\d{6}$/.test(r.symbol.trim()) && r.symbol.trim() !== data.symbol
    ? r.symbol.trim() : null
  const stockName = data.stock_name ?? r.stock_name ?? aiReadName
  const verifiedCode = data.codeVerified !== false  // 검증된 경우에만 코드/로고 신뢰
  const logoUrl = verifiedCode && /^\d{6}$/.test(data.symbol)
    ? `https://file.alphasquare.co.kr/media/images/stock_logo/kr/${data.symbol}.png`
    : null

  return (
    <div className="ai-right">
      {/* ── 종목 식별 미검증 경고 (데이터 정확성: 가짜 코드 사실화 금지) ── */}
      {data.codeVerified === false && (
        <div style={{
          margin: '0 0 12px', padding: '10px 14px', borderRadius: 8,
          background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.4)',
          color: '#fca5a5', fontSize: '0.82rem', lineHeight: 1.5,
        }}>
          ⚠️ <b>종목 식별 미검증</b> — {data.identityNote ?? '코드·종목명을 KRX 상장목록에서 확인하지 못했습니다. 직접 확인하세요.'}
        </div>
      )}
      {/* ── 종목 헤더: 로고 + 이름(크게) + 코드(작게) ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12,
        margin: '0 0 14px', textAlign: 'center',
      }}>
        {logoUrl && (
          <img
            src={logoUrl}
            alt=""
            onError={e => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
            style={{ width: 40, height: 40, borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }}
          />
        )}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span style={{ fontSize: 30, fontWeight: 900, color: 'var(--text, #f1f5f9)', lineHeight: 1 }}>
            {stockName ?? data.symbol}
          </span>
          {stockName && verifiedCode && (
            <span style={{ fontSize: 14, color: 'var(--text-soft, #94a3b8)' }}>{data.symbol}</span>
          )}
          {!verifiedCode && (
            <span style={{ fontSize: 13, color: '#fca5a5' }}>코드 미확인</span>
          )}
        </div>
      </div>

      <div className={`ai-signal-card ${cls} reveal`}>
        <div className="ai-signal-top">
          <div className="ai-signal-badge">
            <span className={`ai-signal-pill ${cls}`}>{r.signal ?? '—'}</span>
            <div className="ai-confidence-bar-wrap">
              <div className="ai-confidence-label">확신도 {r.confidence ?? '—'}%</div>
              <div className="ai-confidence-bar-bg">
                <div className={`ai-confidence-bar-fill ${cls}`} style={{ width: `${r.confidence ?? 0}%` }} />
              </div>
            </div>
          </div>
          <div style={{ textAlign: 'right', fontSize: '0.78rem', color: 'var(--text-soft)' }}>
            <div>{data.symbol}{r.company_analysis?.sector ? ` · ${r.company_analysis.sector}` : ''}{r.ict_analysis?.zone ? ` · ${r.ict_analysis.zone}` : ''}</div>
            {data.images_count != null && <div>{data.images_count}개 이미지 분석</div>}
            <div>{new Date(data.analyzed_at).toLocaleString('ko-KR')}</div>
            {onExport && (
              <button type="button" className="ai-export-btn" onClick={onExport} title="원페이퍼 보고서 내보내기">
                📄 내보내기
              </button>
            )}
          </div>
        </div>

        {/* 상승/하락 확률 + 평가 */}
        {(r.rise_probability != null || r.fall_probability != null || r.valuation) && (
          <div className="ai-prob-row">
            {r.rise_probability != null && (
              <span className="ai-prob-chip up">▲ 상승 {r.rise_probability}%</span>
            )}
            {r.fall_probability != null && (
              <span className="ai-prob-chip down">▼ 하락 {r.fall_probability}%</span>
            )}
            {r.valuation && (
              <span className={`ai-prob-chip val-${r.valuation === '저평가' ? 'under' : r.valuation === '고평가' ? 'over' : 'fair'}`}>
                {r.valuation === '저평가' ? '💹' : r.valuation === '고평가' ? '📈' : '⚖️'} {r.valuation}
              </span>
            )}
          </div>
        )}

        <div className="ai-signal-meta">
          {r.trend && (
            <span className="ai-meta-chip">
              추세&nbsp;<span className="ai-meta-val">
                {r.trend.includes('상승') ? '▲' : r.trend.includes('하락') ? '▼' : '→'} {r.trend}
              </span>
            </span>
          )}
          {r.current_price && (
            <span className="ai-meta-chip">현재가&nbsp;<span className="ai-meta-val">{r.current_price}</span></span>
          )}
          {(r.targets?.risk_reward || r.supply_demand?.risk_reward) && (
            <span className="ai-meta-chip">R/R&nbsp;<span className="ai-meta-val">{r.targets?.risk_reward ?? r.supply_demand?.risk_reward}</span></span>
          )}
        </div>
        {r.summary && <div className="ai-summary-box">{r.summary}</div>}
        {r.directive_response && (
          <div className="ai-summary-box" style={{
            marginTop: '0.6rem', borderLeft: '3px solid #a78bfa',
            background: 'rgba(167,139,250,0.08)',
          }}>
            <div style={{ fontSize: '0.72rem', color: '#a78bfa', fontWeight: 700, marginBottom: 4 }}>
              💬 지시 수행 결과
            </div>
            {r.directive_response}
          </div>
        )}
      </div>

      {(r.targets || r.supply_demand) && (
        <Section title="📌 목표가 · 진입 · 손절">
          <div className="ai-price-grid">
            {(r.targets?.entry_zone || r.supply_demand?.entry_zone) && <div className="ai-price-chip entry"><span className="ai-price-label">진입 구간</span><span className="ai-price-val">{r.targets?.entry_zone ?? r.supply_demand?.entry_zone}</span></div>}
            {r.targets?.target_1 && <div className="ai-price-chip buy-1"><span className="ai-price-label">1차 목표가</span><span className="ai-price-val">{r.targets.target_1}</span></div>}
            {r.targets?.target_2 && <div className="ai-price-chip buy-2"><span className="ai-price-label">2차 목표가</span><span className="ai-price-val">{r.targets.target_2}</span></div>}
            {r.targets?.target_3 && <div className="ai-price-chip buy-3"><span className="ai-price-label">3차 목표가</span><span className="ai-price-val">{r.targets.target_3}</span></div>}
            {(r.targets?.stop_loss || r.supply_demand?.stop_loss_swing) && <div className="ai-price-chip stop1"><span className="ai-price-label">⚠️ 손절 마지노선</span><span className="ai-price-val">{r.targets?.stop_loss ?? r.supply_demand?.stop_loss_swing}</span></div>}
            {r.supply_demand?.stop_loss_short && <div className="ai-price-chip stop2"><span className="ai-price-label">단기 손절</span><span className="ai-price-val">{r.supply_demand.stop_loss_short}</span></div>}
          </div>
          {r.targets?.basis && <p className="hint" style={{ marginTop: '0.6rem' }}>📎 {r.targets.basis}</p>}
        </Section>
      )}

      {r.ict_analysis && (
        <Section title="🧠 ICT 스마트머니 분석">
          <DetailRow label="Order Block" value={r.ict_analysis.order_block} />
          <DetailRow label="FVG / Imbalance" value={r.ict_analysis.fvg} />
          <DetailRow label="유동성 청산" value={r.ict_analysis.liquidity} />
          <DetailRow label="시장 구조" value={r.ict_analysis.market_structure} />
          <DetailRow label="Zone" value={r.ict_analysis.zone} />
        </Section>
      )}

      {r.technical && (
        <Section title="📊 기술적 분석">
          <DetailRow label="추세" value={r.technical.trend_detail} />
          <DetailRow label="이동평균" value={r.technical.ma_alignment} />
          <DetailRow label="RSI" value={r.technical.rsi} />
          <DetailRow label="MACD" value={r.technical.macd} />
          <DetailRow label="볼린저밴드" value={r.technical.bollinger} />
          <DetailRow label="거래량" value={r.technical.volume} />
          <DetailRow label="패턴" value={r.technical.patterns} />
          {r.technical.support_zones?.length ? <DetailRow label="지지 구간" value={r.technical.support_zones.join(' / ')} /> : null}
          {r.technical.resistance_zones?.length ? <DetailRow label="저항 구간" value={r.technical.resistance_zones.join(' / ')} /> : null}
        </Section>
      )}

      {(r.catalysts || r.company_analysis || r.rise_reason) && (
        <div className="two-col">
          {r.catalysts && (
            <Section title="📈 상승 재료 · 섹터 기대감">
              <DetailRow label="뉴스/공시" value={r.catalysts.news_materials} />
              <DetailRow label="미래 가치 기대감" value={r.catalysts.sector_expectation} />
              {r.catalysts.risk_factors?.length ? (
                <div className="ai-detail-row">
                  <span className="ai-detail-label">리스크</span>
                  <ul style={{ margin: 0, padding: '0 0 0 1rem' }}>
                    {r.catalysts.risk_factors.map((f, i) => <li key={i} className="ai-detail-val">{f}</li>)}
                  </ul>
                </div>
              ) : null}
            </Section>
          )}
          {r.company_analysis && (
            <Section title="🏢 기업 분석">
              <DetailRow label="섹터" value={r.company_analysis.sector} />
              <DetailRow label="핵심 제품" value={r.company_analysis.key_products} />
              <DetailRow label="평가" value={r.company_analysis.current_position} />
            </Section>
          )}
          {!r.catalysts && r.rise_reason && (
            <Section title="🚀 상승 이유">
              <DetailRow label="촉매" value={r.rise_reason.catalyst} />
              <DetailRow label="섹터 트렌드" value={r.rise_reason.sector_trend} />
              {r.rise_reason.news_factors?.length ? (
                <div className="ai-detail-row">
                  <span className="ai-detail-label">예상 이슈</span>
                  <ul style={{ margin: 0, padding: '0 0 0 1rem' }}>
                    {r.rise_reason.news_factors.map((f, i) => <li key={i} className="ai-detail-val">{f}</li>)}
                  </ul>
                </div>
              ) : null}
            </Section>
          )}
        </div>
      )}

      {r.outlook && (
        <Section title="🔭 전망">
          <DetailRow label="단기 (1~5일)" value={r.outlook.short_term} />
          <DetailRow label="중기 (1~4주)" value={r.outlook.mid_term} />
        </Section>
      )}

      {r.risks?.length ? (
        <Section title="⚠️ 리스크 요인">
          <ul className="ai-risk-list">
            {r.risks.map((risk, i) => <li key={i}>{risk}</li>)}
          </ul>
        </Section>
      ) : null}
      {r.data_needed && (
        <Section title="ℹ️ 추가 정보 요청">
          <p style={{ margin: 0, color: '#fbbf24', fontSize: '0.88rem' }}>📌 {r.data_needed}</p>
        </Section>
      )}
      <p className="ai-disclaimer">⚠️ AI 분석은 참고용입니다. 투자 결정의 책임은 본인에게 있습니다.</p>
    </div>
  )
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export function AiChartPage({ publicMode = false }: { publicMode?: boolean } = {}) {
  const [mode, setMode] = useState<Mode>('drop')
  const [droppedFiles, setDroppedFiles] = useState<DroppedFile[]>([])
  const [isDragOver, setIsDragOver] = useState(false)
  const [symbol, setSymbol] = useState('')
  const [symbolAutoDetected, setSymbolAutoDetected] = useState(false)
  const [extraContext, setExtraContext] = useState('')
  const [symCode, setSymCode] = useState('')
  const [period, setPeriod] = useState('6mo')
  const [intv, setIntv] = useState('1d')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AnalysisResponse | null>(null)
  const [multiResults, setMultiResults] = useState<AnalysisResponse[] | null>(null)
  const [docResult, setDocResult] = useState<{ mode: string; extraction: Extraction } | null>(null)
  const [reportModal, setReportModal] = useState<{ code: string; name: string } | null>(null)
  const [searchChat, setSearchChat] = useState<{ role: 'user' | 'assistant'; content: string; stock?: { code: string; name: string; inWatchlist?: boolean; hasReport?: boolean } | null }[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const runSearch = useCallback(async (q: string) => {
    if (!q.trim() || searchLoading) return
    const history = searchChat.map(m => ({ role: m.role, content: m.content }))
    setSearchChat(prev => [...prev, { role: 'user', content: q }])
    setSymbol('')
    setSearchLoading(true)
    try {
      let resp: Response
      if (publicMode) {
        const g = getGuest()
        resp = await fetch('/api/public/ai-search', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: q, history, guest_name: g?.name ?? '', guest_phone: g?.phone ?? '' }),
        })
      } else {
        resp = await fetch('/api/admin/ai-search', {
          method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getAccessToken()}` },
          body: JSON.stringify({ query: q, history }),
        })
      }
      const d = await resp.json()
      if (!resp.ok) throw new Error(d.detail ?? `오류 ${resp.status}`)
      setSearchChat(prev => [...prev, { role: 'assistant', content: d.answer ?? '(응답 없음)', stock: d.resolvedStock }])
    } catch (e) {
      setSearchChat(prev => [...prev, { role: 'assistant', content: `검색 실패: ${e instanceof Error ? e.message : String(e)}` }])
    } finally {
      setSearchLoading(false)
    }
  }, [searchChat, searchLoading, publicMode])
  const [showKeyPanel, setShowKeyPanel] = useState(false)
  const [keyProvider, setKeyProvider] = useState<'gemini' | 'groq' | 'openai'>('gemini')
  const [apiKeyInput, setApiKeyInput] = useState('')
  const [keyStatus, setKeyStatus] = useState<'idle' | 'saving' | 'ok' | 'err'>('idle')
  const [keyMsg, setKeyMsg] = useState('')
  const [diagSteps, setDiagSteps] = useState<{step: string; ok: boolean; msg: string}[] | null>(null)
  const [diagRunning, setDiagRunning] = useState(false)
  const [devSug, setDevSug] = useState<DevResponse | null>(null)
  const [devRunning, setDevRunning] = useState(false)
  const [devErr, setDevErr] = useState<string | null>(null)
  const [workReqs, setWorkReqs] = useState<WorkRequestsResp | null>(null)
  const [workRunning, setWorkRunning] = useState(false)
  const [workErr, setWorkErr] = useState<string | null>(null)
  const [csvBatchNote, setCsvBatchNote] = useState<string | null>(null)

  const providerPrefixes: Record<string, string> = { openai: 'sk-', gemini: '', groq: 'gsk_' }
  const providerHints: Record<string, string> = {
    openai: 'sk-로 시작 · platform.openai.com/api-keys',
    gemini: 'AIza로 시작 · aistudio.google.com/app/apikey',
    groq: 'gsk_로 시작 · console.groq.com/keys',
  }

  async function saveApiKey(e: React.FormEvent) {
    e.preventDefault()
    const key = apiKeyInput.trim()
    const prefix = providerPrefixes[keyProvider]
    if (!key || key.length < 10) {
      setKeyStatus('err'); setKeyMsg('API 키를 입력하세요'); return
    }
    if (prefix && !key.startsWith(prefix)) {
      setKeyStatus('err'); setKeyMsg(`${providerHints[keyProvider]}`); return
    }
    setKeyStatus('saving')
    try {
      await fetchJson('/api/ai/chart-analysis/set-key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: key, provider: keyProvider }),
      })
      setKeyStatus('ok'); setKeyMsg('저장 완료! AI 분석을 바로 사용할 수 있습니다')
      setApiKeyInput('')
      setTimeout(() => setShowKeyPanel(false), 1800)
    } catch (err: unknown) {
      setKeyStatus('err'); setKeyMsg(err instanceof Error ? err.message : String(err))
    }
  }

  async function runDiagnose() {
    setDiagRunning(true)
    setDiagSteps(null)
    try {
      const data = await fetchJson<{ ok: boolean; steps: {step: string; ok: boolean; msg: string}[] }>(
        '/api/ai/diagnose'
      )
      setDiagSteps(data.steps ?? [])
    } catch (err: unknown) {
      setDiagSteps([{ step: '진단 실패', ok: false, msg: err instanceof Error ? err.message : String(err) }])
    } finally {
      setDiagRunning(false)
    }
  }

  async function runDevSuggestions() {
    setDevRunning(true); setDevErr(null); setDevSug(null)
    try {
      const data = await fetchJson<DevResponse>('/api/ai/crossval/dev-suggestions', { method: 'POST' })
      setDevSug(data)
    } catch (err: unknown) {
      setDevErr(err instanceof Error ? err.message : String(err))
    } finally {
      setDevRunning(false)
    }
  }

  async function loadWorkRequests() {
    setWorkRunning(true); setWorkErr(null)
    try {
      const data = await fetchJson<WorkRequestsResp>('/api/ai/crossval/work-requests')
      setWorkReqs(data)
    } catch (err: unknown) {
      setWorkErr(err instanceof Error ? err.message : String(err))
    } finally {
      setWorkRunning(false)
    }
  }

  // 작업 요구 클릭 → 해당 종목 코드 채우고 드롭 모드로 (바로 CSV 업로드 가능)
  function pickWorkRequest(code: string) {
    setMode('drop'); setSymbol(code); setSymbolAutoDetected(true)
    setWorkReqs(null)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  async function exportOnePager(override?: AnalysisResponse) {
    const rep = override ?? result
    if (!rep) return
    // Convert image object URLs → base64 data URLs
    const images: string[] = []
    for (const f of droppedFiles.filter(d => d.type === 'image' && d.previewUrl)) {
      try {
        const resp = await fetch(f.previewUrl!)
        const blob = await resp.blob()
        const b64 = await new Promise<string>(resolve => {
          const reader = new FileReader()
          reader.onload = () => resolve(reader.result as string)
          reader.readAsDataURL(blob)
        })
        images.push(b64)
      } catch { /* skip failed images */ }
    }
    const html = buildReportHtml(rep, images)
    const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const dateStr = new Date(rep.analyzed_at).toISOString().slice(0, 10)
    a.download = `${rep.stock_name ?? rep.symbol}_AI분석_${dateStr}.html`
    a.click()
    URL.revokeObjectURL(url)
  }

  const processFiles = useCallback(async (incoming: File[]) => {
    const accepted = incoming.filter(f =>
      f.type.startsWith('image/') || f.name.endsWith('.csv') || f.type === 'text/csv'
    ).slice(0, 6)

    const items: DroppedFile[] = await Promise.all(accepted.map(async file => {
      if (file.type.startsWith('image/')) {
        return { file, previewUrl: URL.createObjectURL(file), type: 'image' as const }
      }
      return { file, type: 'csv' as const }
    }))

    setDroppedFiles(prev => {
      prev.forEach(d => d.previewUrl && URL.revokeObjectURL(d.previewUrl))
      return items
    })

    if (items.length > 0) {
      let detected = ''
      for (const item of items) {
        detected = extractSymbolFromFilename(item.file.name)
        if (detected) break
        if (item.type === 'csv') {
          const text = await item.file.text()
          detected = extractSymbolFromCsv(text)
          if (detected) break
        }
      }
      if (detected) {
        setSymbol(detected)
        setSymbolAutoDetected(true)
      }
    }
  }, [])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    processFiles(Array.from(e.dataTransfer.files))
  }, [processFiles])

  const onFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    processFiles(Array.from(e.target.files ?? []))
    e.target.value = ''
  }, [processFiles])

  function removeFile(idx: number) {
    setDroppedFiles(prev => {
      const copy = [...prev]
      if (copy[idx].previewUrl) URL.revokeObjectURL(copy[idx].previewUrl!)
      copy.splice(idx, 1)
      return copy
    })
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null); setResult(null); setMultiResults(null); setDocResult(null); setCsvBatchNote(null)

    if (mode === 'drop') {
      // 파일 없이 텍스트만 입력 → 자연어 대화형 검색 (질문 자체부터 분석)
      if (droppedFiles.length === 0) {
        if (symbol.trim()) { runSearch(symbol.trim()); return }
        setError('파일을 업로드하거나 검색어를 입력하세요'); return
      }
      // symbol이 비어있으면 파일명에서 자동 추출 시도 (실패해도 진행 — 백엔드가 콘텐츠 인식)
      let effectiveSymbol = symbol.trim()
      if (!effectiveSymbol) {
        for (const d of droppedFiles) {
          effectiveSymbol = extractSymbolFromFilename(d.file.name)
          if (effectiveSymbol) break
        }
      }
      const imageFiles = droppedFiles.filter(d => d.type === 'image')
      const csvFiles = droppedFiles.filter(d => d.type === 'csv')
      // 공개 모드는 이미지 분석만 지원 (CSV·적재 등 관리자 기능 제외)
      if (publicMode && csvFiles.length > 0) {
        setError('공개 분석은 차트 이미지만 지원합니다 (CSV는 관리자 전용)'); return
      }
      // CSV는 종목 식별자가 반드시 필요. 이미지는 콘텐츠 인식으로 진행 가능.
      if (!effectiveSymbol && csvFiles.length > 0 && imageFiles.length === 0) {
        setError('CSV는 종목명 또는 종목코드를 입력하세요 (파일명에서 자동 감지 실패)'); return
      }
      setLoading(true)
      try {
        if (imageFiles.length > 0) {
          const form = new FormData()
          imageFiles.forEach(d => form.append('files', d.file))
          let resp: Response
          if (publicMode) {
            const g = getGuest()
            const params = new URLSearchParams({
              guest_name: g?.name ?? '', guest_phone: g?.phone ?? '',
            })
            if (extraContext.trim()) params.set('extra_context', extraContext.trim())
            resp = await fetch(`/api/public/chart-analysis/image?${params}`, { method: 'POST', body: form })
          } else {
            const token = getAccessToken()
            const params = new URLSearchParams({ symbol: effectiveSymbol || 'AUTO' })
            if (extraContext.trim()) params.set('extra_context', extraContext.trim())
            resp = await fetch(`/api/ai/chart-analysis/image?${params}`, {
              method: 'POST',
              headers: { Authorization: `Bearer ${token}` },
              body: form,
            })
          }
          const data = await resp.json()
          if (!resp.ok) throw new Error(data.detail ?? `서버 오류 ${resp.status}`)
          // 모드별 라우팅: stock / multi_stock / market_data / unrecognized
          if (data?.mode === 'market_data' || data?.mode === 'unrecognized') {
            setDocResult({ mode: data.mode, extraction: data.extraction ?? {} })
          } else if (data?.multi && Array.isArray(data.results)) {
            setMultiResults(data.results as AnalysisResponse[])
          } else {
            setResult(data as AnalysisResponse)
          }
        } else if (csvFiles.length > 0) {
          // 1) 드롭한 전 파일을 intake_only로 빠르게 적재·병합 (LLM 생략).
          // 2) 그 후 '가장 큰 타임프레임 + 변곡점 집중'으로 1회만 분석 → 업로드 순서 무관·결정론.
          const token = getAccessToken()
          let lastCrossval: CrossvalInfo | undefined      // 마지막 응답 = 가장 완전한 병합 요약
          let okCount = 0
          const failed: string[] = []
          for (const d of csvFiles) {
            const fsym = extractSymbolFromFilename(d.file.name) || effectiveSymbol
            const form = new FormData()
            form.append('file', d.file)
            const params = new URLSearchParams({ symbol: fsym, intake_only: 'true' })
            try {
              const resp = await fetch(`/api/ai/chart-analysis/upload?${params}`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}` },
                body: form,
              })
              const data = await resp.json()
              if (!resp.ok) throw new Error(data.detail ?? `서버 오류 ${resp.status}`)
              if (data.crossval) lastCrossval = data.crossval as CrossvalInfo
              okCount++
            } catch (e) {
              failed.push(`${d.file.name}: ${e instanceof Error ? e.message : String(e)}`)
            }
          }
          // 가장 큰 TF + 변곡점 집중 분석 1회 (기준 고정)
          if (okCount > 0) {
            try {
              const aparams = new URLSearchParams({ symbol: effectiveSymbol })
              const resp = await fetch(`/api/ai/crossval/analyze?${aparams}`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}` },
              })
              const data = await resp.json()
              if (!resp.ok) throw new Error(data.detail ?? `분석 오류 ${resp.status}`)
              const analyzed = data as AnalysisResponse
              setResult({ ...analyzed, crossval: lastCrossval ?? analyzed.crossval })
            } catch (e) {
              setError(`적재 ${okCount}개 완료, 분석 실패: ${e instanceof Error ? e.message : String(e)}`)
            }
          }
          setCsvBatchNote(
            `CSV ${csvFiles.length}개 중 ${okCount}개 적재·병합 완료 (가장 큰 TF 변곡점 기준 분석)` +
            (failed.length ? ` · 실패 ${failed.length}개` : '')
          )
          if (okCount === 0 && failed.length > 0) setError(failed.join('\n'))
        }
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : String(err))
      } finally {
        setLoading(false)
      }
    } else {
      if (!symCode.trim()) { setError('종목코드를 입력하세요'); return }
      setLoading(true)
      try {
        const data = await fetchJson<AnalysisResponse>('/api/ai/chart-analysis', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol: symCode.trim(), period, interval: intv }),
        })
        setResult(data)
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : String(err))
      } finally {
        setLoading(false)
      }
    }
  }

  const hasFiles = droppedFiles.length > 0

  return (
    <main className="bolinzer-shell">
      <header className="topbar glass">
        <div>
          <p className="top-label">AI CHART ANALYSIS</p>
          <h2>AI 분석</h2>
          <p className="subtle">차트 이미지 · CSV를 드롭하거나 종목코드로 즉시 AI 분석</p>
        </div>
        {!publicMode && (<>
        <button type="button" className="ai-key-settings-btn" onClick={() => { setShowKeyPanel(v => !v); setKeyStatus('idle'); setKeyMsg('') }}
          title="AI API 키 설정">
          🔑 API 키 설정
        </button>
        <button type="button" className="ai-key-settings-btn" style={{ marginLeft: 8 }}
          onClick={runDiagnose} disabled={diagRunning} title="AI 파이프라인 진단">
          {diagRunning ? '⏳ 진단 중...' : '🔍 진단'}
        </button>
        <button type="button" className="ai-key-settings-btn" style={{ marginLeft: 8 }}
          onClick={runDevSuggestions} disabled={devRunning}
          title="적재된 교차검증 코퍼스로 언어학습 발전 가능성 제시">
          {devRunning ? '⏳ 분석 중...' : '🧠 발전 가능성'}
        </button>
        <button type="button" className="ai-key-settings-btn" style={{ marginLeft: 8 }}
          onClick={loadWorkRequests} disabled={workRunning}
          title="관심종목 중 데이터 부족 종목 작업 요구">
          {workRunning ? '⏳ 조회 중...' : '📋 작업 요구'}
        </button>
        </>)}
      </header>

      {diagSteps !== null && (
        <div className="ai-diag-panel panel glass">
          <div className="ai-key-panel-head">
            <span>🔍 AI 파이프라인 진단</span>
            <button type="button" className="ai-key-close" onClick={() => setDiagSteps(null)}>✕</button>
          </div>
          <ul className="ai-diag-list">
            {diagSteps.map((s, i) => (
              <li key={i} className={`ai-diag-step ${s.ok ? 'pass' : 'fail'}`}>
                <span className="ai-diag-icon">{s.ok ? '✅' : '❌'}</span>
                <span className="ai-diag-name">{s.step}</span>
                <span className="ai-diag-msg">{s.msg}</span>
              </li>
            ))}
          </ul>
          {diagSteps.length > 0 && diagSteps.every(s => s.ok) && (
            <p className="ai-diag-ok-msg">✅ 모든 단계 정상 — AI 분석을 바로 사용하세요</p>
          )}
        </div>
      )}

      {(devSug || devErr) && (
        <div className="ai-diag-panel panel glass">
          <div className="ai-key-panel-head">
            <span>🧠 언어학습 발전 가능성 — 교차검증 코퍼스 기반</span>
            <button type="button" className="ai-key-close"
              onClick={() => { setDevSug(null); setDevErr(null) }}>✕</button>
          </div>
          {devErr ? (
            <p className="ai-key-msg err">❌ {devErr}</p>
          ) : devSug && (
            <div style={{ display: 'grid', gap: 12, padding: '4px 2px' }}>
              <div style={{ fontSize: '0.78rem', color: 'var(--text-soft)' }}>
                코퍼스: CSV {devSug.corpus.csv_count ?? 0} · 이미지 {devSug.corpus.image_count ?? 0} · 종목 {devSug.corpus.symbol_count ?? 0}
                {devSug.corpus.avg_verified_ratio != null && <> · 평균 검증통과율 {(devSug.corpus.avg_verified_ratio * 100).toFixed(1)}%</>}
                <span style={{ marginLeft: 8, opacity: 0.7 }}>({devSug.provider}/{devSug.model})</span>
              </div>
              <div style={{ fontWeight: 700, fontSize: '0.98rem', color: 'var(--text-main)' }}>{devSug.suggestions.headline}</div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-soft)' }}>📦 준비도: {devSug.suggestions.readiness}</div>
              <div style={{ display: 'grid', gap: 8 }}>
                {(devSug.suggestions.ideas ?? []).map((idea, i) => {
                  const fc = idea.feasibility === 'now' ? '#22c55e' : idea.feasibility === 'soon' ? '#f59e0b' : '#94a3b8'
                  const fl = idea.feasibility === 'now' ? '지금' : idea.feasibility === 'soon' ? '곧' : '추후'
                  return (
                    <div key={i} style={{ padding: '10px 12px', borderRadius: 10,
                      background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                        <span style={{ fontWeight: 700, color: 'var(--text-main)' }}>{idea.title}</span>
                        <span style={{ fontSize: '0.72rem', padding: '1px 8px', borderRadius: 999,
                          background: fc + '22', color: fc, border: `1px solid ${fc}55` }}>{fl}</span>
                      </div>
                      <div style={{ fontSize: '0.83rem', color: 'var(--text-soft)', lineHeight: 1.6 }}>
                        {idea.what}<br />
                        <span style={{ opacity: 0.85 }}>· 필요 데이터: {idea.data_needed}</span><br />
                        <span style={{ color: '#fbbf24', opacity: 0.9 }}>⚠ {idea.caution}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
              {(devSug.suggestions.next_actions ?? []).length > 0 && (
                <div style={{ fontSize: '0.83rem', color: 'var(--text-soft)' }}>
                  <strong style={{ color: 'var(--text-main)' }}>다음 행동</strong>
                  <ul style={{ margin: '4px 0 0', paddingLeft: 18, lineHeight: 1.7 }}>
                    {devSug.suggestions.next_actions.map((a, i) => <li key={i}>{a}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {(workReqs || workErr) && (
        <div className="ai-diag-panel panel glass">
          <div className="ai-key-panel-head">
            <span>📋 데이터 작업 요구 — 관심종목 커버리지</span>
            <button type="button" className="ai-key-close"
              onClick={() => { setWorkReqs(null); setWorkErr(null) }}>✕</button>
          </div>
          {workErr ? (
            <p className="ai-key-msg err">❌ {workErr}</p>
          ) : workReqs && (
            <div style={{ display: 'grid', gap: 10, padding: '4px 2px' }}>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-soft)' }}>
                관심종목 {workReqs.watchlist_total}개 중 <strong style={{ color: '#22c55e' }}>{workReqs.covered}개 충분</strong>,
                <strong style={{ color: '#f59e0b' }}> {workReqs.request_count}개 데이터 필요</strong>
                <span style={{ marginLeft: 6, opacity: 0.7 }}>· 클릭하면 종목코드 자동 입력 → CSV 업로드</span>
              </div>
              <div style={{ display: 'grid', gap: 6, maxHeight: 380, overflowY: 'auto' }}>
                {workReqs.requests.map((r) => {
                  const pc = r.priority === 'high' ? '#ef4444' : r.priority === 'medium' ? '#f59e0b' : '#94a3b8'
                  const pl = r.priority === 'high' ? '없음' : r.priority === 'medium' ? '부족' : '보완'
                  return (
                    <button type="button" key={r.stock_code} onClick={() => pickWorkRequest(r.stock_code)}
                      style={{ display: 'flex', alignItems: 'center', gap: 10, textAlign: 'left',
                        padding: '8px 12px', borderRadius: 10, cursor: 'pointer',
                        background: 'rgba(255,255,255,0.04)', border: `1px solid ${pc}44`, color: 'var(--text-main)' }}>
                      <span style={{ fontSize: '0.7rem', padding: '1px 8px', borderRadius: 999,
                        background: pc + '22', color: pc, border: `1px solid ${pc}66`, flexShrink: 0 }}>{pl}</span>
                      <span style={{ fontWeight: 700, minWidth: 64 }}>{r.stock_code}</span>
                      <span style={{ flex: 1, fontSize: '0.84rem' }}>{r.stock_name ?? ''}</span>
                      <span style={{ fontSize: '0.76rem', color: 'var(--text-soft)' }}>{r.reason} · {r.suggested_action}</span>
                    </button>
                  )
                })}
                {workReqs.requests.length === 0 && (
                  <div style={{ fontSize: '0.85rem', color: '#22c55e', padding: 8 }}>✅ 모든 관심종목 데이터 충분</div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {showKeyPanel && (
        <div className="ai-key-panel panel glass">
          <div className="ai-key-panel-head">
            <span>🔑 AI API 키 설정</span>
            <button type="button" className="ai-key-close" onClick={() => setShowKeyPanel(false)}>✕</button>
          </div>
          <div className="ai-provider-tabs">
            <button
              type="button"
              className={`ai-provider-tab${keyProvider === 'gemini' ? ' active' : ''}`}
              onClick={() => { setKeyProvider('gemini'); setApiKeyInput(''); setKeyStatus('idle') }}
            >Gemini <span className="free-badge">무료</span></button>
            <button
              type="button"
              className={`ai-provider-tab${keyProvider === 'groq' ? ' active' : ''}`}
              onClick={() => { setKeyProvider('groq'); setApiKeyInput(''); setKeyStatus('idle') }}
            >Groq <span className="free-badge">무료</span></button>
            <button
              type="button"
              className={`ai-provider-tab${keyProvider === 'openai' ? ' active' : ''}`}
              onClick={() => { setKeyProvider('openai'); setApiKeyInput(''); setKeyStatus('idle') }}
            >OpenAI</button>
          </div>
          <p className="ai-key-hint">
            {keyProvider === 'gemini' && <><a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer">aistudio.google.com/app/apikey</a>에서 무료 발급 · <code>AIza</code>로 시작</>}
            {keyProvider === 'groq' && <><a href="https://console.groq.com/keys" target="_blank" rel="noreferrer">console.groq.com/keys</a>에서 무료 발급 · <code>gsk_</code>로 시작</>}
            {keyProvider === 'openai' && <><a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer">platform.openai.com/api-keys</a>에서 발급 · <code>sk-</code>로 시작</>}
            <br />키는 <code>backend/.env</code>에 저장되며 즉시 적용됩니다.
          </p>
          <form onSubmit={saveApiKey} className="ai-key-form">
            <input
              type="password"
              placeholder={providerPrefixes[keyProvider] + '...'}
              value={apiKeyInput}
              onChange={e => { setApiKeyInput(e.target.value); setKeyStatus('idle') }}
              autoComplete="off"
              spellCheck={false}
            />
            <button type="submit" className="btn" disabled={keyStatus === 'saving'}>
              {keyStatus === 'saving' ? '저장 중...' : '저장'}
            </button>
          </form>
          {keyMsg && (
            <p className={`ai-key-msg ${keyStatus}`}>
              {keyStatus === 'ok' ? '✅' : '❌'} {keyMsg}
            </p>
          )}
        </div>
      )}

      <div className="ai-chart-layout">
        <div className="ai-left">
          <div className="ai-mode-toggle">
            <button type="button" className={`ai-mode-btn${mode === 'drop' ? ' active' : ''}`}
              onClick={() => { setMode('drop'); setResult(null); setError(null) }}>
              📂 파일 드롭
            </button>
            <button type="button" className={`ai-mode-btn${mode === 'code' ? ' active' : ''}`}
              onClick={() => { setMode('code'); setResult(null); setError(null) }}>
              🔢 종목코드
            </button>
          </div>

          {mode === 'drop' ? (
            <form onSubmit={handleSubmit}>
              <div
                className={`ai-dropzone${isDragOver ? ' drag-over' : ''}${hasFiles ? ' has-files' : ''}`}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={e => { e.preventDefault(); setIsDragOver(true) }}
                onDragLeave={() => setIsDragOver(false)}
                onDrop={onDrop}
              >
                <span className="ai-dropzone-icon">{hasFiles ? '✅' : isDragOver ? '📥' : '📂'}</span>
                <div className="ai-dropzone-title">
                  {hasFiles ? `${droppedFiles.length}개 파일 업로드됨` : '파일을 드래그하거나 클릭하여 선택'}
                </div>
                <div className="ai-dropzone-sub">
                  TradingView 차트 이미지 (PNG/JPG) 또는 CSV 데이터<br />
                  최대 6개 · 파일당 10MB
                </div>
                <div className="ai-dropzone-badge">
                  <span>📸 이미지</span><span style={{ opacity: 0.4 }}>·</span>
                  <span>📄 CSV</span><span style={{ opacity: 0.4 }}>·</span>
                  <span>최대 6개</span>
                </div>
                <input ref={fileInputRef} type="file"
                  accept="image/png,image/jpeg,image/webp,.csv,text/csv"
                  multiple style={{ display: 'none' }} onChange={onFileInput} />
              </div>

              {hasFiles && (
                <div className="ai-file-list">
                  {droppedFiles.map((df, i) => (
                    <div className="ai-file-item" key={i}>
                      {df.type === 'image' && df.previewUrl
                        ? <img className="ai-file-thumb" src={df.previewUrl} alt="" />
                        : <div className="ai-file-csv-icon">📄</div>
                      }
                      <div className="ai-file-info">
                        <div className="ai-file-name" title={df.file.name}>{df.file.name}</div>
                        <div className="ai-file-meta">{df.type === 'image' ? '이미지' : 'CSV'} · {formatBytes(df.file.size)}</div>
                      </div>
                      <button type="button" className="ai-file-remove"
                        onClick={e => { e.stopPropagation(); removeFile(i) }}>✕</button>
                    </div>
                  ))}
                </div>
              )}

              <div className="panel glass" style={{ padding: '12px 14px', display: 'grid', gap: '10px' }}>
                {symbolAutoDetected ? (
                  <div className="ai-detected-symbol-row">
                    <span className="ai-detail-label">종목</span>
                    <span className="ai-auto-tag" style={{ fontSize: '0.9rem', padding: '3px 10px' }}>{symbol}</span>
                    <button type="button" className="ai-edit-symbol-btn"
                      onClick={() => setSymbolAutoDetected(false)}>✏️ 수정</button>
                  </div>
                ) : (
                  <label>
                    검색
                    <span className="hint"> (종목명·질문 입력 — 대화형 검색 · 파일 올리면 차트 분석)</span>
                    <input value={symbol}
                      onChange={e => setSymbol(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter' && symbol.trim() && !hasFiles) { e.preventDefault(); runSearch(symbol.trim()) } }}
                      placeholder="예: 삼성전자 어때?  /  방산 섹터 전망  /  009150" />
                  </label>
                )}
                {/* 추가 정보 — 차트 파일을 올렸을 때만 (이미지 분석 맥락). 순수 검색 화면은 깔끔하게 */}
                {!publicMode && hasFiles && (
                  <label>
                    추가 정보 <span className="hint">(선택 — 이미지 분석 지시. 예: 각각 분석 / 평단 180만원 보유)</span>
                    <input value={extraContext} onChange={e => setExtraContext(e.target.value)}
                      placeholder="예: 평단 180만원 보유 중" />
                  </label>
                )}
                {!hasFiles && (
                  <button type="button" className="ai-export-btn" disabled={searchLoading || !symbol.trim()}
                    onClick={() => runSearch(symbol.trim())}>
                    {searchLoading ? '검색 중…' : '🔍 검색'}
                  </button>
                )}
              </div>

              <div className="panel glass" style={{ padding: '10px 14px', fontSize: '0.8rem', color: 'var(--text-soft)', lineHeight: 1.7 }}>
                💡 <strong style={{ color: 'var(--text-main)' }}>TradingView 저장법</strong><br />
                차트 상단 <strong style={{ color: 'var(--text-main)' }}>📷 카메라 아이콘</strong> → PNG로 저장<br />
                일봉 · 4H · 1H 타임프레임을 함께 업로드하면 더 정확해요
              </div>

              <button className={`ai-analyze-btn${loading ? ' loading' : ''}`} type="submit" disabled={loading}>
                {loading ? '🤖 분석 중... (30~60초)' : '🚀 AI 분석 시작'}
              </button>
            </form>
          ) : (
            <form onSubmit={handleSubmit}>
              <div className="panel glass" style={{ padding: '14px', display: 'grid', gap: '10px' }}>
                <label>
                  종목코드 <span style={{ color: '#ef4444' }}>*</span>
                  <input value={symCode} onChange={e => setSymCode(e.target.value)}
                    placeholder="005930 · 009150 · AAPL" />
                </label>
                <div className="settings-grid">
                  <label>조회 기간
                    <select value={period} onChange={e => setPeriod(e.target.value)}>
                      <option value="1mo">1개월</option>
                      <option value="3mo">3개월</option>
                      <option value="6mo">6개월</option>
                      <option value="1y">1년</option>
                      <option value="2y">2년</option>
                    </select>
                  </label>
                  <label>봉 단위
                    <select value={intv} onChange={e => setIntv(e.target.value)}>
                      <option value="1d">일봉</option>
                      <option value="1wk">주봉</option>
                      <option value="1mo">월봉</option>
                    </select>
                  </label>
                </div>
              </div>
              <div className="panel glass" style={{ padding: '10px 14px', fontSize: '0.8rem', color: 'var(--text-soft)', lineHeight: 1.6 }}>
                💡 Yahoo Finance에서 자동으로 데이터를 수집합니다.<br />
                코스피 6자리 · 코스닥 6자리 · 미국 티커 모두 지원
              </div>
              <button className={`ai-analyze-btn${loading ? ' loading' : ''}`} type="submit" disabled={loading}>
                {loading ? '🤖 분석 중... (30~60초)' : '🚀 AI 분석 시작'}
              </button>
            </form>
          )}

          {error && (
            <div className="ai-error-box">
              <span>❌</span><span>{error}</span>
            </div>
          )}
        </div>

        <div>
          {searchChat.length > 0 ? (
            <div className="ai-right">
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {searchChat.map((m, i) => {
                  const isUser = m.role === 'user'
                  const len = m.content.length
                  // 답변이 길수록 더 넓고 큰 폰트로 (공간 활용)
                  const fs = isUser ? '0.95rem' : len > 360 ? '1.12rem' : len > 160 ? '1.06rem' : '1rem'
                  const maxW = isUser ? '80%' : len > 220 ? '100%' : '92%'
                  return (
                  <div key={i} style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start' }}>
                    <div className="panel glass" style={{
                      padding: isUser ? '11px 16px' : '16px 20px', maxWidth: maxW, lineHeight: 1.8, fontSize: fs,
                      width: !isUser && len > 220 ? '100%' : undefined,
                      background: isUser ? 'rgba(96,165,250,0.14)' : 'var(--color-background-secondary, rgba(255,255,255,0.04))',
                      borderColor: isUser ? 'rgba(96,165,250,0.35)' : undefined,
                    }}>
                      {m.content}
                      {m.stock && (
                        <div style={{ marginTop: 8 }}>
                          {m.stock.hasReport ? (
                            <button type="button" className="ai-export-btn"
                              onClick={() => setReportModal({ code: m.stock!.code, name: m.stock!.name })}>
                              📄 {m.stock.name} 리포트 보기
                            </button>
                          ) : (
                            <span style={{ fontSize: '0.82rem', color: '#fbbf24' }}>
                              ⏳ {m.stock.name} — {m.stock.inWatchlist ? '리포트 준비 중' : '관심종목 미편입 · 분석 준비 중'}
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                  )
                })}
                {searchLoading && (
                  <div className="panel glass" style={{ padding: '10px 14px', fontSize: '0.85rem', color: 'var(--text-soft)', alignSelf: 'flex-start' }}>답변 작성 중…</div>
                )}
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                <input value={symbol} onChange={e => setSymbol(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && symbol.trim()) { e.preventDefault(); runSearch(symbol.trim()) } }}
                  placeholder="이어서 질문…" style={{ flex: 1 }} />
                <button type="button" className="ai-export-btn" disabled={searchLoading || !symbol.trim()}
                  onClick={() => runSearch(symbol.trim())}>전송</button>
                <button type="button" className="ai-export-btn" onClick={() => setSearchChat([])}>새 대화</button>
              </div>
            </div>
          ) : loading ? (
            <LoadingSkeleton />
          ) : docResult ? (
            <DocView mode={docResult.mode} ex={docResult.extraction} publicMode={publicMode}
              onOpenReport={(code, name) => setReportModal({ code, name })} />
          ) : multiResults ? (
            <>
              <div className="panel glass" style={{ marginBottom: 12, padding: '10px 14px',
                fontSize: '0.84rem', color: '#a78bfa', border: '1px solid rgba(167,139,250,0.3)' }}>
                🧩 다종목 감지 — {multiResults.length}개 종목을 개별 분석했습니다
              </div>
              {multiResults.map((res, i) => (
                <div key={i} style={{ marginBottom: 20 }}>
                  <div style={{ fontSize: '0.78rem', color: '#64748b', fontWeight: 700, margin: '4px 0 8px' }}>
                    {i + 1} / {multiResults.length}
                  </div>
                  <ResultView data={res} onExport={() => exportOnePager(res)} />
                  {res.crossval && <CrossvalBadge info={res.crossval} />}
                </div>
              ))}
            </>
          ) : result ? (
            <>
              {csvBatchNote && (
                <div className="panel glass" style={{ marginBottom: 12, padding: '10px 14px',
                  fontSize: '0.84rem', color: '#22c55e', border: '1px solid rgba(34,197,94,0.3)' }}>
                  📥 {csvBatchNote}
                </div>
              )}
              {result.analysis_basis && (
                <div className="panel glass" style={{ marginBottom: 12, padding: '10px 14px', fontSize: '0.82rem', color: 'var(--text-soft)', lineHeight: 1.7 }}>
                  🎯 분석 기준: <strong style={{ color: 'var(--text-main)' }}>{result.analysis_basis.timeframe}</strong>
                  {' '}(가장 큰 타임프레임, {result.analysis_basis.bars.toLocaleString()}봉) · 변곡점 {result.analysis_basis.inflection_count}개 집중
                  {result.analysis_basis.mtf_used && <span style={{ marginLeft: 6, color: '#22c55e' }}>· MTF 합류 ✓</span>}
                  <span style={{ marginLeft: 6, opacity: 0.7 }}>· 업로드 순서 무관</span>
                  {(result.analysis_basis.reference_signals?.cvd || result.analysis_basis.reference_signals?.smartmoney_zone) && (
                    <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid rgba(255,255,255,0.08)', fontSize: '0.76rem' }}>
                      <span style={{ color: '#fbbf24' }}>참고 신호(미검증)</span>
                      {result.analysis_basis.reference_signals?.cvd && <div>· {result.analysis_basis.reference_signals.cvd}</div>}
                      {result.analysis_basis.reference_signals?.smartmoney_zone && <div>· {result.analysis_basis.reference_signals.smartmoney_zone}</div>}
                    </div>
                  )}
                </div>
              )}
              {result.learningSamples && !result.learningSamples.sufficient && (
                <div className="panel glass" style={{ marginBottom: 12, padding: '10px 14px', fontSize: '0.82rem', lineHeight: 1.6, borderColor: 'rgba(251,191,36,0.4)', background: 'rgba(251,191,36,0.08)', color: '#fbbf24' }}>
                  📚 학습 샘플 요청 — {result.learningSamples.request}
                </div>
              )}
              <ResultView data={result} onExport={() => exportOnePager()} />
              {result.crossval && <CrossvalBadge info={result.crossval} />}
            </>
          ) : (
            <div className="panel glass ai-empty-state">
              <div className="ai-empty-icon">🤖</div>
              <div className="ai-empty-text">
                왼쪽에 차트 이미지나 CSV를 업로드하고<br />
                <strong style={{ color: 'var(--text-main)' }}>AI 분석 시작</strong>을 누르면<br />
                여기에 결과가 표시됩니다
              </div>
              <div style={{ display: 'grid', gap: '8px', width: '100%', maxWidth: '300px', marginTop: '0.5rem' }}>
                {[
                  { icon: '📊', label: '기술적 분석 · 매수/매도 신호' },
                  { icon: '📌', label: '목표가 · 손절가 자동 계산' },
                  { icon: '🚀', label: '상승 이유 · 수급 분석' },
                  { icon: '🔭', label: '단기/중기 전망 · 리스크 요인' },
                ].map(({ icon, label }) => (
                  <div key={label} style={{
                    display: 'flex', gap: '10px', alignItems: 'center',
                    padding: '8px 12px', borderRadius: '10px',
                    background: 'rgba(255,255,255,0.04)',
                    border: '1px solid rgba(255,255,255,0.08)',
                    fontSize: '0.83rem', color: 'var(--text-soft)',
                  }}>
                    <span>{icon}</span><span>{label}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
      {reportModal && (
        <StockReportModal code={reportModal.code} name={reportModal.name}
          onClose={() => setReportModal(null)} />
      )}
    </main>
  )
}
