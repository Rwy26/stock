export function AutoBasicPage() {
  return (
    <>
      <header className="topbar glass">
        <div>
          <p className="top-label">Auto Trading</p>
          <h2>일반 자동매매</h2>
          <p className="subtle">추천 점수 기반 단순 매수/매도 자동화</p>
        </div>
        <div className="status-pill">운영시간 09:00~15:20</div>
      </header>

      <section className="two-col">
        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>설정</h3>
          </div>
          <div className="settings-grid">
            <label>
              활성화 여부
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
              최대 보유 종목 수
              <input type="number" defaultValue={5} />
            </label>
            <label>
              손절률(%)
              <input type="number" defaultValue={-5} />
            </label>
            <label>
              익절률(%)
              <input type="number" defaultValue={10} />
            </label>
          </div>
          <div className="divider"></div>
          <button className="btn" type="button">
            저장
          </button>
          <p className="hint" style={{ marginTop: 10 }}>
            거래일 1분 주기로 실행, 주말/공휴일 자동 스킵
          </p>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>상태</h3>
          </div>
          <ul className="engine-list">
            <li>
              <span>엔진</span>
              <span className="chip off">OFF</span>
            </li>
            <li>
              <span>오늘 거래 건수</span>
              <b>0</b>
            </li>
            <li>
              <span>예산 잔액</span>
              <b>₩-</b>
            </li>
            <li>
              <span>마지막 실행</span>
              <b>-</b>
            </li>
          </ul>
          <div className="divider"></div>
          <div className="chart-placeholder">매매 로그/성과 요약 Placeholder</div>
        </article>
      </section>
    </>
  )
}
