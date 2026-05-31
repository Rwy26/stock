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
