import { useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { getGuest, publicFetch } from '../../lib/publicApi'

const inputStyle: CSSProperties = {
  width: '100%',
  padding: '10px 12px',
  margin: '6px 0 14px',
  borderRadius: 8,
  border: '1px solid rgba(255,255,255,0.15)',
  background: 'rgba(255,255,255,0.05)',
  color: '#f1f5f9',
  boxSizing: 'border-box',
}

export function PublicAiRequestPage() {
  const [stock, setStock] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    const guest = getGuest()
    const q = stock.trim()
    if (!guest) {
      setErr('게스트 정보가 없습니다. 다시 입장해 주세요.')
      return
    }
    if (!q) {
      setErr('분석을 원하는 종목명을 입력하세요.')
      return
    }
    setBusy(true)
    setErr(null)
    setDone(null)
    try {
      const res = await publicFetch<{ ok: boolean; message?: string }>('/api/public/ai-request', {
        method: 'POST',
        body: JSON.stringify({ name: guest.name, phone: guest.phone, stock: q }),
      })
      setDone(res.message ?? '요청이 접수되었습니다.')
      setStock('')
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <h2 style={{ marginBottom: 4 }}>🤖 AI 종목 분석 요청</h2>
      <p style={{ color: '#94a3b8', fontSize: 13, marginBottom: 16, lineHeight: 1.6 }}>
        분석을 원하는 종목명을 입력하면 요청이 접수됩니다. 실제 AI 분석은 관리자가 수행한 뒤 처리합니다.
        <br />
        (이 페이지에서는 분석이 즉시 실행되지 않습니다.)
      </p>

      <form className="glass" onSubmit={submit} style={{ padding: 24, maxWidth: 440 }}>
        <label style={{ fontSize: 13, color: '#cbd5e1' }}>종목명</label>
        <input
          value={stock}
          onChange={(e) => setStock(e.target.value)}
          placeholder="예: 삼성전자, SK하이닉스"
          style={inputStyle}
        />
        {err && <p style={{ color: '#f87171', fontSize: 13, margin: '0 0 8px' }}>{err}</p>}
        {done && <p style={{ color: '#34d399', fontSize: 13, margin: '0 0 8px' }}>✅ {done}</p>}
        <button className="btn" type="submit" disabled={busy} style={{ width: '100%' }}>
          {busy ? '접수 중…' : '분석 요청하기'}
        </button>
      </form>
    </div>
  )
}
