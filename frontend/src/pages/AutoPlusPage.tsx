import { useState } from 'react'

type PlusTab = 'status' | 'logs' | 'rotation' | 'performance'

export function AutoPlusPage() {
  const [activeTab, setActiveTab] = useState<PlusTab>('status')

  return (
    <>
      <header className="topbar glass">
        <div>
          <p className="top-label">Plus Auto Trading</p>
          <h2>Plus 자동매매</h2>
          <p className="subtle">포트폴리오 순환 매매(언더퍼포머 자동 교체)</p>
        </div>
        <div className="status-pill">순환 체크 주기 설정</div>
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
            탐색 시작 순위
            <input type="number" defaultValue={1} />
          </label>
          <label>
            탐색 종료 순위
            <input type="number" defaultValue={100} />
          </label>
          <label>
            상승 요구
            <select>
              <option>Off</option>
              <option>On</option>
            </select>
          </label>
          <label>
            최소 SA 점수
            <input type="number" defaultValue={50} />
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
            트레일링 스탑률
            <input placeholder="선택" />
          </label>
          <label>
            급락 매도률
            <input placeholder="선택" />
          </label>
          <label>
            최소 보유 시간(분)
            <input placeholder="선택" />
          </label>
          <label>
            순환 체크 주기(분)
            <input placeholder="선택" />
          </label>
        </div>
        <div className="divider"></div>
        <button className="btn" type="button">
          저장
        </button>
      </section>

      <section className="panel glass reveal">
        <div className="panel-head">
          <h3>탭</h3>
        </div>
        <div className="tabs" data-tabs="plus">
          <button className={`tab${activeTab === 'status' ? ' active' : ''}`} type="button" data-tab="status" onClick={() => setActiveTab('status')}>
            현황
          </button>
          <button className={`tab${activeTab === 'logs' ? ' active' : ''}`} type="button" data-tab="logs" onClick={() => setActiveTab('logs')}>
            매매 로그
          </button>
          <button className={`tab${activeTab === 'rotation' ? ' active' : ''}`} type="button" data-tab="rotation" onClick={() => setActiveTab('rotation')}>
            순환 이력
          </button>
          <button className={`tab${activeTab === 'performance' ? ' active' : ''}`} type="button" data-tab="performance" onClick={() => setActiveTab('performance')}>
            성과 차트
          </button>
        </div>

        <div className="tab-panels" data-tab-panels="plus">
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
                        <th>매수가</th>
                        <th>현재가</th>
                        <th>매수 랭킹</th>
                        <th>수익률</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td>KB금융</td>
                        <td>78,400</td>
                        <td>79,600</td>
                        <td>12</td>
                        <td className="up">+1.53%</td>
                      </tr>
                      <tr>
                        <td>POSCO홀딩스</td>
                        <td>420,000</td>
                        <td>418,000</td>
                        <td>18</td>
                        <td className="down">-0.48%</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>
              <article className="panel glass" style={{ boxShadow: 'none' }}>
                <div className="panel-head">
                  <h3>통계</h3>
                </div>
                <ul className="engine-list">
                  <li>
                    <span>총 평가액</span>
                    <b>₩-</b>
                  </li>
                  <li>
                    <span>평균 수익률</span>
                    <b className="up">+0.52%</b>
                  </li>
                  <li>
                    <span>여유 슬롯</span>
                    <b>3</b>
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
                    <th>가격</th>
                    <th>수량</th>
                    <th>랭킹</th>
                    <th>사유</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>09:10</td>
                    <td>매수</td>
                    <td>KB금융</td>
                    <td>78,400</td>
                    <td>20</td>
                    <td>12</td>
                    <td>추천 상위 편입</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div className={`tab-panel${activeTab === 'rotation' ? ' active' : ''}`} data-tab-panel="rotation">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>시각</th>
                    <th>퇴출 종목</th>
                    <th>퇴출 수익률</th>
                    <th>편입 종목</th>
                    <th>편입 랭킹</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>13:05</td>
                    <td>POSCO홀딩스</td>
                    <td className="down">-0.48%</td>
                    <td>현대차</td>
                    <td>3</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div className={`tab-panel${activeTab === 'performance' ? ' active' : ''}`} data-tab-panel="performance">
            <div className="chart-placeholder">일별 수익(바) + 누적 손익(선) Placeholder</div>
          </div>
        </div>
      </section>
    </>
  )
}
