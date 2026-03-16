import { useEffect, useMemo, useState } from 'react'
import { fetchJson } from '../lib/api'

type AdminUser = {
  id: number
  email: string
  nickname: string | null
  role: string
  isActive: boolean
  kisConfigured: boolean
  createdAt: string | null
}

type AdminUsersResponse = {
  items: AdminUser[]
}

type LoginHistoryItem = {
  id: number
  userId: number | null
  email?: string | null
  event: string
  ip: string | null
  userAgent: string | null
  at: string | null
}

type LoginHistoryResponse = {
  items: LoginHistoryItem[]
}

type EngineLogItem = {
  id: number
  userId: number
  email?: string | null
  engine: string
  event: string
  message: string | null
  at: string | null
}

type EngineLogsResponse = {
  items: EngineLogItem[]
}

type AdminKisProfile = {
  userId: number
  appKey: string | null
  accountPrefix: string | null
  tradeType: '실계좌' | '모의투자'
  hasAppSecret: boolean
}

type AdminAutomation = {
  userId: number
  saEnabled: boolean
  plusEnabled: boolean
  svEnabled: boolean
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('ko-KR')
}

export function AdminPage() {
  const [users, setUsers] = useState<AdminUser[] | null>(null)
  const [loginHistory, setLoginHistory] = useState<LoginHistoryItem[] | null>(null)
  const [engineLogs, setEngineLogs] = useState<EngineLogItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const [createEmail, setCreateEmail] = useState('')
  const [createPassword, setCreatePassword] = useState('')
  const [createNickname, setCreateNickname] = useState('')
  const [createRole, setCreateRole] = useState<'user' | 'admin'>('user')
  const [createIsActive, setCreateIsActive] = useState(true)
  const [actionMessage, setActionMessage] = useState<string | null>(null)

  const [historyStartDate, setHistoryStartDate] = useState('')
  const [historyEndDate, setHistoryEndDate] = useState('')
  const [historyEventFilter, setHistoryEventFilter] = useState<'all' | 'login' | 'logout'>('all')

  const [kisUserId, setKisUserId] = useState<number | null>(null)
  const [kisLoading, setKisLoading] = useState(false)
  const [kisProfile, setKisProfile] = useState<AdminKisProfile | null>(null)
  const [kisAppKey, setKisAppKey] = useState('')
  const [kisAccountPrefix, setKisAccountPrefix] = useState('')
  const [kisTradeType, setKisTradeType] = useState<'실계좌' | '모의투자'>('실계좌')
  const [kisAppSecret, setKisAppSecret] = useState('')

  const [autoUserId, setAutoUserId] = useState<number | null>(null)
  const [autoLoading, setAutoLoading] = useState(false)
  const [autoCfg, setAutoCfg] = useState<AdminAutomation | null>(null)
  const [autoSaEnabled, setAutoSaEnabled] = useState(false)
  const [autoPlusEnabled, setAutoPlusEnabled] = useState(false)
  const [autoSvEnabled, setAutoSvEnabled] = useState(false)

  const isAdminOnlyMessage = useMemo(() => {
    if (!error) return false
    return /403/.test(error) || /Admin only/i.test(error)
  }, [error])

  const load = async (opts?: { startDate?: string; endDate?: string }) => {
    setLoading(true)
    setError(null)
    const qs = new URLSearchParams({ limit: '200' })
    if (opts?.startDate) qs.set('startDate', opts.startDate)
    if (opts?.endDate) qs.set('endDate', opts.endDate)

    const engineQs = new URLSearchParams({ limit: '200' })

    try {
      const [usersRes, historyRes, engineLogsRes] = await Promise.all([
        fetchJson<AdminUsersResponse>('/api/admin/users'),
        fetchJson<LoginHistoryResponse>(`/api/admin/login-history?${qs.toString()}`),
        fetchJson<EngineLogsResponse>(`/api/admin/engine-logs?${engineQs.toString()}`),
      ])
      setUsers(usersRes.items)
      setLoginHistory(historyRes.items)
      setEngineLogs(engineLogsRes.items)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setUsers(null)
      setLoginHistory(null)
      setEngineLogs(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    void (async () => {
      await load()
      if (cancelled) return
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const filteredLoginHistory = useMemo(() => {
    const items = loginHistory ?? []
    if (historyEventFilter === 'all') return items
    return items.filter((r) => (r.event || '').toLowerCase() === historyEventFilter)
  }, [loginHistory, historyEventFilter])

  const renderEvent = (event: string) => {
    const normalized = (event || '').toLowerCase()
    if (normalized === 'login') return { label: '로그인', cls: 'chip on' }
    if (normalized === 'logout') return { label: '로그아웃', cls: 'chip off' }
    return { label: event || '-', cls: 'chip' }
  }

  const renderEngineEvent = (event: string) => {
    const normalized = (event || '').toLowerCase()
    if (normalized === 'tick') return { label: 'tick', cls: 'chip on' }
    if (normalized === 'error') return { label: 'error', cls: 'chip off' }
    return { label: event || '-', cls: 'chip' }
  }

  return (
    <>
      <header className="topbar glass">
        <div>
          <p className="top-label">Admin</p>
          <h2>관리자 기능</h2>
          <p className="subtle">사용자 목록 / 로그인 이력</p>
        </div>
        <div className="status-pill">관리자 전용</div>
      </header>

      {error ? (
        <section className="panel glass reveal">
          <div className="panel-head">
            <h3>오류</h3>
          </div>
          <p className="hint">
            {isAdminOnlyMessage ? '관리자 계정만 접근할 수 있습니다.' : error}
          </p>
        </section>
      ) : null}

      <section className="panel glass reveal">
        <div className="panel-head">
          <h3>사용자 목록</h3>
          {loading ? <div className="hint">불러오는 중…</div> : null}
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>이메일</th>
                <th>닉네임</th>
                <th>역할</th>
                <th>가입일</th>
                <th>활성</th>
                <th>KIS</th>
                <th>KIS 설정</th>
                <th>활성 변경</th>
                <th>비밀번호</th>
                <th>자동매매</th>
              </tr>
            </thead>
            <tbody>
              {(users ?? []).map((u) => (
                <tr key={u.id}>
                  <td>{u.email}</td>
                  <td>{u.nickname ?? '-'}</td>
                  <td>
                    {u.role === 'admin' ? <b>admin</b> : u.role}
                  </td>
                  <td>{formatDate(u.createdAt)}</td>
                  <td>
                    <span className={`chip ${u.isActive ? 'on' : ''}`}>{u.isActive ? 'ON' : 'OFF'}</span>
                  </td>
                  <td>
                    <span className={`chip ${u.kisConfigured ? 'on' : ''}`}>{u.kisConfigured ? 'ON' : 'OFF'}</span>
                  </td>
                  <td>
                    <button
                      className="btn secondary"
                      type="button"
                      disabled={loading || kisLoading || autoLoading}
                      onClick={async () => {
                        setActionMessage(null)
                        setError(null)
                        setKisUserId(u.id)
                        setKisLoading(true)
                        setAutoUserId(null)
                        setAutoCfg(null)
                        try {
                          const prof = await fetchJson<AdminKisProfile>(`/api/admin/users/${encodeURIComponent(String(u.id))}/kis-profile`)
                          setKisProfile(prof)
                          setKisAppKey(prof.appKey ?? '')
                          setKisAccountPrefix(prof.accountPrefix ?? '')
                          setKisTradeType(prof.tradeType)
                          setKisAppSecret('')
                        } catch (e) {
                          setActionMessage(e instanceof Error ? e.message : String(e))
                          setKisProfile(null)
                        } finally {
                          setKisLoading(false)
                        }
                      }}
                    >
                      설정
                    </button>
                  </td>

                  <td>
                    <button
                      className="btn secondary"
                      type="button"
                      disabled={loading || kisLoading || autoLoading}
                      onClick={async () => {
                        setActionMessage(null)
                        setError(null)
                        try {
                          await fetchJson(`/api/admin/users/${encodeURIComponent(String(u.id))}/activation`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ isActive: !u.isActive }),
                          })
                          setActionMessage(`사용자 활성 상태를 ${!u.isActive ? 'ON' : 'OFF'}로 변경했습니다.`)
                          await load({ startDate: historyStartDate || undefined, endDate: historyEndDate || undefined })
                        } catch (e) {
                          setActionMessage(e instanceof Error ? e.message : String(e))
                        }
                      }}
                    >
                      {u.isActive ? 'OFF' : 'ON'}
                    </button>
                  </td>

                  <td>
                    <button
                      className="btn secondary"
                      type="button"
                      disabled={loading || kisLoading || autoLoading}
                      onClick={async () => {
                        setActionMessage(null)
                        setError(null)
                        try {
                          const res = await fetchJson<{ ok: boolean; tempPassword: string | null }>(
                            `/api/admin/users/${encodeURIComponent(String(u.id))}/reset-password`,
                            { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) },
                          )
                          setActionMessage(
                            res.tempPassword
                              ? `임시 비밀번호: ${res.tempPassword}`
                              : '비밀번호를 초기화했습니다.',
                          )
                        } catch (e) {
                          setActionMessage(e instanceof Error ? e.message : String(e))
                        }
                      }}
                    >
                      초기화
                    </button>
                  </td>

                  <td>
                    <button
                      className="btn secondary"
                      type="button"
                      disabled={loading || kisLoading || autoLoading}
                      onClick={async () => {
                        setActionMessage(null)
                        setError(null)
                        setAutoUserId(u.id)
                        setAutoLoading(true)
                        setKisUserId(null)
                        setKisProfile(null)
                        try {
                          const cfg = await fetchJson<AdminAutomation>(`/api/admin/users/${encodeURIComponent(String(u.id))}/automation`)
                          setAutoCfg(cfg)
                          setAutoSaEnabled(cfg.saEnabled)
                          setAutoPlusEnabled(cfg.plusEnabled)
                          setAutoSvEnabled(cfg.svEnabled)
                        } catch (e) {
                          setActionMessage(e instanceof Error ? e.message : String(e))
                          setAutoCfg(null)
                        } finally {
                          setAutoLoading(false)
                        }
                      }}
                    >
                      설정
                    </button>
                  </td>
                </tr>
              ))}
              {!loading && (users ?? []).length === 0 ? (
                <tr>
                  <td colSpan={10} className="hint">
                    데이터가 없습니다.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        {kisUserId != null ? (
          <>
            <div className="divider"></div>
            <div className="panel-head">
              <h3>사용자 KIS 설정</h3>
              {kisLoading ? <div className="hint">불러오는 중…</div> : null}
            </div>
            <div className="form-row">
              <label>
                App Key
                <input value={kisAppKey} onChange={(e) => setKisAppKey(e.target.value)} placeholder="KIS App Key" />
              </label>
              <label>
                App Secret
                <input
                  value={kisAppSecret}
                  onChange={(e) => setKisAppSecret(e.target.value)}
                  placeholder={kisProfile?.hasAppSecret ? '******** (변경 시에만 입력)' : 'KIS App Secret'}
                  type="password"
                />
              </label>
              <label>
                계좌번호(앞 8자리)
                <input value={kisAccountPrefix} onChange={(e) => setKisAccountPrefix(e.target.value)} placeholder="예: 12345678" />
              </label>
            </div>
            <div className="form-row">
              <label>
                거래 구분
                <select value={kisTradeType} onChange={(e) => setKisTradeType(e.target.value === '모의투자' ? '모의투자' : '실계좌')}>
                  <option value="실계좌">실계좌</option>
                  <option value="모의투자">모의투자</option>
                </select>
              </label>
              <label>
                액션
                <button
                  className="btn"
                  type="button"
                  disabled={loading || kisLoading}
                  onClick={async () => {
                    if (kisUserId == null) return
                    setActionMessage(null)
                    try {
                      const body: Record<string, unknown> = {
                        appKey: kisAppKey.trim() || null,
                        accountPrefix: kisAccountPrefix.trim() || null,
                        tradeType: kisTradeType,
                      }
                      const secret = kisAppSecret.trim()
                      if (secret) body.appSecret = secret

                      await fetchJson<{ ok: boolean }>(`/api/admin/users/${encodeURIComponent(String(kisUserId))}/kis-profile`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body),
                      })

                      setKisAppSecret('')
                      setActionMessage('KIS 설정을 저장했습니다.')
                      await load({ startDate: historyStartDate || undefined, endDate: historyEndDate || undefined })
                    } catch (e) {
                      setActionMessage(e instanceof Error ? e.message : String(e))
                    }
                  }}
                >
                  저장
                </button>
                <button
                  className="btn secondary"
                  type="button"
                  disabled={loading || kisLoading}
                  onClick={() => {
                    setKisUserId(null)
                    setKisProfile(null)
                    setKisAppKey('')
                    setKisAccountPrefix('')
                    setKisTradeType('실계좌')
                    setKisAppSecret('')
                  }}
                  style={{ marginLeft: 8 }}
                >
                  닫기
                </button>
              </label>
            </div>
            <p className="hint" style={{ marginTop: 10 }}>
              App Secret은 보안상 조회로 반환하지 않으며, 변경 시에만 입력합니다.
            </p>
          </>
        ) : null}

        {autoUserId != null ? (
          <>
            <div className="divider"></div>
            <div className="panel-head">
              <h3>사용자 자동매매 설정</h3>
              {autoLoading ? <div className="hint">불러오는 중…</div> : null}
            </div>
            <div className="form-row">
              <label>
                SA
                <select value={autoSaEnabled ? 'on' : 'off'} onChange={(e) => setAutoSaEnabled(e.target.value === 'on')}>
                  <option value="off">OFF</option>
                  <option value="on">ON</option>
                </select>
              </label>
              <label>
                Plus
                <select value={autoPlusEnabled ? 'on' : 'off'} onChange={(e) => setAutoPlusEnabled(e.target.value === 'on')}>
                  <option value="off">OFF</option>
                  <option value="on">ON</option>
                </select>
              </label>
              <label>
                SV
                <select value={autoSvEnabled ? 'on' : 'off'} onChange={(e) => setAutoSvEnabled(e.target.value === 'on')}>
                  <option value="off">OFF</option>
                  <option value="on">ON</option>
                </select>
              </label>
            </div>
            <div className="form-row">
              <label>
                액션
                <button
                  className="btn"
                  type="button"
                  disabled={loading || kisLoading || autoLoading}
                  onClick={async () => {
                    if (autoUserId == null) return
                    setActionMessage(null)
                    try {
                      await fetchJson<AdminAutomation>(`/api/admin/users/${encodeURIComponent(String(autoUserId))}/automation`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                          saEnabled: autoSaEnabled,
                          plusEnabled: autoPlusEnabled,
                          svEnabled: autoSvEnabled,
                        }),
                      })
                      setActionMessage('자동매매 설정을 저장했습니다.')
                      await load({ startDate: historyStartDate || undefined, endDate: historyEndDate || undefined })
                    } catch (e) {
                      setActionMessage(e instanceof Error ? e.message : String(e))
                    }
                  }}
                >
                  저장
                </button>
                <button
                  className="btn secondary"
                  type="button"
                  disabled={loading || kisLoading || autoLoading}
                  onClick={() => {
                    setAutoUserId(null)
                    setAutoCfg(null)
                    setAutoSaEnabled(false)
                    setAutoPlusEnabled(false)
                    setAutoSvEnabled(false)
                  }}
                  style={{ marginLeft: 8 }}
                >
                  닫기
                </button>
              </label>
            </div>
            {autoCfg ? (
              <p className="hint" style={{ marginTop: 10 }}>
                현재 상태: SA {autoCfg.saEnabled ? 'ON' : 'OFF'} / Plus {autoCfg.plusEnabled ? 'ON' : 'OFF'} / SV {autoCfg.svEnabled ? 'ON' : 'OFF'}
              </p>
            ) : null}
          </>
        ) : null}

        <div className="divider"></div>

        <div className="panel-head">
          <h3>사용자 생성</h3>
          {actionMessage ? <div className="hint">{actionMessage}</div> : null}
        </div>
        <div className="form-row">
          <label>
            이메일
            <input value={createEmail} onChange={(e) => setCreateEmail(e.target.value)} placeholder="email" />
          </label>
          <label>
            비밀번호
            <input value={createPassword} onChange={(e) => setCreatePassword(e.target.value)} placeholder="password" type="password" />
          </label>
          <label>
            닉네임(선택)
            <input value={createNickname} onChange={(e) => setCreateNickname(e.target.value)} placeholder="nickname" />
          </label>
        </div>
        <div className="form-row">
          <label>
            역할
            <select value={createRole} onChange={(e) => setCreateRole(e.target.value === 'admin' ? 'admin' : 'user')}>
              <option value="user">user</option>
              <option value="admin">admin</option>
            </select>
          </label>
          <label>
            활성
            <select value={createIsActive ? 'on' : 'off'} onChange={(e) => setCreateIsActive(e.target.value === 'on')}>
              <option value="on">ON</option>
              <option value="off">OFF</option>
            </select>
          </label>
          <label>
            액션
            <button
              className="btn"
              type="button"
              disabled={loading}
              onClick={async () => {
                setActionMessage(null)
                try {
                  const email = createEmail.trim()
                  const password = createPassword
                  if (!email || !password) {
                    setActionMessage('이메일과 비밀번호를 입력해 주세요.')
                    return
                  }

                  await fetchJson('/api/admin/users', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      email,
                      password,
                      nickname: createNickname.trim() || null,
                      role: createRole,
                      isActive: createIsActive,
                    }),
                  })

                  setCreateEmail('')
                  setCreatePassword('')
                  setCreateNickname('')
                  setCreateRole('user')
                  setCreateIsActive(true)
                  setActionMessage('사용자를 생성했습니다.')
                  await load({ startDate: historyStartDate || undefined, endDate: historyEndDate || undefined })
                } catch (e) {
                  setActionMessage(e instanceof Error ? e.message : String(e))
                }
              }}
            >
              사용자 생성
            </button>
          </label>
        </div>
      </section>

      <section className="panel glass reveal">
        <div className="panel-head">
          <h3>로그인 이력</h3>
          {loading ? <div className="hint">불러오는 중…</div> : null}
        </div>

        <div className="form-row">
          <label>
            시작일
            <input type="date" value={historyStartDate} onChange={(e) => setHistoryStartDate(e.target.value)} />
          </label>
          <label>
            종료일
            <input type="date" value={historyEndDate} onChange={(e) => setHistoryEndDate(e.target.value)} />
          </label>
          <label>
            이벤트
            <select value={historyEventFilter} onChange={(e) => setHistoryEventFilter(e.target.value as 'all' | 'login' | 'logout')}>
              <option value="all">전체</option>
              <option value="login">로그인</option>
              <option value="logout">로그아웃</option>
            </select>
          </label>
          <label>
            액션
            <button
              className="btn"
              type="button"
              disabled={loading}
              onClick={async () => {
                await load({
                  startDate: historyStartDate || undefined,
                  endDate: historyEndDate || undefined,
                })
              }}
            >
              조회
            </button>
          </label>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>시각</th>
                <th>이메일</th>
                <th>이벤트</th>
                <th>IP</th>
                <th>브라우저</th>
              </tr>
            </thead>
            <tbody>
              {filteredLoginHistory.map((r) => (
                <tr key={r.id}>
                  <td>{formatDate(r.at)}</td>
                  <td>{r.email ?? (r.userId != null ? `user#${r.userId}` : '-')}</td>
                  <td>
                    <span className={renderEvent(r.event).cls}>{renderEvent(r.event).label}</span>
                  </td>
                  <td>{r.ip ?? '-'}</td>
                  <td>{r.userAgent ?? '-'}</td>
                </tr>
              ))}
              {!loading && filteredLoginHistory.length === 0 ? (
                <tr>
                  <td colSpan={5} className="hint">
                    데이터가 없습니다.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel glass reveal">
        <div className="panel-head">
          <h3>자동매매 엔진 로그</h3>
          {loading ? <div className="hint">불러오는 중…</div> : null}
        </div>
        <p className="hint" style={{ marginTop: 8 }}>
          dry-run tick 로그(평일 09:00~15:20). 서버에서 AUTOTRADING_KILL_SWITCH=1이면 기록되지 않습니다.
        </p>

        <div className="table-wrap" style={{ marginTop: 10 }}>
          <table>
            <thead>
              <tr>
                <th>시각</th>
                <th>이메일</th>
                <th>엔진</th>
                <th>이벤트</th>
                <th>메시지</th>
              </tr>
            </thead>
            <tbody>
              {(engineLogs ?? []).map((r) => (
                <tr key={r.id}>
                  <td>{formatDate(r.at)}</td>
                  <td>{r.email ?? (r.userId != null ? `user#${r.userId}` : '-')}</td>
                  <td>{r.engine || '-'}</td>
                  <td>
                    <span className={renderEngineEvent(r.event).cls}>{renderEngineEvent(r.event).label}</span>
                  </td>
                  <td>{r.message ?? '-'}</td>
                </tr>
              ))}
              {!loading && (engineLogs ?? []).length === 0 ? (
                <tr>
                  <td colSpan={5} className="hint">
                    데이터가 없습니다.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}
