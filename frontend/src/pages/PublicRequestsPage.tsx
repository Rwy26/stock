import { useEffect, useState } from 'react'
import { fetchJson } from '../lib/api'

type Visitor = { id: number; name: string; phone: string; at: string | null }
type AiRequest = { id: number; name: string; phone: string; stock: string; status: string; at: string | null }

export function PublicRequestsPage() {
  const [visitors, setVisitors] = useState<Visitor[]>([])
  const [requests, setRequests] = useState<AiRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      fetchJson<{ items: AiRequest[] }>('/api/admin/public-ai-requests'),
      fetchJson<{ items: Visitor[] }>('/api/admin/public-visitors'),
    ])
      .then(([r, v]) => {
        setRequests(r.items)
        setVisitors(v.items)
      })
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [])

  const th: React.CSSProperties = { padding: '8px 6px', textAlign: 'left', color: '#94a3b8', fontSize: 13 }
  const td: React.CSSProperties = { padding: '8px 6px', borderTop: '1px solid rgba(255,255,255,0.08)' }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>📨 공개 페이지 요청</h2>
      {loading && <p style={{ color: '#94a3b8' }}>불러오는 중…</p>}
      {err && <p style={{ color: '#f87171' }}>불러오기 실패: {err}</p>}

      {!loading && !err && (
        <>
          <h3 style={{ margin: '0 0 8px' }}>AI 차트 분석 요청 ({requests.length})</h3>
          <div className="glass" style={{ padding: 16, marginBottom: 24 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={th}>이름</th>
                  <th style={th}>전화번호</th>
                  <th style={th}>요청 종목</th>
                  <th style={th}>상태</th>
                  <th style={th}>시각</th>
                </tr>
              </thead>
              <tbody>
                {requests.map((r) => (
                  <tr key={r.id}>
                    <td style={td}>{r.name}</td>
                    <td style={td}>{r.phone}</td>
                    <td style={{ ...td, fontWeight: 600 }}>{r.stock}</td>
                    <td style={td}>{r.status}</td>
                    <td style={{ ...td, color: '#94a3b8' }}>{r.at ?? ''}</td>
                  </tr>
                ))}
                {requests.length === 0 && (
                  <tr>
                    <td style={{ ...td, color: '#94a3b8' }} colSpan={5}>
                      요청 없음
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <h3 style={{ margin: '0 0 8px' }}>방문자 ({visitors.length})</h3>
          <div className="glass" style={{ padding: 16 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={th}>이름</th>
                  <th style={th}>전화번호</th>
                  <th style={th}>입장 시각</th>
                </tr>
              </thead>
              <tbody>
                {visitors.map((v) => (
                  <tr key={v.id}>
                    <td style={td}>{v.name}</td>
                    <td style={td}>{v.phone}</td>
                    <td style={{ ...td, color: '#94a3b8' }}>{v.at ?? ''}</td>
                  </tr>
                ))}
                {visitors.length === 0 && (
                  <tr>
                    <td style={{ ...td, color: '#94a3b8' }} colSpan={3}>
                      방문자 없음
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
