export function AdminPage() {
  return (
    <>
      <header className="topbar glass">
        <div>
          <p className="top-label">Admin</p>
          <h2>관리자 기능</h2>
          <p className="subtle">사용자 관리 / 로그인 이력 / 토큰 갱신</p>
        </div>
        <div className="status-pill">관리자 전용</div>
      </header>

      <section className="panel glass reveal">
        <div className="panel-head">
          <h3>사용자 관리</h3>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>이메일</th>
                <th>역할</th>
                <th>가입일</th>
                <th>활성</th>
                <th>KIS 설정</th>
                <th>비밀번호 초기화</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>administrator</td>
                <td>
                  <b>admin</b>
                </td>
                <td>2026-03-03</td>
                <td>
                  <span className="chip on">ON</span>
                </td>
                <td>
                  <button className="btn secondary" type="button">
                    설정
                  </button>
                </td>
                <td>
                  <button className="btn secondary" type="button">
                    초기화
                  </button>
                </td>
              </tr>
              <tr>
                <td>user01@example.com</td>
                <td>user</td>
                <td>2026-03-10</td>
                <td>
                  <span className="chip on">ON</span>
                </td>
                <td>
                  <button className="btn secondary" type="button">
                    설정
                  </button>
                </td>
                <td>
                  <button className="btn secondary" type="button">
                    초기화
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="divider"></div>
        <div className="form-row">
          <label>
            사용자 생성(이메일)
            <input placeholder="email" />
          </label>
          <label>
            비밀번호
            <input placeholder="password" />
          </label>
          <label>
            역할
            <select>
              <option>user</option>
              <option>admin</option>
            </select>
          </label>
        </div>
        <div className="divider"></div>
        <button className="btn" type="button">
          사용자 생성
        </button>
      </section>

      <section className="panel glass reveal">
        <div className="panel-head">
          <h3>로그인 이력</h3>
        </div>
        <div className="form-row">
          <label>
            시작일
            <input type="date" defaultValue="2026-03-01" />
          </label>
          <label>
            종료일
            <input type="date" defaultValue="2026-03-16" />
          </label>
          <label>
            액션
            <button className="btn" type="button">
              조회
            </button>
          </label>
        </div>
        <div className="divider"></div>
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
              <tr>
                <td>2026-03-16 09:01</td>
                <td>administrator</td>
                <td>login</td>
                <td>203.0.113.10</td>
                <td>Chrome</td>
              </tr>
              <tr>
                <td>2026-03-16 15:30</td>
                <td>administrator</td>
                <td>logout</td>
                <td>203.0.113.10</td>
                <td>Chrome</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="hint" style={{ marginTop: 10 }}>
          관리자 JWT 토큰은 20시간 주기로 자동 갱신
        </p>
      </section>
    </>
  )
}
