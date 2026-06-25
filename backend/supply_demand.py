"""supply_demand.py

수급 + 실적 데이터 통합 수집 모듈.

사용 위치: scoring_engine.run_batch() 또는 추천 엔진 사전 단계에서 호출.
결과 딕셔너리는 scoring_engine.compute_stock_score(supply_demand=...) 에 그대로 전달.

지원 소스:
  1. KIS OpenAPI — 외국인/기관/프로그램 수급 (inquire_investor, program-trade)
  2. DART OpenAPI — 분기별 손익계산서 (EPS 성장률, 영업이익률, 순이익률)
  3. yfinance    — EPS 성장률 fallback (DART 미설정 시)
  4. FinanceDataReader — 시가총액, 섹터 정보 보조

KIS/DART 키 미설정 시 해당 필드를 수집하지 않고 빈 값으로 유지 (스코어링에서 0점 처리).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)


# ─── 단건 수급 조회 ────────────────────────────────────────────────────────────

def fetch_investor_flow_for(
    stock_code: str,
    *,
    app_key: str,
    app_secret: str,
    is_paper: bool,
    live_base_url: str = "",
    paper_base_url: str = "",
    lookback_days: int = 10,
) -> dict[str, Any]:
    """KIS API로 외국인/기관/프로그램 수급 조회 → supply_demand 딕셔너리 반환.

    Returns (빈 dict if 실패):
        {
            "foreign_net_buy_days": int,
            "inst_net_buy_days":    int,
            "foreign_net_qty":      int,
            "inst_net_qty":         int,
            "program_buy_days":     int,
        }
    """
    import kis_client

    result: dict[str, Any] = {}

    kw: dict[str, Any] = {
        "app_key": app_key,
        "app_secret": app_secret,
        "is_paper": is_paper,
    }
    if live_base_url:
        kw["live_base_url"] = live_base_url
    if paper_base_url:
        kw["paper_base_url"] = paper_base_url

    # 외국인/기관 수급
    try:
        inv = kis_client.inquire_investor(code=stock_code, **kw)
        flow = kis_client.parse_investor_flow(inv, lookback_days=lookback_days)
        result.update(flow)
    except Exception as exc:
        logger.debug("KIS investor flow 실패 %s: %s", stock_code, exc)

    # 프로그램 수급
    try:
        prog = kis_client.inquire_program_trade(code=stock_code, **kw)
        result["program_buy_days"] = kis_client.parse_program_trade(prog, lookback_days=5)
    except Exception as exc:
        logger.debug("KIS program trade 실패 %s: %s", stock_code, exc)

    return result


# ─── 통합 배치 수집 ────────────────────────────────────────────────────────────

def fetch_supply_demand_batch(
    stock_codes: list[str],
    *,
    # KIS 설정 (없으면 수급 데이터 미수집)
    kis_app_key: str = "",
    kis_app_secret: str = "",
    kis_is_paper: bool = True,
    kis_live_base_url: str = "",
    kis_paper_base_url: str = "",
    # DART 설정 (없으면 재무 데이터 DART 미수집, yfinance fallback)
    dart_api_key: str = "",
    # 병렬 워커 수
    max_workers: int = 4,
    # DB 캐시 사용 (DailyInvestorFlow 테이블)
    use_db_cache: bool = True,
    db_session=None,        # SQLAlchemy Session (있으면 캐시 읽기/쓰기)
) -> dict[str, dict[str, Any]]:
    """여러 종목의 수급/실적 데이터를 병렬 수집 후 통합 반환.

    Returns:
        {
            "005930": {
                "foreign_net_buy_days": 5,
                "inst_net_buy_days":    3,
                "program_buy_days":     2,
                "foreign_net_qty":      120000,
                "inst_net_qty":         80000,
                "eps_growth":           0.42,
                "profit_margin":        0.18,
                "op_margin":            0.22,
            },
            ...
        }

    모든 필드는 Optional — 데이터 없으면 키 자체가 없음.
    """
    today = date.today()
    result: dict[str, dict[str, Any]] = {c: {} for c in stock_codes}

    # ── 1. DB 캐시 로딩 ──────────────────────────────────────────────────────
    codes_needing_kis: list[str] = list(stock_codes)
    if use_db_cache and db_session is not None:
        cached_codes = _load_investor_flow_cache(db_session, stock_codes, today)
        for code, cached in cached_codes.items():
            result[code].update(cached)
        codes_needing_kis = [c for c in stock_codes if c not in cached_codes]

    # ── 2. KIS 수급 수집 ─────────────────────────────────────────────────────
    kis_ok = bool(kis_app_key and kis_app_secret)
    if kis_ok and codes_needing_kis:
        logger.info("KIS 수급 조회: %d종목", len(codes_needing_kis))

        def _kis_one(code: str) -> tuple[str, dict]:
            flow = fetch_investor_flow_for(
                code,
                app_key=kis_app_key,
                app_secret=kis_app_secret,
                is_paper=kis_is_paper,
                live_base_url=kis_live_base_url,
                paper_base_url=kis_paper_base_url,
            )
            return code, flow

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for code, flow in pool.map(_kis_one, codes_needing_kis):
                if flow:
                    result[code].update(flow)

        # DB 캐시 쓰기
        if use_db_cache and db_session is not None:
            try:
                _save_investor_flow_cache(db_session, result, today)
                db_session.commit()
            except Exception as exc:
                logger.warning("KIS 캐시 저장 실패: %s", exc)
                try:
                    db_session.rollback()
                except Exception:
                    pass

    elif not kis_ok:
        logger.debug("KIS_APP_KEY/SECRET 미설정 — 수급 데이터 조회 건너뜀")

    # ── 2.5 공매도 급증 플래그 (short_selling_daily — scripts/short_selling_sync.py가 매일 적재) ──
    if db_session is not None:
        try:
            import short_selling
            surge_flags = short_selling.compute_short_surge_flags(db_session, stock_codes)
            for code, flags in surge_flags.items():
                for k, v in flags.items():
                    if k not in result[code]:   # 수동 주입값 우선
                        result[code][k] = v
            logger.info("공매도 급증 판정: %d종목 (데이터 충분 종목만)", len(surge_flags))
        except Exception as exc:
            logger.warning("공매도 급증 판정 실패 (스코어링은 N/A로 계속): %s", exc)

    # ── 3. DART 재무 데이터 수집 ─────────────────────────────────────────────
    if dart_api_key:
        logger.info("DART 재무 데이터 조회: %d종목", len(stock_codes))
        try:
            import dart_client
            financials = dart_client.fetch_financials_batch(
                stock_codes, api_key=dart_api_key, max_workers=max_workers
            )
            for code, fin in financials.items():
                if fin:
                    for k, v in fin.items():
                        if k not in result[code]:   # 기존 값 우선
                            result[code][k] = v
        except ImportError:
            logger.warning("dart_client 모듈 없음 — DART 재무 데이터 건너뜀")
        except Exception as exc:
            logger.warning("DART 재무 데이터 조회 실패: %s", exc)

    else:
        logger.debug("DART_API_KEY 미설정 — yfinance EPS fallback 사용 (scoring_engine 내부)")

    valid = sum(1 for v in result.values() if v)
    logger.info(
        "fetch_supply_demand_batch 완료: %d종목, 유효 %d건 (KIS=%s, DART=%s)",
        len(result), valid, "O" if kis_ok else "X", "O" if dart_api_key else "X"
    )
    return result


# ─── DB 캐시 헬퍼 ─────────────────────────────────────────────────────────────

def _load_investor_flow_cache(
    db,
    stock_codes: list[str],
    today: date,
) -> dict[str, dict[str, Any]]:
    """DailyInvestorFlow 테이블에서 오늘 날짜 캐시 로딩."""
    try:
        import models
        from sqlalchemy import select

        rows = db.execute(
            select(models.DailyInvestorFlow).where(
                models.DailyInvestorFlow.stock_code.in_(stock_codes),
                models.DailyInvestorFlow.trading_date == today,
            )
        ).scalars().all()

        return {
            str(row.stock_code): {
                "foreign_net_buy_days": int(row.foreign_net_buy_days or 0),
                "inst_net_buy_days":    int(row.inst_net_buy_days or 0),
                "foreign_net_qty":      int(row.foreign_net_qty or 0),
                "inst_net_qty":         int(row.inst_net_qty or 0),
                "program_buy_days":     int(row.program_buy_days or 0),
            }
            for row in rows
        }
    except Exception as exc:
        logger.debug("DailyInvestorFlow 캐시 로딩 실패: %s", exc)
        return {}


def _save_investor_flow_cache(
    db,
    result: dict[str, dict[str, Any]],
    today: date,
) -> None:
    """수집된 수급 데이터를 DailyInvestorFlow에 upsert."""
    try:
        import models
        from sqlalchemy.dialects.mysql import insert as mysql_insert

        rows_to_upsert = []
        for code, data in result.items():
            if not data:
                continue
            rows_to_upsert.append({
                "stock_code":           code,
                "trading_date":         today,
                "foreign_net_buy_days": int(data.get("foreign_net_buy_days", 0)),
                "foreign_net_qty":      int(data.get("foreign_net_qty", 0)),
                "inst_net_buy_days":    int(data.get("inst_net_buy_days", 0)),
                "inst_net_qty":         int(data.get("inst_net_qty", 0)),
                "program_buy_days":     int(data.get("program_buy_days", 0)),
                "fetched_at":           datetime.now(),
            })

        if not rows_to_upsert:
            return

        stmt = mysql_insert(models.DailyInvestorFlow.__table__).values(rows_to_upsert)
        stmt = stmt.on_duplicate_key_update(
            foreign_net_buy_days=stmt.inserted.foreign_net_buy_days,
            foreign_net_qty=stmt.inserted.foreign_net_qty,
            inst_net_buy_days=stmt.inserted.inst_net_buy_days,
            inst_net_qty=stmt.inserted.inst_net_qty,
            program_buy_days=stmt.inserted.program_buy_days,
            fetched_at=stmt.inserted.fetched_at,
        )
        db.execute(stmt)
        logger.debug("DailyInvestorFlow 캐시 저장: %d건", len(rows_to_upsert))
    except Exception as exc:
        logger.warning("DailyInvestorFlow 캐시 저장 실패: %s", exc)
        raise
