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
