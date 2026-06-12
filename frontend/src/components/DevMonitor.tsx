import { useCallback, useEffect, useState } from 'react'
import { fetchJson } from '../lib/api'
import { getUserRole } from '../lib/auth'

// ─── Types ───────────────────────────────────────────────────────────────────

type ScheduledTask = {
  name: string
  found: boolean
  lastRun?: string
  lastResult?: string
  taskStatus?: string
}

type SystemStatus = {
  uptimeSec: number
  startTime: string
  killSwitchOn: boolean
  gitLastCommit: { hash: string; subject: string; time: string }
  scheduledTasks: ScheduledTask[]
  hourlyActivity: { hour: string; count: number }[]
  dataFreshness: { label: string; lastDate: string | null; status: string }[]
}

type PendingItem = {
  id: string
  title: string
  description: string
  status: 'pending' | 'error' | 'ok'
  priority: 'high' | 'medium' | 'low'
}

type ErrorItem = {
  id: number
  engine: string
  event: string
  message: string | null
  at: string | null
  email?: string | null
}

type UserItem = {
  id: number
  email: string
  nickname: string | null
  isActive: boolean
  kisConfigured: boolean
  createdAt: string | null
}

type LoginRecord = {
  userId: number | null
  event: string
  at: string | null
  ip: string | null
}

type ModalState =
  | { kind: 'error'; item: ErrorItem }
  | { kind: 'pending'; item: PendingItem }
  | { kind: 'user'; item: UserItem }
  | { kind: 'task'; task: ScheduledTask }
  | { kind: 'freshness'; label: string; lastDate: string | null; status: string }
  | null

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmt(v: string | null | undefined) {
  if (!v) return '-'
  const d = new Date(v)
  return isNaN(d.getTime()) ? v : d.toLocaleString('ko-KR')
}

function fmtUptime(sec: number) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60)
  return h > 0 ? `${h}시간 ${m}분` : m > 0 ? `${m}분 ${sec % 60}초` : `${sec % 60}초`
}

function taskStatus(t: ScheduledTask): 'ok' | 'warn' | 'error' | 'off' {
  if (!t.found) return 'error'
  if (t.lastResult === '0') return 'ok'
  if (t.lastResult === '267011') return 'warn'
  if (t.lastResult && t.lastResult !== '0') return 'error'
  return 'ok'
}

const DOT: Record<string, string> = {
  ok: 'var(--color-text-success)',
  warn: 'var(--color-text-warning)',
  error: 'var(--color-text-danger)',
  off: 'var(--color-text-tertiary)',
  stale: 'var(--color-text-warning)',
}

// ─── Hourly bar chart ────────────────────────────────────────────────────────

function HourlyChart({ data }: { data: { hour: string; count: number }[] }) {
  const max = Math.max(...data.map(d => d.count), 1)
  const W = 580, barSlot = W / data.length, barW = barSlot - 2, H = 60

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', overflow: 'visible' }}>
      {data.map((d, i) => {
        const bH = d.count > 0 ? Math.max((d.count / max) * (H - 16), 4) : 1
        const x = i * barSlot
        return (
          <g key={d.hour}>
            <rect
              x={x + 1} y={H - bH - 14} width={barW} height={bH} rx={2}
              fill={d.count > 0 ? 'var(--color-text-info)' : 'var(--color-border-tertiary)'}
              opacity={d.count > 0 ? 0.65 : 0.35}
            />
            {i % 3 === 0 && (
              <text
                x={x + barW / 2} y={H - 2}
                textAnchor="middle"
                style={{ fontSize: 9, fill: 'var(--color-text-tertiary)', fontFamily: 'var(--font-sans)' }}
              >
                {d.hour}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

// ─── Modal content ───────────────────────────────────────────────────────────

function ModalContent({
  modal, onClose, onClaude, copied,
}: {
  modal: NonNullable<ModalState>
  onClose: () => void
  onClaude: () => void
  copied: boolean
}) {
  const [history, setHistory] = useState<LoginRecord[] | null>(null)

  useEffect(() => {
    if (modal.kind !== 'user') return
    setHistory(null)
    fetchJson<{ items: LoginRecord[] }>('/api/admin/login-history?limit=50')
      .then(r => setHistory(r.items.filter(h => h.userId === modal.item.id).slice(0, 8)))
      .catch(() => setHistory([]))
  }, [modal])

  const canClaude = modal.kind === 'error' || modal.kind === 'pending'
  const rowStyle: React.CSSProperties = {
    display: 'contents',
  }
  const kStyle: React.CSSProperties = { color: 'var(--color-text-tertiary)', fontSize: 12, paddingTop: 4 }
  const vStyle: React.CSSProperties = { fontSize: 12, color: 'var(--color-text-primary)', paddingTop: 4, wordBreak: 'break-all' }

  const grid = (pairs: [string, string | undefined | null][]) => (
    <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr', gap: '2px 12px', marginBottom: 16 }}>
      {pairs.map(([k, v]) => (
        v !== undefined ? (
          <div key={k} style={rowStyle}>
            <span style={kStyle}>{k}</span>
            <span style={vStyle}>{v ?? '-'}</span>
          </div>
        ) : null
      ))}
    </div>
  )

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 500 }}>
          {modal.kind === 'error' ? '오류 상세' :
           modal.kind === 'pending' ? '미완료 항목' :
           modal.kind === 'user' ? '사용자 정보' :
           modal.kind === 'task' ? modal.task.name :
           modal.kind === 'freshness' ? modal.label : '상세'}
        </h3>
        <button className="btn secondary" style={{ padding: '2px 10px', fontSize: 12 }} onClick={onClose}>닫기</button>
      </div>

      {modal.kind === 'error' && grid([
        ['엔진', modal.item.engine],
        ['이벤트', modal.item.event],
        ['메시지', modal.item.message ?? '(없음)'],
        ['발생 시각', fmt(modal.item.at)],
        ['사용자', modal.item.email ?? '-'],
      ])}

      {modal.kind === 'pending' && grid([
        ['항목', modal.item.title],
        ['설명', modal.item.description],
        ['우선순위', modal.item.priority === 'high' ? '높음' : modal.item.priority === 'medium' ? '중간' : '낮음'],
        ['상태', modal.item.status === 'error' ? '오류' : modal.item.status === 'ok' ? '완료' : '대기 중'],
      ])}

      {modal.kind === 'task' && grid([
        ['작업 이름', modal.task.name],
        ['등록', modal.task.found ? '등록됨' : '미등록'],
        ['상태', modal.task.taskStatus ?? '-'],
        ['마지막 실행', modal.task.lastRun ?? '-'],
        ['결과 코드', modal.task.lastResult === '0' ? '성공 (0)' : modal.task.lastResult === '267011' ? '미실행 (267011)' : modal.task.lastResult ?? '-'],
      ])}

      {modal.kind === 'freshness' && grid([
        ['데이터', modal.label],
        ['마지막 날짜', modal.lastDate ?? '없음'],
        ['상태', modal.status === 'ok' ? '정상' : modal.status === 'stale' ? '오래됨 / 미수집' : '오류'],
      ])}

      {modal.kind === 'user' && (
        <>
          {grid([
            ['이메일', modal.item.email],
            ['닉네임', modal.item.nickname ?? '-'],
            ['활성', modal.item.isActive ? '활성' : '비활성'],
            ['KIS 설정', modal.item.kisConfigured ? '설정됨' : '미설정'],
            ['가입일', fmt(modal.item.createdAt)],
          ])}
          <p style={{ fontSize: 12, fontWeight: 500, marginBottom: 6, color: 'var(--color-text-secondary)' }}>최근 로그인 이력</p>
          {history === null ? (
            <p style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>불러오는 중…</p>
          ) : history.length === 0 ? (
            <p style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>이력 없음</p>
          ) : (
            <div style={{ border: '0.5px solid var(--color-border-tertiary)', borderRadius: 6, overflow: 'hidden' }}>
              {history.map((h, i) => (
                <div key={i} style={{ display: 'grid', gridTemplateColumns: '60px 1fr 80px', fontSize: 12, padding: '5px 10px', borderBottom: i < history.length - 1 ? '0.5px solid var(--color-border-tertiary)' : 'none', background: i % 2 === 0 ? 'var(--color-background-secondary)' : 'transparent' }}>
                  <span style={{ color: h.event === 'login' ? 'var(--color-text-success)' : 'var(--color-text-secondary)' }}>{h.event}</span>
                  <span style={{ color: 'var(--color-text-tertiary)' }}>{fmt(h.at)}</span>
                  <span style={{ color: 'var(--color-text-tertiary)', textAlign: 'right' }}>{h.ip ?? '-'}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {canClaude && (
        <div style={{ borderTop: '0.5px solid var(--color-border-tertiary)', marginTop: 12, paddingTop: 12, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <button className="btn" style={{ fontSize: 12 }} onClick={onClaude}>
            {copied ? '✓ 복사됨 — Claude에 붙여넣기' : 'Claude로 수정'}
          </button>
          <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>
            프롬프트를 클립보드에 복사하고 claude.ai를 엽니다
          </span>
        </div>
      )}
    </>
  )
}

// ─── Sub-panel wrapper ────────────────────────────────────────────────────────

function SubPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ background: 'var(--color-background-secondary)', border: '0.5px solid var(--color-border-tertiary)', borderRadius: 'var(--border-radius-md)', padding: '10px 12px' }}>
      <p style={{ fontSize: 10, fontWeight: 500, color: 'var(--color-text-secondary)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 8 }}>
        {title}
      </p>
      {children}
    </div>
  )
}

function ClickRow({ left, right, onClick, dotColor }: { left: React.ReactNode; right?: React.ReactNode; onClick: () => void; dotColor?: string }) {
  return (
    <div
      onClick={onClick}
      style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0', borderBottom: '0.5px solid var(--color-border-tertiary)', cursor: 'pointer' }}
      className="dev-row"
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
        {dotColor && <span style={{ width: 6, height: 6, borderRadius: '50%', background: dotColor, flexShrink: 0 }} />}
        <span style={{ fontSize: 12, color: 'var(--color-text-primary)' }}>{left}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        {right && <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>{right}</span>}
        <span style={{ fontSize: 12, color: 'var(--color-text-info)', opacity: 0.7 }}>›</span>
      </div>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export function DevMonitor() {
  const role = getUserRole()

  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [pending, setPending] = useState<PendingItem[]>([])
  const [errors, setErrors] = useState<ErrorItem[]>([])
  const [users, setUsers] = useState<UserItem[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null)
  const [modal, setModal] = useState<ModalState>(null)
  const [copied, setCopied] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    const [sysR, pendR, errR, usrR] = await Promise.allSettled([
      fetchJson<SystemStatus>('/api/admin/system-status'),
      fetchJson<{ items: PendingItem[] }>('/api/admin/pending-items'),
      fetchJson<{ items: ErrorItem[] }>('/api/admin/engine-logs?event=error&limit=5'),
      fetchJson<{ items: UserItem[] }>('/api/admin/users'),
    ])
    if (sysR.status === 'fulfilled') setStatus(sysR.value)
    if (pendR.status === 'fulfilled') setPending(pendR.value.items)
    if (errR.status === 'fulfilled') setErrors(errR.value.items)
    if (usrR.status === 'fulfilled') setUsers(usrR.value.items)
    setRefreshedAt(new Date())
    setLoading(false)
  }, [])

  useEffect(() => { void load() }, [load])

  if (role !== 'admin') return null

  const buildPrompt = (m: ModalState): string => {
    if (!m) return ''
    if (m.kind === 'error') {
      return `MOON STOCK 시스템 오류를 해결해주세요:\n\n엔진: ${m.item.engine}\n이벤트: ${m.item.event}\n메시지: ${m.item.message ?? '(없음)'}\n발생 시각: ${fmt(m.item.at)}\n사용자: ${m.item.email ?? '-'}\n\n백엔드 경로: C:\\stock\\backend\\main.py\n에러 로그를 분석하고 해결 방법을 제안해주세요.`
    }
    if (m.kind === 'pending') {
      return `MOON STOCK 미완료 항목을 해결해주세요:\n\n항목: ${m.item.title}\n설명: ${m.item.description}\n우선순위: ${m.item.priority}\n\n관련 경로:\n- 백엔드: C:\\stock\\backend\\main.py\n- 스크립트: C:\\stock\\scripts\\\n\n해결 방법을 제안하고 구현해주세요.`
    }
    return ''
  }

  const openClaude = () => {
    const prompt = buildPrompt(modal)
    if (!prompt) return
    navigator.clipboard.writeText(prompt).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 3000)
    window.open('https://claude.ai/', '_blank', 'noopener,noreferrer')
  }

  // Health card data
  const healthCards = [
    {
      name: '백엔드 가동',
      st: status ? 'ok' : 'off',
      val: status ? fmtUptime(status.uptimeSec) : '-',
      sub: status ? `시작 ${fmt(status.startTime).slice(0, 17)}` : '-',
    },
    {
      name: '킬스위치',
      st: status?.killSwitchOn ? 'warn' : 'ok',
      val: status?.killSwitchOn ? 'ON (정지)' : 'OFF (정상)',
      sub: '',
    },
    {
      name: 'Git 커밋',
      st: status?.gitLastCommit?.hash ? 'ok' : 'off',
      val: status?.gitLastCommit?.hash ? `${status.gitLastCommit.hash}` : '-',
      sub: status?.gitLastCommit?.subject?.slice(0, 28) ?? '',
    },
    {
      name: '스케줄 작업',
      st: (status?.scheduledTasks ?? []).some(t => taskStatus(t) === 'error') ? 'error'
        : (status?.scheduledTasks ?? []).some(t => taskStatus(t) === 'warn') ? 'warn' : 'ok',
      val: (() => {
        const tasks = status?.scheduledTasks ?? []
        const ok = tasks.filter(t => taskStatus(t) === 'ok').length
        return `${ok} / ${tasks.length} 정상`
      })(),
      sub: '',
    },
  ] as const

  const priorityBg = (p: PendingItem['priority']) =>
    p === 'high' ? 'var(--color-background-danger)' : p === 'medium' ? 'var(--color-background-warning)' : 'var(--color-background-info)'
  const priorityColor = (p: PendingItem['priority']) =>
    p === 'high' ? 'var(--color-text-danger)' : p === 'medium' ? 'var(--color-text-warning)' : 'var(--color-text-info)'
  const priorityLabel = (p: PendingItem['priority']) =>
    p === 'high' ? '높음' : p === 'medium' ? '중간' : '낮음'

  return (
    <>
      <style>{`.dev-row:hover{background:var(--color-background-secondary);border-radius:4px;}`}</style>

      {/* Modal overlay */}
      {modal && (
        <div
          onClick={() => setModal(null)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 300, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{ background: 'var(--color-background-primary)', border: '0.5px solid var(--color-border-secondary)', borderRadius: 'var(--border-radius-lg)', padding: '20px 24px', maxWidth: 520, width: '90%', maxHeight: '82vh', overflowY: 'auto' }}
          >
            <ModalContent modal={modal} onClose={() => setModal(null)} onClaude={openClaude} copied={copied} />
          </div>
        </div>
      )}

      <article className="panel glass reveal" style={{ gridColumn: '1 / -1' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <h3 style={{ margin: 0 }}>개발자 모니터</h3>
            <span style={{ fontSize: 10, fontWeight: 500, padding: '2px 7px', background: 'var(--color-background-info)', color: 'var(--color-text-info)', borderRadius: 4 }}>Admin only</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {refreshedAt && (
              <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>
                {refreshedAt.toLocaleTimeString('ko-KR')} 갱신
              </span>
            )}
            <button className="btn secondary" style={{ fontSize: 12, padding: '3px 10px' }} disabled={loading} onClick={() => void load()}>
              {loading ? '…' : '새로고침'}
            </button>
          </div>
        </div>

        {/* Row 1: 최근 오류 + 미완료 항목 (TOP) */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
          <SubPanel title="최근 오류">
            {errors.length === 0 ? (
              <p style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>오류 없음</p>
            ) : errors.map(e => (
              <ClickRow
                key={e.id}
                dotColor="var(--color-text-danger)"
                left={
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ fontSize: 10, fontWeight: 500, padding: '1px 5px', background: 'var(--color-background-danger)', color: 'var(--color-text-danger)', borderRadius: 100 }}>error</span>
                    {e.engine} — {(e.message ?? '').slice(0, 28) || '(없음)'}
                  </span>
                }
                right={e.at ? new Date(e.at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }) : '-'}
                onClick={() => setModal({ kind: 'error', item: e })}
              />
            ))}
          </SubPanel>

          <SubPanel title="미완료 항목">
            {pending.length === 0 ? (
              <p style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>미완료 항목 없음</p>
            ) : pending.map(p => (
              <ClickRow
                key={p.id}
                left={
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ fontSize: 10, fontWeight: 500, padding: '1px 5px', background: priorityBg(p.priority), color: priorityColor(p.priority), borderRadius: 100, flexShrink: 0 }}>{priorityLabel(p.priority)}</span>
                    {p.title}
                  </span>
                }
                onClick={() => setModal({ kind: 'pending', item: p })}
              />
            ))}
          </SubPanel>
        </div>

        {/* Row 2: 시스템 헬스 + 시간별 차트 */}
        <SubPanel title="시스템 헬스">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
            {healthCards.map(h => (
              <div
                key={h.name}
                onClick={() => {
                  if (h.name === '스케줄 작업') return
                  setModal({ kind: 'task', task: { name: h.name, found: h.st !== 'off', taskStatus: h.val } })
                }}
                style={{ background: 'var(--color-background-primary)', border: '0.5px solid var(--color-border-tertiary)', borderRadius: 'var(--border-radius-md)', padding: '8px 10px', cursor: 'pointer' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 3 }}>
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: DOT[h.st] ?? DOT.off, flexShrink: 0 }} />
                  <span style={{ fontSize: 10, color: 'var(--color-text-tertiary)' }}>{h.name}</span>
                </div>
                <p style={{ fontSize: 12, fontWeight: 500, color: 'var(--color-text-primary)', margin: 0 }}>{h.val}</p>
                {h.sub && <p style={{ fontSize: 10, color: 'var(--color-text-tertiary)', margin: '2px 0 0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{h.sub}</p>}
              </div>
            ))}
          </div>
          <p style={{ fontSize: 10, color: 'var(--color-text-tertiary)', marginBottom: 4 }}>최근 12시간 활동 (로그인 + 엔진 이벤트)</p>
          {(status?.hourlyActivity?.length ?? 0) > 0
            ? <HourlyChart data={status!.hourlyActivity} />
            : <div style={{ height: 60, background: 'var(--color-border-tertiary)', borderRadius: 4, opacity: 0.25 }} />}
        </SubPanel>

        {/* Row 3: 데이터 신선도 + 사용자 현황 */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 10 }}>
          {/* 데이터 신선도 */}
          <SubPanel title="데이터 신선도">
            {(status?.scheduledTasks ?? []).map(t => (
              <ClickRow
                key={t.name}
                dotColor={DOT[taskStatus(t)]}
                left={t.name.replace('MOON-STOCK-', '')}
                right={t.lastRun ?? '-'}
                onClick={() => setModal({ kind: 'task', task: t })}
              />
            ))}
            {(status?.dataFreshness ?? []).map(f => (
              <ClickRow
                key={f.label}
                dotColor={DOT[f.status] ?? DOT.off}
                left={f.label}
                right={f.lastDate ?? '없음'}
                onClick={() => setModal({ kind: 'freshness', label: f.label, lastDate: f.lastDate, status: f.status })}
              />
            ))}
          </SubPanel>

          {/* 사용자 현황 */}
          <SubPanel title="사용자 현황">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6, marginBottom: 10 }}>
              {[
                { label: '전체', val: users.length },
                { label: '활성', val: users.filter(u => u.isActive).length },
                { label: 'KIS 설정', val: users.filter(u => u.kisConfigured).length },
              ].map(s => (
                <div key={s.label} style={{ background: 'var(--color-background-primary)', border: '0.5px solid var(--color-border-tertiary)', borderRadius: 'var(--border-radius-md)', padding: '6px 8px' }}>
                  <p style={{ fontSize: 10, color: 'var(--color-text-tertiary)', margin: '0 0 2px' }}>{s.label}</p>
                  <p style={{ fontSize: 17, fontWeight: 500, color: 'var(--color-text-primary)', margin: 0 }}>{s.val}</p>
                </div>
              ))}
            </div>
            {users.map(u => (
              <ClickRow
                key={u.id}
                dotColor={u.isActive ? 'var(--color-text-success)' : 'var(--color-text-tertiary)'}
                left={
                  <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    {u.email}
                    {u.nickname && <span style={{ fontSize: 10, color: 'var(--color-text-tertiary)' }}>({u.nickname})</span>}
                    {u.kisConfigured && <span style={{ fontSize: 9, fontWeight: 500, padding: '1px 4px', background: 'var(--color-background-success)', color: 'var(--color-text-success)', borderRadius: 100 }}>KIS</span>}
                  </span>
                }
                onClick={() => setModal({ kind: 'user', item: u })}
              />
            ))}
          </SubPanel>
        </div>
      </article>
    </>
  )
}
