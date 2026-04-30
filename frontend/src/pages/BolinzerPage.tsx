import React from "react";

export function BolinzerPage() {
  return (
    <main className="bolinzer-shell">
      <header className="topbar glass">
        <div>
          <p className="top-label">BOLINZER</p>
          <h2>볼린저 자동매매</h2>
          <p className="subtle">볼린저밴드 기반 자동매매 전략</p>
        </div>
        <div className="status-pill">전략 상태: 준비</div>
      </header>
      <section className="panel glass reveal">
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
            볼린저밴드 기간
            <input type="number" defaultValue={20} />
          </label>
          <label>
            표준편차
            <input type="number" defaultValue={2} />
          </label>
        </div>
        <div className="divider"></div>
        <button className="btn" type="button">저장</button>
      </section>
      <section className="panel glass reveal">
        <div className="panel-head">
          <h3>실행 로그</h3>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>시간</th>
                <th>액션</th>
                <th>종목</th>
                <th>수량</th>
                <th>가격</th>
                <th>메시지</th>
              </tr>
            </thead>
            <tbody>
              {/* TODO: 로그 데이터 연동 */}
              <tr>
                <td>2026-05-01 09:00</td>
                <td>매수</td>
                <td>삼성전자</td>
                <td>10</td>
                <td>75,000</td>
                <td>볼린저 하단 진입</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
