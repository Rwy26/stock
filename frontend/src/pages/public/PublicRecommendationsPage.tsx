import { useEffect, useState } from 'react'
import { publicFetch } from '../../lib/publicApi'

type Item = { rank: number; name: string; code: string; score: number }

export function PublicRecommendationsPage() {
  const [items, setItems] = useState<Item[]>([])
  const [date, setDate] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    publicFetch<{ date: string; items: Item[] }>('/api/public/recommendations')
      .then((d) => {
        setItems(d.items)
        setDate(d.date)
      })
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <h2 style={{ marginBottom: 4 }}>📈 종목 추천</h2>
      <p style={{ color: '#94a3b8', fontSize: 13, marginBottom: 16 }}>
        기준일 {date || '—'} · 점수 기반 추천 (실시간 시세 제외)
      </p>

      {loading && <p style={{ color: '#94a3b8' }}>불러오는 중…</p>}
      {err && <p style={{ color: '#f87171' }}>불러오기 실패: {err}</p>}
      {!loading && !err && items.length === 0 && (
        <p style={{ color: '#94a3b8' }}>오늘 추천 데이터가 아직 없습니다.</p>
      )}

      {items.length > 0 && (
        <div className="glass" style={{ padding: 16 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ textAlign: 'left', color: '#94a3b8', fontSize: 13 }}>
                <th style={{ padding: '8px 6px' }}>#</th>
                <th style={{ padding: '8px 6px' }}>종목</th>
                <th style={{ padding: '8px 6px' }}>코드</th>
                <th style={{ padding: '8px 6px', textAlign: 'right' }}>점수</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={it.code} style={{ borderTop: '1px solid rgba(255,255,255,0.08)' }}>
                  <td style={{ padding: '8px 6px', color: '#94a3b8' }}>{it.rank || i + 1}</td>
                  <td style={{ padding: '8px 6px', fontWeight: 600 }}>{it.name}</td>
                  <td style={{ padding: '8px 6px', color: '#94a3b8' }}>{it.code}</td>
                  <td style={{ padding: '8px 6px', textAlign: 'right', color: '#34d399', fontWeight: 600 }}>
                    {it.score}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
