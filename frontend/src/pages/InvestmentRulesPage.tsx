
export function InvestmentRulesPage() {
  return (
    <main className="investment-rules-shell">
      <header className="topbar glass">
        <div>
          <p className="top-label">Investment Rules</p>
          <h2>투자 규칙</h2>
          <p className="subtle">SongStock 시스템의 투자 원칙 및 운영 정책</p>
        </div>
      </header>
      <section className="panel glass reveal">
        <div className="panel-head">
          <h3>기본 투자 규칙</h3>
        </div>
        <ul className="engine-list">
          <li>실계좌/실데이터 기반 운영</li>
          <li>자동매매는 사전 승인/설정된 전략만 허용</li>
          <li>손절/익절/분할매수 등 리스크 관리 필수</li>
          <li>시장/종목별 투자 한도 엄수</li>
          <li>모든 거래/운영 내역 기록 및 검증</li>
        </ul>
      </section>
      <section className="panel glass reveal">
        <div className="panel-head">
          <h3>운영 정책</h3>
        </div>
        <ul className="engine-list">
          <li>주문/자동매매 차단 정책(필요시)</li>
          <li>실시간 모니터링 및 장애 대응</li>
          <li>보안 및 개인정보 보호 준수</li>
          <li>운영/검증 스크립트 및 문서화</li>
        </ul>
      </section>
    </main>
  );
}
