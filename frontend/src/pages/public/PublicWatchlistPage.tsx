import { useEffect, useState } from 'react'
import { publicFetch } from '../../lib/publicApi'

type Item = { name: string; code: string; score: number; sector: string }

export function PublicWatchlistPage() {
  const [items, setItems] = useState<Item[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    publicFetch<{ items: Item[] }>('/api/public/watchlist')
      .then((d) => setItems(d.items))
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <h2 style={{ marginBottom: 4 }}>⭐ 관심 종목</h2>
      <p style={{ color: '#94a3b8', fontSize: 13, marginBottom: 16 }}>대표 관심 종목 (읽기 전용)</p>

      {loading && <p style={{ color: '#94a3b8' }}>불러오는 중…</p>}
      {err && <p style={{ color: '#f87171' }}>불러오기 실패: {err}</p>}
      {!loading && !err && items.length === 0 && <p style={{ color: '#94a3b8' }}>등록된 관심 종목이 없습니다.</p>}

      {items.length > 0 && (
        <div className="glass" style={{ padding: 16 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ textAlign: 'left', color: '#94a3b8', fontSize: 13 }}>
                <th style={{ padding: '8px 6px' }}>종목</th>
                <th style={{ padding: '8px 6px' }}>코드</th>
                <th style={{ padding: '8px 6px' }}>섹터</th>
                <th style={{ padding: '8px 6px', textAlign: 'right' }}>점수</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.code} style={{ borderTop: '1px solid rgba(255,255,255,0.08)' }}>
                  <td style={{ padding: '8px 6px', fontWeight: 600 }}>{it.name}</td>
                  <td style={{ padding: '8px 6px', color: '#94a3b8' }}>{it.code}</td>
                  <td style={{ padding: '8px 6px', color: '#cbd5e1' }}>{it.sector}</td>
                  <td style={{ padding: '8px 6px', textAlign: 'right', color: '#34d399', fontWeight: 600 }}>{it.score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
