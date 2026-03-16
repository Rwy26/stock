export function StockSearchPage() {
  return (
    <>
      <header className="topbar glass">
        <div>
          <p className="top-label">Stock Search</p>
          <h2>종목 탐색</h2>
          <p className="subtle">종목명 또는 종목코드 검색 (자동완성)</p>
        </div>
        <div className="status-pill">실시간 조회 준비</div>
      </header>

      <section className="two-col">
        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>검색</h3>
          </div>
          <div className="form-row">
            <label>
              검색어
              <input placeholder="예: 삼성전자 / 005930" />
            </label>
            <label>
              시장
              <select>
                <option>KOSPI</option>
                <option>KOSDAQ</option>
                <option>ALL</option>
              </select>
            </label>
            <label>
              정렬
              <select>
                <option>관련도</option>
                <option>거래대금</option>
                <option>등락률</option>
              </select>
            </label>
          </div>
          <div className="divider"></div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>종목명</th>
                  <th>코드</th>
                  <th>현재가</th>
                  <th>등락률</th>
                  <th>상세</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>삼성전자</td>
                  <td>005930</td>
                  <td>72,100</td>
                  <td className="up">+1.02%</td>
                  <td>
                    <button className="btn secondary" type="button">
                      보기
                    </button>
                  </td>
                </tr>
                <tr>
                  <td>SK하이닉스</td>
                  <td>000660</td>
                  <td>210,500</td>
                  <td className="up">+2.12%</td>
                  <td>
                    <button className="btn secondary" type="button">
                      보기
                    </button>
                  </td>
                </tr>
                <tr>
                  <td>팬오션</td>
                  <td>028670</td>
                  <td>6,180</td>
                  <td className="down">-0.64%</td>
                  <td>
                    <button className="btn secondary" type="button">
                      보기
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>

        <article className="panel glass reveal">
          <div className="panel-head">
            <h3>종목 상세</h3>
            <p className="subtle">현재가/등락률, 일봉 차트, 14개 지표 점수</p>
          </div>
          <ul className="engine-list">
            <li>
              <span>종목</span>
              <b>삼성전자 (005930)</b>
            </li>
            <li>
              <span>현재가</span>
              <b>72,100</b>
            </li>
            <li>
              <span>등락률</span>
              <b className="up">+1.02%</b>
            </li>
            <li>
              <span>종합 점수</span>
              <b>91점</b>
            </li>
          </ul>
          <div className="divider"></div>
          <div className="chart-placeholder">일봉 OHLCV Chart Placeholder</div>
          <div className="divider"></div>
          <div className="two-col" style={{ gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <article className="panel" style={{ padding: 0, border: 0, background: 'transparent', boxShadow: 'none' }}>
              <h3 style={{ fontSize: '1rem' }}>지표 점수</h3>
              <ul className="engine-list" style={{ marginTop: 8 }}>
                <li>
                  <span>가치(29)</span>
                  <b>24</b>
                </li>
                <li>
                  <span>수급(26)</span>
                  <b>22</b>
                </li>
                <li>
                  <span>수익(21)</span>
                  <b>19</b>
                </li>
                <li>
                  <span>성장(6)</span>
                  <b>5</b>
                </li>
                <li>
                  <span>기술(18)</span>
                  <b>17</b>
                </li>
              </ul>
            </article>
            <article className="panel" style={{ padding: 0, border: 0, background: 'transparent', boxShadow: 'none' }}>
              <h3 style={{ fontSize: '1rem' }}>액션</h3>
              <p className="hint" style={{ marginTop: 8 }}>
                관심 종목 추가
              </p>
              <button className="btn" type="button" style={{ width: '100%' }}>
                ☆ 관심 추가
              </button>
              <p className="hint" style={{ marginTop: 10 }}>
                점수 상세는 지표별로 확장 예정
              </p>
            </article>
          </div>
        </article>
      </section>
    </>
  )
}
