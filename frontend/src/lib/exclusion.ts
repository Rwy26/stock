import type { CSSProperties } from 'react'

// 거래 제외 종목 '투자 주의' 페이로드 — backend/exclusion_engine.rejection_payload 형식.
// 제외 종목 문의는 HTTP 200으로 이 메시지가 발행된다 (에러 거부 아님).
export type ExclusionInfo = {
  ok: boolean
  excluded: boolean
  opinion: string          // 'CAUTION'
  policy?: string
  code: string
  name?: string | null
  tags: string[]
  reasons: Array<{ tag: string; label: string }>
  detail?: string | null
  message: string
}

export function exclusionReasons(ex: ExclusionInfo): string {
  return ex.reasons.map(r => r.label).join(', ')
}

// 워치리스트 추가 등 POST 응답: 정상이면 {ok:true}, 제외 종목이면 투자 주의 페이로드
export type OkOrCaution = { ok: boolean } & Partial<ExclusionInfo>

export const CAUTION_BANNER_STYLE: CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  gap: 8,
  padding: '9px 12px',
  margin: '8px 0',
  background: 'rgba(251,191,36,0.08)',
  border: '1px solid rgba(251,191,36,0.35)',
  borderRadius: 10,
  color: '#fbbf24',
  fontSize: '0.78rem',
  lineHeight: 1.5,
}
