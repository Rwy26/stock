import { useEffect, useState } from 'react'
import { publicFetch } from '../../lib/publicApi'
import { CompassReport } from '../../components/CompassReport'

type Item = {
  code: string
  name: string | null
  signal: string | null
  confidence: number | null
  upside: number | null
  analyzedAt: string | null
  isCompass: boolean
}
type Detail = {
  code: string
  name: string | null
  signal: string | null
  confidence: number | null
  analyzedAt: string | null
  result_json: Record<string, unknown> | null
}

const SIGNAL_LABEL: Record<string, string> = {
  STRONG_BUY: '적극 매수', BUY: '매수', HOLD: '관망', SELL: '매도', STRONG_SELL: '적극 매도',
}
const SIGNAL_COLOR: Record<string, string> = {
  STRONG_BUY: '#fbbf24', BUY: '#34d399', HOLD: '#60a5fa', SELL: '#f87171', STRONG_SELL: '#ef4444',
}

function fmtAt(s: string | null): string {
  if (!s) return '–'
  const d = new Date(s)
  return `${d.getMonth() + 1}. ${d.getDate()}. ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function PublicAiHistoryPage() {
  const [items, setItems] = useState<Item[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  useEffect(() => {
    publicFetch<{ items: Item[] }>('/api/public/ai-history')
      .then(r => setItems(r.items))
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [])

  const openDetail = (code: string) => {
    setDetailLoading(true)
    publicFetch<Detail>(`/api/public/ai-history/${code}`)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false))
  }

  return (
    <div>
      <h2 style={{ marginBottom: 4 }}>📊 AI 분석 리포트</h2>
      <p style={{ color: '#94a3b8', fontSize: 13, marginBottom: 16, lineHeight: 1.6 }}>
        AI가 시장 자금흐름·차트·수급을 종합해 작성한 종목 리포트입니다. 종목을 누르면 상세 리포트가 열립니다.
        <br />참고용 정보이며 투자 권유가 아닙니다.
      </p>

      {loading && <p style={{ color: '#94a3b8' }}>불러오는 중…</p>}
      {err && <p style={{ color: '#f87171' }}>불러오기 실패: {err}</p>}

      {!loading && !err && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {items.length === 0 && <p style={{ color: '#64748b' }}>아직 공개된 분석이 없습니다.</p>}
          {items.map(it => (
            <button
              key={it.code}
              type="button"
              onClick={() => openDetail(it.code)}
              style={{
                display: 'flex', alignItems: 'center', gap: 12, textAlign: 'left',
                padding: '12px 14px', borderRadius: 12, cursor: 'pointer',
                background: 'rgba(13,18,34,0.85)', border: '1px solid rgba(255,255,255,0.09)',
                color: '#f1f5f9',
              }}
            >
              <span style={{
                padding: '3px 10px', borderRadius: 99, fontSize: 12, fontWeight: 800, flexShrink: 0,
                color: SIGNAL_COLOR[it.signal ?? ''] ?? '#94a3b8',
                background: `${SIGNAL_COLOR[it.signal ?? ''] ?? '#94a3b8'}1a`,
                border: `1px solid ${SIGNAL_COLOR[it.signal ?? ''] ?? '#94a3b8'}44`,
              }}>
                {SIGNAL_LABEL[it.signal ?? ''] ?? it.signal ?? '–'}
              </span>
              <span style={{ fontWeight: 700, flex: 1, minWidth: 0 }}>
                {it.name ?? it.code}
                <span style={{ marginLeft: 6, color: '#64748b', fontSize: 12, fontWeight: 400 }}>{it.code}</span>
              </span>
              {it.confidence != null && (
                <span style={{ fontSize: 12.5, color: '#94a3b8', flexShrink: 0 }}>점수 {Math.round(it.confidence)}</span>
              )}
              <span style={{ fontSize: 12, color: '#64748b', flexShrink: 0 }}>{fmtAt(it.analyzedAt)}</span>
            </button>
          ))}
        </div>
      )}

      {/* 상세 모달 */}
      {(detail || detailLoading) && (
        <div
          onClick={() => setDetail(null)}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)', zIndex: 100,
            display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
            overflowY: 'auto', padding: '24px 8px',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              maxWidth: 720, width: '100%', position: 'relative',
              background: 'rgba(8,12,24,0.97)', border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 16, padding: '20px 16px',
            }}
          >
            <button
              type="button"
              onClick={() => setDetail(null)}
              style={{
                position: 'absolute', top: 10, right: 12, background: 'none', border: 'none',
                color: '#94a3b8', fontSize: 20, cursor: 'pointer', zIndex: 1,
              }}
            >×</button>
            {detailLoading ? (
              <p style={{ textAlign: 'center', color: '#94a3b8' }}>리포트 불러오는 중…</p>
            ) : detail?.result_json && (detail.result_json as Record<string, unknown>).source === 'market-compass-12stage' ? (
              <CompassReport data={detail.result_json as Record<string, never>} />
            ) : detail ? (
              <div>
                <h3>{detail.name ?? detail.code}</h3>
                <p style={{ color: '#94a3b8', fontSize: 13 }}>
                  시그널: {SIGNAL_LABEL[detail.signal ?? ''] ?? '–'} · 분석일시: {fmtAt(detail.analyzedAt)}
                </p>
                <p style={{ color: '#64748b', fontSize: 13 }}>이 분석은 요약 정보만 제공됩니다.</p>
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  )
}
