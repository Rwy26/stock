import { useEffect, useState } from 'react'
import { publicFetch } from '../../lib/publicApi'

type SectorItem = { sector: string; score: number }
type RotationData = {
  sectors?: SectorItem[]
  topSectors?: string[]
  warningSectors?: string[]
}

export function PublicSectorPage() {
  const [data, setData] = useState<RotationData | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    publicFetch<RotationData>('/api/public/sector-rotation')
      .then(setData)
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [])

  const sectors = (data?.sectors ?? []).slice().sort((a, b) => (b.score ?? 0) - (a.score ?? 0))

  return (
    <div>
      <h2 style={{ marginBottom: 4 }}>🧭 섹터 나침반</h2>
      <p style={{ color: '#94a3b8', fontSize: 13, marginBottom: 16 }}>KOSPI 섹터 로테이션 점수 (캐시 기준)</p>

      {loading && <p style={{ color: '#94a3b8' }}>분석 데이터를 불러오는 중…</p>}
      {err && <p style={{ color: '#f87171' }}>불러오기 실패: {err}</p>}

      {!loading && !err && (
        <>
          {data?.topSectors && data.topSectors.length > 0 && (
            <div className="glass" style={{ padding: 16, marginBottom: 16 }}>
              <span style={{ color: '#34d399', fontWeight: 600, fontSize: 14 }}>🏆 주도 섹터</span>
              <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {data.topSectors.map((s) => (
                  <span
                    key={s}
                    style={{ padding: '4px 10px', borderRadius: 999, background: 'rgba(52,211,153,0.15)', color: '#34d399', fontSize: 13 }}
                  >
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}

          {sectors.length > 0 && (
            <div className="glass" style={{ padding: 16 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ textAlign: 'left', color: '#94a3b8', fontSize: 13 }}>
                    <th style={{ padding: '8px 6px' }}>#</th>
                    <th style={{ padding: '8px 6px' }}>섹터</th>
                    <th style={{ padding: '8px 6px', textAlign: 'right' }}>점수</th>
                  </tr>
                </thead>
                <tbody>
                  {sectors.map((s, i) => (
                    <tr key={s.sector} style={{ borderTop: '1px solid rgba(255,255,255,0.08)' }}>
                      <td style={{ padding: '8px 6px', color: '#94a3b8' }}>{i + 1}</td>
                      <td style={{ padding: '8px 6px', fontWeight: 600 }}>{s.sector}</td>
                      <td style={{ padding: '8px 6px', textAlign: 'right', fontWeight: 600 }}>{Math.round(s.score)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
