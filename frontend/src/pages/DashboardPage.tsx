export function DashboardPage() {
  return (
    <>
      <header className="topbar glass">
        <div>
          <p className="top-label">Production v1.0+</p>
          <h2>Apollo Stock Trading System</h2>
        </div>
        <div className="status-pill">KIS 실시간 연결</div>
      </header>

      <section className="dashboard-grid">
        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>자산 요약 (Asset Summary)</h3>
          </div>
          <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
            <div className="card gradient-a" style={{ boxShadow: 'none' }}>
              <h3>총 평가금액</h3>
              <p className="value">₩184,380,000</p>
              <span className="delta up">+2.41%</span>
            </div>
            <div className="card gradient-b" style={{ boxShadow: 'none' }}>
              <h3>총 투자금액</h3>
              <p className="value">₩161,000,000</p>
              <span className="delta up">+1.04%</span>
            </div>
            <div className="card gradient-c" style={{ boxShadow: 'none' }}>
              <h3>수익금</h3>
              <p className="value">₩23,380,000</p>
              <span className="delta up">+14.52%</span>
            </div>
            <div className="card gradient-d" style={{ boxShadow: 'none' }}>
              <h3>예수금</h3>
              <p className="value">₩39,640,000</p>
              <span className="delta">가용 가능</span>
            </div>
          </div>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>자산 추이 차트 (30일)</h3>
          </div>
          <div className="chart-placeholder">Asset Trend Chart Placeholder</div>
          <p className="hint" style={{ marginTop: 10 }}>
            날짜 hover 시 상세 금액 표시
          </p>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>자동매매 상태</h3>
          </div>
          <ul className="engine-list">
            <li>
              <span>일반 자동매매</span>
              <span className="chip off">OFF</span>
            </li>
            <li>
              <span>SA 자동매매</span>
              <span className="chip on">ON / 12건</span>
            </li>
            <li>
              <span>Plus 자동매매</span>
              <span className="chip off">OFF</span>
            </li>
            <li>
              <span>SV Agent</span>
              <span className="chip on">ON / ai_assisted</span>
            </li>
          </ul>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>Top 추천 종목</h3>
          </div>
          <ol className="ranking">
            <li>
              <span>삼성전자</span>
              <b>91점</b>
            </li>
            <li>
              <span>SK하이닉스</span>
              <b>88점</b>
            </li>
            <li>
              <span>현대차</span>
              <b>85점</b>
            </li>
            <li>
              <span>KB금융</span>
              <b>84점</b>
            </li>
            <li>
              <span>POSCO홀딩스</span>
              <b>83점</b>
            </li>
          </ol>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>일봉 캔들 차트</h3>
            <p className="subtle">선택 종목: 삼성전자 (005930)</p>
          </div>
          <div className="chart-placeholder">Daily Candle Chart Placeholder</div>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>시장 지수 차트</h3>
            <p className="subtle">KOSPI / KOSDAQ 당일 분봉</p>
          </div>
          <div className="chart-placeholder">Market Index Chart Placeholder</div>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>금리 차트</h3>
            <p className="subtle">한국 기준금리 / CD금리</p>
          </div>
          <div className="chart-placeholder">Interest Rate Chart Placeholder</div>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>환율 차트</h3>
            <p className="subtle">USD/KRW 최근 30일</p>
          </div>
          <div className="chart-placeholder">FX Chart Placeholder</div>
        </article>
      </section>
    </>
  )
}
