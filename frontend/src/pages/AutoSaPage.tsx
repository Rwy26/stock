import { useState } from 'react'

type SaTab = 'status' | 'logs' | 'alerts' | 'signals' | 'daily' | 'snapshots'

export function AutoSaPage() {
  const [activeTab, setActiveTab] = useState<SaTab>('status')

  return (
    <>
      <header className="topbar glass">
        <div>
          <p className="top-label">Smart Agent</p>
          <h2>SA 자동매매</h2>
          <p className="subtle">골든크로스 예측 + OBV/MFI/매집패턴 가중치 기반</p>
        </div>
        <div className="status-pill">모니터링 1분</div>
      </header>

      <section className="panel glass reveal">
        <div className="panel-head">
          <h3>설정</h3>
        </div>
        <div className="settings-grid">
          <label>
            상태
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
            종목당 예산
            <input placeholder="예: 2000000" />
          </label>
          <label>
            최대 종목 수
            <input type="number" defaultValue={5} />
          </label>
          <label>
            최소 SA 점수
            <input type="number" defaultValue={50} />
          </label>
          <label>
            주의 모드 최소 점수
            <input type="number" defaultValue={55} />
          </label>
          <label>
            탐색 순위 범위
            <input type="number" defaultValue={200} />
          </label>
          <label>
            OBV 가중치
            <input type="number" step={0.1} defaultValue={1.0} />
          </label>
          <label>
            MFI 가중치
            <input type="number" step={0.1} defaultValue={1.0} />
          </label>
          <label>
            패턴 가중치
            <input type="number" step={0.1} defaultValue={1.0} />
          </label>
          <label>
            최대 보유일
            <input type="number" defaultValue={10} />
          </label>
          <label>
            변동성 조정
            <select>
              <option>On</option>
              <option>Off</option>
            </select>
          </label>
        </div>
        <div className="divider"></div>
        <button className="btn" type="button">
          저장
        </button>
        <p className="hint" style={{ marginTop: 10 }}>
          금요일 15:15 이후 자동 청산 / 매일 15:20 마감 청산
        </p>
      </section>

      <section className="panel glass reveal">
        <div className="panel-head">
          <h3>탭</h3>
        </div>
        <div className="tabs" data-tabs="sa">
          <button className={`tab${activeTab === 'status' ? ' active' : ''}`} type="button" data-tab="status" onClick={() => setActiveTab('status')}>
            현황
          </button>
          <button className={`tab${activeTab === 'logs' ? ' active' : ''}`} type="button" data-tab="logs" onClick={() => setActiveTab('logs')}>
            매매 로그
          </button>
          <button className={`tab${activeTab === 'alerts' ? ' active' : ''}`} type="button" data-tab="alerts" onClick={() => setActiveTab('alerts')}>
            알림
          </button>
          <button className={`tab${activeTab === 'signals' ? ' active' : ''}`} type="button" data-tab="signals" onClick={() => setActiveTab('signals')}>
            시그널
          </button>
          <button className={`tab${activeTab === 'daily' ? ' active' : ''}`} type="button" data-tab="daily" onClick={() => setActiveTab('daily')}>
            일별 성과
          </button>
          <button className={`tab${activeTab === 'snapshots' ? ' active' : ''}`} type="button" data-tab="snapshots" onClick={() => setActiveTab('snapshots')}>
            계좌 스냅샷
          </button>
        </div>

        <div className="tab-panels" data-tab-panels="sa">
          <div className={`tab-panel${activeTab === 'status' ? ' active' : ''}`} data-tab-panel="status">
            <div className="two-col" style={{ gridTemplateColumns: '1.2fr 0.8fr' }}>
              <article className="panel glass" style={{ boxShadow: 'none' }}>
                <div className="panel-head">
                  <h3>보유 포지션</h3>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>종목명</th>
                        <th>수량</th>
                        <th>매수가</th>
                        <th>현재가</th>
                        <th>수익률</th>
                        <th>골든크로스</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td>SK하이닉스</td>
                        <td>10</td>
                        <td>198,500</td>
                        <td>210,500</td>
                        <td className="up">+6.05%</td>
                        <td>
                          <span className="chip on">달성</span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>
              <article className="panel glass" style={{ boxShadow: 'none' }}>
                <div className="panel-head">
                  <h3>요약</h3>
                </div>
                <ul className="engine-list">
                  <li>
                    <span>엔진</span>
                    <span className="chip on">ON</span>
                  </li>
                  <li>
                    <span>오늘 거래</span>
                    <b>12</b>
                  </li>
                  <li>
                    <span>손절</span>
                    <b>-5.0%</b>
                  </li>
                  <li>
                    <span>익절</span>
                    <b>+5%/+10%</b>
                  </li>
                </ul>
              </article>
            </div>
          </div>

          <div className={`tab-panel${activeTab === 'logs' ? ' active' : ''}`} data-tab-panel="logs">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>시각</th>
                    <th>유형</th>
                    <th>종목</th>
                    <th>수량</th>
                    <th>가격</th>
                    <th>사유</th>
                    <th>손익</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>10:21</td>
                    <td>매수</td>
                    <td>SK하이닉스</td>
                    <td>10</td>
                    <td>198,500</td>
                    <td>골든크로스 임박</td>
                    <td>-</td>
                  </tr>
                  <tr>
                    <td>14:32</td>
                    <td>익절(1차)</td>
                    <td>SK하이닉스</td>
                    <td>5</td>
                    <td>208,400</td>
                    <td>+5% 도달</td>
                    <td className="up">+247,500</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div className={`tab-panel${activeTab === 'alerts' ? ' active' : ''}`} data-tab-panel="alerts">
            <ul className="engine-list">
              <li>
                <span>매수 실패</span>
                <span className="chip off">읽지 않음</span>
              </li>
              <li>
                <span>손절 발생</span>
                <span className="chip on">읽음</span>
              </li>
              <li>
                <span>예산 부족</span>
                <span className="chip off">읽지 않음</span>
              </li>
            </ul>
            <p className="hint" style={{ marginTop: 10 }}>
              이벤트: 매수 실패, 손절, 킬스위치 등
            </p>
          </div>

          <div className={`tab-panel${activeTab === 'signals' ? ' active' : ''}`} data-tab-panel="signals">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>시각</th>
                    <th>종목</th>
                    <th>시그널</th>
                    <th>실행</th>
                    <th>실패 사유</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>10:21</td>
                    <td>SK하이닉스</td>
                    <td>BUY</td>
                    <td>
                      <span className="chip on">성공</span>
                    </td>
                    <td>-</td>
                  </tr>
                  <tr>
                    <td>11:10</td>
                    <td>팬오션</td>
                    <td>BUY</td>
                    <td>
                      <span className="chip off">실패</span>
                    </td>
                    <td>예산 부족</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div className={`tab-panel${activeTab === 'daily' ? ' active' : ''}`} data-tab-panel="daily">
            <div className="chart-placeholder">일별 수익금/수익률 + 누적 손익 Placeholder</div>
            <p className="hint" style={{ marginTop: 10 }}>
              월별/연간 수익률, 승/패 통계는 확장 구현
            </p>
          </div>

          <div className={`tab-panel${activeTab === 'snapshots' ? ' active' : ''}`} data-tab-panel="snapshots">
            <div className="chart-placeholder">시간대별 계좌 현황 Placeholder</div>
          </div>
        </div>
      </section>
    </>
  )
}
