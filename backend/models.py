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
