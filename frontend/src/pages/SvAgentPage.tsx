import { useState } from 'react'

type SvTab = 'positions' | 'ai' | 'approvals' | 'realized' | 'settings'

export function SvAgentPage() {
  const [activeTab, setActiveTab] = useState<SvTab>('positions')

  return (
    <>
      <header className="topbar glass">
        <div>
          <p className="top-label">Supervisor Agent</p>
          <h2>SV Agent (AI 슈퍼바이저)</h2>
          <p className="subtle">멀티 AI 에이전트 기반 감독 자동매매</p>
        </div>
        <div className="status-pill">Kill Switch</div>
      </header>

      <section className="two-col">
        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>설정</h3>
          </div>
          <div className="settings-grid">
            <label>
              활성화
              <select>
                <option>Off</option>
                <option>On</option>
              </select>
            </label>
            <label>
              총 예산
              <input placeholder="예: 10000000" />
            </label>
            <label>
              최대 종목 수
              <input type="number" defaultValue={5} />
            </label>
            <label>
              종목당 최대 예산
              <input placeholder="예: 2000000" />
            </label>
            <label>
              승인 모드
              <select>
                <option>rule_based</option>
                <option>ai_assisted</option>
                <option>full_ai</option>
              </select>
            </label>
            <label>
              손절률(%)
              <input type="number" defaultValue={-5} />
            </label>
            <label>
              익절률(%)
              <input type="number" defaultValue={10} />
            </label>
            <label>
              트레일링 시작 수익률(%)
              <input type="number" defaultValue={3} />
            </label>
            <label>
              최대 보유일
              <input type="number" defaultValue={10} />
            </label>
            <label>
              AI 학습 활성화
              <select>
                <option>On</option>
                <option>Off</option>
              </select>
            </label>
            <label>
              Kill Switch 임계값(%)
              <input type="number" defaultValue={-10} />
            </label>
          </div>
          <div className="divider"></div>
          <button className="btn" type="button">
            저장
          </button>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>Kill Switch 상태</h3>
          </div>
          <ul className="engine-list">
            <li>
              <span>임계값</span>
              <b>-10%</b>
            </li>
            <li>
              <span>현재 손실률</span>
              <b className="up">-</b>
            </li>
            <li>
              <span>상태</span>
              <span className="chip on">대기</span>
            </li>
          </ul>
          <div className="divider"></div>
          <p className="hint">임계값 초과 시 모든 포지션 즉시 청산 후 비활성화</p>
        </article>
      </section>

      <section className="panel glass reveal">
        <div className="panel-head">
          <h3>탭</h3>
        </div>
        <div className="tabs" data-tabs="sv">
          <button className={`tab${activeTab === 'positions' ? ' active' : ''}`} type="button" data-tab="positions" onClick={() => setActiveTab('positions')}>
            보유 포지션
          </button>
          <button className={`tab${activeTab === 'ai' ? ' active' : ''}`} type="button" data-tab="ai" onClick={() => setActiveTab('ai')}>
            AI 추천
          </button>
          <button className={`tab${activeTab === 'approvals' ? ' active' : ''}`} type="button" data-tab="approvals" onClick={() => setActiveTab('approvals')}>
            승인 이력
          </button>
          <button className={`tab${activeTab === 'realized' ? ' active' : ''}`} type="button" data-tab="realized" onClick={() => setActiveTab('realized')}>
            실현손익
          </button>
          <button className={`tab${activeTab === 'settings' ? ' active' : ''}`} type="button" data-tab="settings" onClick={() => setActiveTab('settings')}>
            설정
          </button>
        </div>

        <div className="tab-panels" data-tab-panels="sv">
          <div className={`tab-panel${activeTab === 'positions' ? ' active' : ''}`} data-tab-panel="positions">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>종목명</th>
                    <th>수량</th>
                    <th>매수가</th>
                    <th>현재가</th>
                    <th>수익률</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>삼성전자</td>
                    <td>20</td>
                    <td>69,400</td>
                    <td>72,100</td>
                    <td className="up">+3.89%</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="hint" style={{ marginTop: 10 }}>
              현재가는 KIS 실시간 API 조회
            </p>
          </div>

          <div className={`tab-panel${activeTab === 'ai' ? ' active' : ''}`} data-tab-panel="ai">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>종목</th>
                    <th>AI 점수</th>
                    <th>추천 사유</th>
                    <th>승인 상태</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>현대차</td>
                    <td>
                      <b>0.82</b>
                    </td>
                    <td>리스크/수익 균형</td>
                    <td>
                      <span className="chip off">대기</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div className={`tab-panel${activeTab === 'approvals' ? ' active' : ''}`} data-tab-panel="approvals">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>시각</th>
                    <th>종목</th>
                    <th>신호</th>
                    <th>결과</th>
                    <th>사유</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>11:12</td>
                    <td>현대차</td>
                    <td>BUY</td>
                    <td>
                      <span className="chip on">승인</span>
                    </td>
                    <td>규칙 충족</td>
                  </tr>
                  <tr>
                    <td>12:03</td>
                    <td>팬오션</td>
                    <td>BUY</td>
                    <td>
                      <span className="chip off">거절</span>
                    </td>
                    <td>리스크 과다</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div className={`tab-panel${activeTab === 'realized' ? ' active' : ''}`} data-tab-panel="realized">
            <div className="chart-placeholder">날짜별/종목별 실현손익 집계 Placeholder</div>
            <p className="hint" style={{ marginTop: 10 }}>
              승/패 통계 확장 구현
            </p>
          </div>

          <div className={`tab-panel${activeTab === 'settings' ? ' active' : ''}`} data-tab-panel="settings">
            <p className="hint">상단 설정 패널과 동일 항목을 조정합니다.</p>
          </div>
        </div>
      </section>
    </>
  )
}
