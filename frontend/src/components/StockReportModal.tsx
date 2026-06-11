/* 종목 이름 클릭 → AI 분석 리포트 모달.
   데이터: /api/public/ai-history/{code} (인증 불필요 — 관리자·게스트 공용)
   리포트가 없으면 안내 + 네이버 시세 링크. */

import { useEffect, useState } from 'react'
import { publicFetch } from '../lib/publicApi'
import { CompassReport } from './CompassReport'

type Detail = {
  code: string
  name: string | null
  signal: string | null
  analyzedAt: string | null
  result_json: Record<string, unknown> | null
}

export function StockReportModal({
  code, name, onClose,
}: { code: string; name?: string; onClose: () => void }) {
  const [detail, setDetail] = useState<Detail | null>(null)
  const [state, setState] = useState<'loading' | 'ok' | 'none'>('loading')

  useEffect(() => {
    setState('loading')
    setDetail(null)
    publicFetch<Detail>(`/api/public/ai-history/${code}`)
      .then(d => { setDetail(d); setState('ok') })
      .catch(() => setState('none'))
  }, [code])

  const isCompass =
    detail?.result_json &&
    (detail.result_json as Record<string, unknown>).source === 'market-compass-12stage'

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)', zIndex: 120,
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
          onClick={onClose}
          style={{
            position: 'absolute', top: 10, right: 12, background: 'none', border: 'none',
            color: '#94a3b8', fontSize: 20, cursor: 'pointer', zIndex: 1,
          }}
        >×</button>

        {state === 'loading' && (
          <p style={{ textAlign: 'center', color: '#94a3b8', padding: '30px 0' }}>
            {name ?? code} 리포트 불러오는 중…
          </p>
        )}

        {state === 'ok' && isCompass && (
          <CompassReport data={detail!.result_json as Record<string, never>} />
        )}

        {(state === 'none' || (state === 'ok' && !isCompass)) && (
          <div style={{ textAlign: 'center', padding: '26px 8px' }}>
            <h3 style={{ marginBottom: 8 }}>{name ?? detail?.name ?? code}</h3>
            <p style={{ color: '#94a3b8', fontSize: 13.5, lineHeight: 1.7 }}>
              아직 이 종목의 AI 분석 리포트가 없습니다.
              <br />
              <span style={{ color: '#64748b', fontSize: 12.5 }}>
                매일 밤 9시 전 종목 자동 분석이 돌고 나면 여기서 바로 볼 수 있습니다.
              </span>
            </p>
            <a
              href={`https://finance.naver.com/item/main.naver?code=${code}`}
              target="_blank" rel="noreferrer"
              style={{ color: '#93c5fd', fontSize: 13 }}
            >
              네이버 시세 보기 ↗
            </a>
          </div>
        )}

        {state === 'ok' && isCompass && (
          <p style={{ textAlign: 'center', marginTop: 4 }}>
            <a
              href={`https://finance.naver.com/item/main.naver?code=${code}`}
              target="_blank" rel="noreferrer"
              style={{ color: '#64748b', fontSize: 12 }}
            >
              네이버 시세 보기 ↗
            </a>
          </p>
        )}
      </div>
    </div>
  )
}
