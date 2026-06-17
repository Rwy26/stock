from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    nickname: Mapped[str | None] = mapped_column(String(80), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default="user")  # admin | user
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Stock(Base):
    __tablename__ = "stocks"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    market: Mapped[str | None] = mapped_column(String(20), nullable=True)  # KOSPI/KOSDAQ/ETC
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DailyPrice(Base):
    __tablename__ = "daily_prices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    open_price: Mapped[float] = mapped_column(Float)
    high_price: Mapped[float] = mapped_column(Float)
    low_price: Mapped[float] = mapped_column(Float)
    close_price: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(BigInteger)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (Index("uq_daily_prices_code_date", "stock_code", "trading_date", unique=True),)


class IndicatorScore(Base):
    __tablename__ = "indicator_scores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), index=True)
    scoring_date: Mapped[date] = mapped_column(Date, index=True)

    score_value: Mapped[int] = mapped_column(Integer, default=0)
    score_flow: Mapped[int] = mapped_column(Integer, default=0)
    score_profit: Mapped[int] = mapped_column(Integer, default=0)
    score_growth: Mapped[int] = mapped_column(Integer, default=0)
    score_tech: Mapped[int] = mapped_column(Integer, default=0)
    score_total: Mapped[int] = mapped_column(Integer, default=0)

    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (Index("uq_indicator_scores_code_date", "stock_code", "scoring_date", unique=True),)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rec_date: Mapped[date] = mapped_column(Date, index=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), index=True)
    score_total: Mapped[int] = mapped_column(Integer)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (Index("uq_recommendations_date_code", "rec_date", "stock_code", unique=True),)


class KrOpeningGapSignal(Base):
    """KR 시초가 갭 신호 — 참고용 스크리닝 신호(거래 판단 미반영, reference-only).

    소스: premarket-scanner/kr_gap_scanner.sh (네이버 모바일 API) → 종목별 시초가 갭
    = (open - prev_close)/prev_close 재계산. 적재 시점에 갭/가격을 네이버 siseJson으로
    재확인(price_verified)하며 어긋나면 siseJson을 우선한다(daily-prices-pipeline 원칙).
    촉매(catalyst)는 LLM 뉴스 요약·참고치라 catalyst_verified=False 고정 — 추천에서
    사실처럼 표기하지 않는다(data-accuracy 원칙). 제외 종목은 이 테이블에 저장하지 않고
    excluded_stocks 인덱스에만 남긴다(exclusion_engine 경유, 완전제외+인덱스만).
    (session_date, stock_code) UPSERT.
    """

    __tablename__ = "kr_opening_gap_signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_date: Mapped[date] = mapped_column(Date, index=True)              # 갭(시초가)이 발생한 거래일
    # 갭 스캐너는 전 시장(KOSPI+KOSDAQ)을 훑으므로 추천 유니버스(stocks 마스터) 밖 코드가
    # 다수다. reference-only 인 CrossvalCorpus/ExcludedStock 와 같이 stocks FK 를 두지 않는다.
    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    signal_type: Mapped[str] = mapped_column(String(20), default="opening_gap")
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)          # 스캐너 갭% 순위
    tier: Mapped[str | None] = mapped_column(String(2), nullable=True)        # A | B | C (결정론 등급)
    gap_pct: Mapped[float] = mapped_column(Float)                             # siseJson 재확인값
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    prev_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trade_value_krw: Mapped[float | None] = mapped_column(Float, nullable=True)
    catalyst: Mapped[str | None] = mapped_column(Text, nullable=True)         # LLM 뉴스 요약 (미검증)
    catalyst_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # flow | fundamental | null
    catalyst_verified: Mapped[bool] = mapped_column(Boolean, default=False)   # 항상 False (LLM 요약)
    catalyst_source: Mapped[str] = mapped_column(String(40), default="naver_news_llm")
    headlines: Mapped[list | None] = mapped_column(JSON, nullable=True)       # 근거 헤드라인[]
    price_verified: Mapped[bool] = mapped_column(Boolean, default=False)      # siseJson 정합 재확인 통과 여부
    disclaimer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("uq_kr_gap_signal_date_code", "session_date", "stock_code", unique=True),
    )


class PortfolioPosition(Base):
    __tablename__ = "portfolio"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), index=True)
    qty: Mapped[int] = mapped_column(Integer)
    avg_buy: Mapped[float] = mapped_column(Float)
    buy_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("uq_portfolio_user_stock", "user_id", "stock_code", unique=True),)


class AssetHistory(Base):
    __tablename__ = "asset_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    total_value: Mapped[float] = mapped_column(Float)
    invested: Mapped[float] = mapped_column(Float)
    pnl: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)

    __table_args__ = (Index("uq_asset_history_user_date", "user_id", "as_of_date", unique=True),)


class Watchlist(Base):
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (Index("uq_watchlist_user_stock", "user_id", "stock_code", unique=True),)


class StockInterest(Base):
    """사용자별 종목 관심도 추적.

    mention_count: 해당 종목이 이슈 리스트에 등장한 누적 횟수
    interest_weight: mention_count 기반 자동 계산 가중치 (1.0~5.0)
        1회=1.0, 2회≈1.9, 3회≈2.4, 5회≈2.9, 10회≈3.5
    analysis_depth:
        1 (기본): score_total만 저장, details=None
        2 (심화): details JSON 풀 저장 + 기술 지표
        3 (전문): details + DART 실적 + 60m 단기 신호 포함
    tags: 관심 이유 메모 (JSON 배열)
    """
    __tablename__ = "stock_interest"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), index=True)
    mention_count: Mapped[int] = mapped_column(Integer, default=1)
    interest_weight: Mapped[float] = mapped_column(Float, default=1.0)
    analysis_depth: Mapped[int] = mapped_column(Integer, default=1)  # 1|2|3
    tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)   # ["바이오","이슈"]
    last_mentioned_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (Index("uq_stock_interest_user_code", "user_id", "stock_code", unique=True),)


class LoginHistory(Base):
    __tablename__ = "login_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    event: Mapped[str] = mapped_column(String(20))  # login | logout
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class KisProfile(Base):
    __tablename__ = "kis_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, unique=True)
    app_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    app_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_prefix: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SaAutoTradingConfig(Base):
    __tablename__ = "sa_auto_trading_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SaAutoTradingPosition(Base):
    __tablename__ = "sa_auto_trading_positions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), index=True)
    qty: Mapped[int] = mapped_column(Integer)
    avg_buy: Mapped[float] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SaAutoTradingLog(Base):
    __tablename__ = "sa_auto_trading_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), index=True)
    action: Mapped[str] = mapped_column(String(20))  # buy|sell|stoploss|takeprofit
    qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class PlusAutoTradingConfig(Base):
    __tablename__ = "plus_auto_trading_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PlusAutoTradingPosition(Base):
    __tablename__ = "plus_auto_trading_positions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), index=True)
    qty: Mapped[int] = mapped_column(Integer)
    avg_buy: Mapped[float] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PlusAutoTradingLog(Base):
    __tablename__ = "plus_auto_trading_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), index=True)
    action: Mapped[str] = mapped_column(String(20))
    qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class AutomationEngineLog(Base):
    __tablename__ = "automation_engine_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    engine: Mapped[str] = mapped_column(String(20), index=True)  # basic|sa|plus|sv
    event: Mapped[str] = mapped_column(String(30), index=True)  # tick|start|stop|error
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class SvAgentConfig(Base):
    __tablename__ = "sv_agent_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SvAgentPosition(Base):
    __tablename__ = "sv_agent_positions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), index=True)
    qty: Mapped[int] = mapped_column(Integer)
    avg_buy: Mapped[float] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SvAgentPrediction(Base):
    __tablename__ = "sv_agent_predictions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AiAnalysisCache(Base):
    """AI 차트 분석 결과 캐시 테이블.

    종목별 최신 분석 결과를 보관. 동일 종목 재분석 시 덮어쓰기.
    signal 강도 순 정렬용: STRONG_BUY(1) > BUY(2) > HOLD(3) > SELL(4) > STRONG_SELL(5)
    """

    __tablename__ = "ai_analysis_cache"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True, unique=True)
    stock_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, index=True, server_default=func.now())
    signal: Mapped[str | None] = mapped_column(String(20), nullable=True)           # STRONG_BUY | BUY | HOLD | SELL | STRONG_SELL
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)           # 0~100
    upside_probability: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0~100
    eps_growth: Mapped[float | None] = mapped_column(Float, nullable=True)          # EPS 성장률
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)           # AI 전체 분석 결과
    image_hashes: Mapped[list | None] = mapped_column(JSON, nullable=True)          # 이미지 SHA-256 해시 목록


class CrossvalCorpus(Base):
    """교차검증 코퍼스 인덱스·노드 — 모든 세션 공동 사용 공유 저장소.

    참고용 메타데이터(커버리지 인덱스 + 결정론 노드 메트릭)만 보관한다.
    원본 CSV·병합 시계열(parquet)은 D:\\개인연구용 데이터\\교차검증 에 있고,
    이 테이블은 그 요약/색인일 뿐 — 거래 판단에 반영하지 않는다(reference-only).
    종목당 1행, 업로드/병합 시 UPSERT.
    """

    __tablename__ = "crossval_corpus"

    stock_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    stock_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    timeframes: Mapped[dict | None] = mapped_column(JSON, nullable=True)   # 인덱스: {tf: {rows, first, last, files}}
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    last_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_data_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 최신 봉 시각
    node_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)    # 추출 노드(결정론 메트릭)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PublicVisitor(Base):
    """공개(게스트) 페이지 진입 기록.

    이름+전화번호 '회원가입' 게이트로 입력된 방문자. 인증 수단이 아니라
    방문자(리드) 수집 용도. 비밀번호/토큰 없음.
    """

    __tablename__ = "public_visitors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    phone: Mapped[str] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class PublicAiRequest(Base):
    """공개 페이지의 'AI 차트 분석 요청' 기록.

    게스트가 원하는 종목명을 입력하면 분석을 실행하지 않고 요청만 기록한다.
    실제 AI 분석은 관리자만 수행. 관리자는 이 목록(이름/전화/종목)을 확인한다.
    """

    __tablename__ = "public_ai_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    phone: Mapped[str] = mapped_column(String(40), index=True)
    stock_query: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)  # new | done
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class DailyInvestorFlow(Base):
    """일별 투자자 수급 캐시 테이블.

    KIS API 조회 결과를 저장해 반복 호출 최소화.
    run_batch() 수행 시 하루 1회 갱신.
    """

    __tablename__ = "daily_investor_flow"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    # 외국인
    foreign_net_buy_days: Mapped[int] = mapped_column(Integer, default=0)    # 연속 순매수 일수
    foreign_net_qty: Mapped[int] = mapped_column(Integer, default=0)         # 7거래일 누적 순매수량
    # 기관
    inst_net_buy_days: Mapped[int] = mapped_column(Integer, default=0)
    inst_net_qty: Mapped[int] = mapped_column(Integer, default=0)
    # 프로그램
    program_buy_days: Mapped[int] = mapped_column(Integer, default=0)        # 연속 프로그램 매수 일수
    # 메타
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("uq_investor_flow_code_date", "stock_code", "trading_date", unique=True),
    )


class ShortSellingDaily(Base):
    """종목별 일별 공매도 데이터.

    거래량(short_qty/short_ratio): KIS 공매도 일별추이 (TR FHPST04830000) — T+1 공표.
    잔고(balance_qty/balance_ratio): KRX 정보데이터시스템 — KRX_ID/KRX_PW 로그인 필요, T+2 공표.
        (data.krx.co.kr·short.krx.co.kr 모두 로그인 필수 — 무료 회원가입 후 set-krx-env.ps1로 설정)
    수집: scripts/short_selling_sync.py (매일 18:40 작업 스케줄러)
    소비: supply_demand.fetch_supply_demand_batch → scoring_engine 위험2(short_sell_surge_3d)
    """

    __tablename__ = "short_selling_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    # 공매도 거래 (KIS)
    short_qty: Mapped[int] = mapped_column(BigInteger, default=0)        # 공매도 체결 수량
    short_ratio: Mapped[float] = mapped_column(Float, default=0.0)       # 거래량 대비 공매도 비중 %
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 공매도 잔고 (KRX — 자격증명 없으면 NULL 유지)
    balance_qty: Mapped[int | None] = mapped_column(BigInteger, nullable=True)    # 잔고 수량
    balance_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)     # 시총 대비 잔고 비중 %
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("uq_short_selling_code_date", "stock_code", "trade_date", unique=True),
    )


class VkospiHistory(Base):
    """VKOSPI(코스피 변동성지수) 일별 이력.

    현물 VKOSPI는 야후/네이버/다음 미제공. KRX 정보데이터시스템(data.krx.co.kr)은
    접속 가능하나 로그인(KRX_ID/KRX_PW) 필수 — 과거 "DNS 불가" 결론은 잘못된 도메인
    (data.krx.go.kr)으로 테스트한 오판(2026-06-12 확인). 현재는 KRX 변동성지수
    선물 연속물(VKI1!)을 TradingView 차트 데이터로 수집한다.
    초기 적재: scripts/vkospi_crawl.py (과거 일봉 전체)
    일일 갱신: scripts/fundamentals_sync.py (07:00 / 20:10)
    해석: 20~30 평시, 30 이상 공포 (2008년 위기 ~80).
    """

    __tablename__ = "vkospi_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    open: Mapped[float] = mapped_column(Float, default=0.0)
    high: Mapped[float] = mapped_column(Float, default=0.0)
    low: Mapped[float] = mapped_column(Float, default=0.0)
    close: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(20), default="VKI1!")  # 데이터 출처 (선물 연속물)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ExcludedStock(Base):
    """거래 제외 종목 경량 인덱스 — exclusion_engine 전용.

    원칙: 제외 종목은 종목별 데이터를 DB에 저장하지 않고 이 인덱스만 유지한다(용량 절감).
    tags: 쉼표 구분 제외 사유 태그 (exclusion_engine.TAG_LABELS 키).
    source: quote(실시간 탐지) | static(이름/코드 규칙) | sweep(전수 스윕) | manual(수동).
    """

    __tablename__ = "excluded_stocks"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tags: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="sweep")
    first_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_checked: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class MarketLeader(Base):
    """시장 주도 섹터의 주도주 보호 인덱스 — exclusion_engine 전용.

    주도 섹터(compute_king_sectors: KOSPI 대비 섹터 ETF 알파 상위) 안에서
    IndicatorScore 상위 종목을 주도주로 본다. 이 인덱스의 종목은:
      - 어떤 제외 규칙에도 걸리지 않는다(투자 주의 정보에 영향받지 않음).
      - 관심 종목에서 상위에 배치된다.
    source: auto(king-sector 자동 산출) | manual(관리자 고정).
    """

    __tablename__ = "market_leaders"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sector_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 주도 섹터 순위 (1=최상위)
    stock_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)    # 섹터 내 주도주 순위
    score_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="auto")
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class NewsArticle(Base):
    """섹터/종목 뉴스 수집 저장소 (네이버 모바일 증권 뉴스 API).

    수집: backend/news_collector.py — 시장 나침반 계산 시 30분 TTL로 자동 수집.
    article_key = officeId+articleId (네이버 기사 고유키, 중복 수집 방지).
    시장 나침반 6단계(뉴스 분석)가 24시간/7일/30일 버킷으로 사용.
    """

    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_key: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    sector: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    press: Mapped[str | None] = mapped_column(String(80), nullable=True)
    url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MacroSentimentDaily(Base):
    """글로벌 매크로 투자심리 일별 스냅샷 — global_macro.compute_global_macro() 결과 저장.

    8대 점수(0~100, 50=중립) + composite(가중평균) + flow(구간 라벨) + 확률(1w/1m/3m) +
    원천값 inputs(JSON). 모든 수치는 결정론 레이어가 산출하고 LLM은 해석만 한다.
    누적 표본이 ≥60거래일이면 확률 산출이 결정론 로지스틱→빈도 기반으로 자동 전환된다(스펙 §7.2).
    적재: scripts/fundamentals_sync.py (06:00 체인) — trade_date upsert.
    """

    __tablename__ = "macro_sentiment_daily"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    liquidity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    growth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inflation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_cycle: Mapped[int | None] = mapped_column(Integer, nullable=True)
    geopolitics: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_appetite: Mapped[int | None] = mapped_column(Integer, nullable=True)
    us_equity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kr_equity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    composite: Mapped[int | None] = mapped_column(Integer, nullable=True)
    flow: Mapped[str | None] = mapped_column(String(20), nullable=True)
    prob_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)      # {"1w":{up,down},...,"method","n"}
    inputs_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)    # 원천값 + evidence + kr_sectors
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PredictionMarketDaily(Base):
    """예측시장(Polymarket/Kalshi/Metaculus) 이벤트별 확률 시계열.

    target_key = global_macro.PREDICTION_TARGETS 의 key (recession_2026 등).
    각 소스 확률은 0~100(Yes%), 무데이터는 NULL. consensus = 가용 소스 가중평균(스펙 §2.2),
    n_sources = 합산에 참여한 소스 수(표본 수 없는 확률 금지 원칙).
    적재: scripts/fundamentals_sync.py (06:00 체인) — (trade_date, target_key) upsert.
    """

    __tablename__ = "prediction_market_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    target_key: Mapped[str] = mapped_column(String(40), index=True)
    polymarket: Mapped[float | None] = mapped_column(Float, nullable=True)
    kalshi: Mapped[float | None] = mapped_column(Float, nullable=True)
    metaculus: Mapped[float | None] = mapped_column(Float, nullable=True)
    consensus: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_sources: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("uq_prediction_market_date_key", "trade_date", "target_key", unique=True),
    )


class SignalOutcome(Base):
    """AI 시그널 적중 추적 (append-only 예측 로그 + 익일 채점).

    매 분석마다 1행 append (ai_analysis_cache 와 별개·영구 보존).
    야간 채점(scripts/score_signals.py)이 다음 거래일 종가로 결과를 채운다.
    signal: STRONG_BUY | BUY | HOLD | SELL | STRONG_SELL
    hit_1d 판정: BUY/STRONG_BUY → (alpha 없으면 raw) ret > +0.003,
                 SELL/STRONG_SELL → < -0.003, HOLD → |ret| <= 0.003.
    룩어헤드 금지 — entry/next 종가는 predicted_at 이후 시점만 사용.
    """

    __tablename__ = "signal_outcomes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    stock_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(120), nullable=True)
    predicted_at: Mapped[datetime] = mapped_column(DateTime)  # utcnow(naive) 관행
    signal: Mapped[str | None] = mapped_column(String(20), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)        # 종합 점수 0~100
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)   # 0~100 (현재 score 동일)
    entry_close: Mapped[float | None] = mapped_column(Float, nullable=True)  # 분석 시점 기준 종가
    next_close: Mapped[float | None] = mapped_column(Float, nullable=True)   # 다음 거래일 종가
    ret_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_5d: Mapped[float | None] = mapped_column(Float, nullable=True)
    kospi_ret_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    alpha_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    hit_1d: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # composite 5요소 점수 {"섹터 강도":..,"MTF 정렬":..,"상승지속확률":..,"공매도 수급":..,"손익비":..}
    # 3단계 가중치 재학습(scripts/retrain_weights.py)의 features. 구버전 행은 NULL.
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_signal_outcomes_code_predicted", "stock_code", "predicted_at"),
        Index("ix_signal_outcomes_scored_at", "scored_at"),
    )
