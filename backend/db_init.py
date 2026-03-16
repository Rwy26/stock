from __future__ import annotations

from datetime import date, timedelta
import sys

from sqlalchemy import select

import db
import models
from auth import hash_password


def _seed_minimal_data() -> None:
    """Seed minimal demo data for local development.

    The current UI expects non-empty portfolio/watchlist/recommendations.
    This seed is intentionally small and idempotent.
    """

    today = date.today()
    yesterday = today - timedelta(days=1)

    universe = [
        # code, name, market, price(today close), changeRate(%), score_total
        ("005930", "삼성전자", "KOSPI", 72100.0, 1.02, 91),
        ("000660", "SK하이닉스", "KOSPI", 210500.0, 2.12, 88),
        ("005380", "현대차", "KOSPI", 221500.0, -0.35, 85),
        ("105560", "KB금융", "KOSPI", 79600.0, 0.48, 84),
        ("005490", "POSCO홀딩스", "KOSPI", 418000.0, 0.90, 83),
    ]

    def prev_close(price: float, change_rate_pct: float) -> float:
        if change_rate_pct == 0:
            return price
        return round(price / (1.0 + (change_rate_pct / 100.0)), 2)

    with db.session_scope() as session:
        # Default user (id=1) used until JWT/login is implemented.
        user = session.execute(select(models.User).where(models.User.id == 1)).scalar_one_or_none()
        if user is None:
            session.add(
                models.User(
                    id=1,
                    email="administrator",
                    nickname="administrator",
                    password_hash=hash_password("!Sunset22"),
                    role="admin",
                    is_active=True,
                )
            )
        else:
            # Upgrade placeholder password to a real hash (idempotent).
            if (user.password_hash or "").strip() in {"", "!", "*"}:
                user.password_hash = hash_password("!Sunset22")

        # 1) Ensure parent rows exist first (stocks)
        for code, name, market, _close_today, _change_rate, _score_total in universe:
            stock = session.execute(select(models.Stock).where(models.Stock.code == code)).scalar_one_or_none()
            if stock is None:
                session.add(models.Stock(code=code, name=name, market=market))

        # Make sure FK parents are visible to subsequent inserts in this transaction.
        session.flush()

        # 2) Child rows (prices + indicator scores)
        for code, _name, _market, close_today, change_rate, score_total in universe:
            exists_today = session.execute(
                select(models.DailyPrice.id).where(
                    models.DailyPrice.stock_code == code,
                    models.DailyPrice.trading_date == today,
                )
            ).first()
            if not exists_today:
                session.add(
                    models.DailyPrice(
                        stock_code=code,
                        trading_date=today,
                        open_price=close_today,
                        high_price=close_today,
                        low_price=close_today,
                        close_price=close_today,
                        volume=0,
                        value=None,
                    )
                )

            close_yesterday = prev_close(close_today, change_rate)
            exists_yesterday = session.execute(
                select(models.DailyPrice.id).where(
                    models.DailyPrice.stock_code == code,
                    models.DailyPrice.trading_date == yesterday,
                )
            ).first()
            if not exists_yesterday:
                session.add(
                    models.DailyPrice(
                        stock_code=code,
                        trading_date=yesterday,
                        open_price=close_yesterday,
                        high_price=close_yesterday,
                        low_price=close_yesterday,
                        close_price=close_yesterday,
                        volume=0,
                        value=None,
                    )
                )

            exists_score = session.execute(
                select(models.IndicatorScore.id).where(
                    models.IndicatorScore.stock_code == code,
                    models.IndicatorScore.scoring_date == today,
                )
            ).first()
            if not exists_score:
                session.add(
                    models.IndicatorScore(
                        stock_code=code,
                        scoring_date=today,
                        score_value=0,
                        score_flow=0,
                        score_profit=0,
                        score_growth=0,
                        score_tech=0,
                        score_total=score_total,
                        details=None,
                    )
                )

        # Recommendations (today)
        for rank, (code, _name, _market, _close_today, _change_rate, score_total) in enumerate(universe, start=1):
            exists_rec = session.execute(
                select(models.Recommendation.id).where(
                    models.Recommendation.rec_date == today,
                    models.Recommendation.stock_code == code,
                )
            ).first()
            if not exists_rec:
                session.add(
                    models.Recommendation(
                        rec_date=today,
                        stock_code=code,
                        score_total=score_total,
                        rank=rank,
                    )
                )

        # Watchlist defaults (3 items)
        for code in ("005930", "000660", "005380"):
            exists_w = session.execute(
                select(models.Watchlist.id).where(
                    models.Watchlist.user_id == 1,
                    models.Watchlist.stock_code == code,
                )
            ).first()
            if not exists_w:
                session.add(models.Watchlist(user_id=1, stock_code=code))

        # Portfolio defaults (2 positions)
        portfolio_defaults = [
            ("005930", 10, 69000.0),
            ("000660", 2, 198000.0),
        ]
        for code, qty, avg_buy in portfolio_defaults:
            exists_p = session.execute(
                select(models.PortfolioPosition.id).where(
                    models.PortfolioPosition.user_id == 1,
                    models.PortfolioPosition.stock_code == code,
                )
            ).first()
            if not exists_p:
                session.add(
                    models.PortfolioPosition(
                        user_id=1,
                        stock_code=code,
                        qty=qty,
                        avg_buy=avg_buy,
                        buy_date=today,
                    )
                )


def main() -> int:
    try:
        engine = db.get_engine()
    except Exception as exc:
        print(f"[db-init] configuration error: {exc}")
        return 2

    try:
        models.Base.metadata.create_all(bind=engine)
        _seed_minimal_data()
        print("[db-init] OK: tables are created/verified")
        return 0
    except Exception as exc:
        print(f"[db-init] FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
