"""거래 제외 종목 엔진 — MOON STOCK 전역 제외 원칙의 단일 소스.

원칙 (2026-06-12 확정):
  1. 제외 종목은 종목별 데이터의 DB 저장(스코어/일봉/수급/뉴스/AI캐시 등)을 하지 않는다.
  2. 제외 종목 문의 발생 시 "의견 거부"를 *발행*한다 — 요청 자체를 에러로 거부하는 것이
     아니라, 제외 사유 태그와 원인 설명이 담긴 메시지를 정상 응답(HTTP 200)으로 내보낸다.
  3. DB에는 경량 인덱스(excluded_stocks: 코드/이름/태그/사유)만 저장해 용량 부담을 줄인다.
  4. 이 원칙은 MOON STOCK 모든 파이프라인·엔드포인트에 적용한다.

제외하지 않는 것 (2026-06-12 사용자 확정):
  - 주가·시장 과열로 인한 시장조치(투자주의/투자경고/투자위험, 단기과열)는 제외하지
    않으며 필요한 모든 정보를 정상 저장한다. 제외 대상 시장조치는 거래정지/정리매매/
    관리종목 뿐이다.
  - 섹터를 대표하는 ETF(scoring_engine.SECTOR_ETF_MAP)는 제외하지 않고 정보를 모두 저장한다.

판정 소스:
  - 시장조치: KIS 현재가(FHKST01010100) 응답의 Y/N 필드.
      mang_issu_cls_code(관리종목여부) / temp_stop_yn(거래정지) / sltr_yn(정리매매)
      iscd_stat_cls_code(종목상태구분코드)는 보조 신호 — 51 관리 / 58 거래정지 에만
      반응하고 그 외 값(55 신용가능, 57 증거금100% 등)은 제외 사유로 쓰지 않는다.
  - 상품유형: 스팩(이름 '스팩'), 우선주(6자리 코드 끝자리 != '0'), 리츠(이름 '리츠' 종료),
      ETF/ETN(스윕에서 pykrx 목록 대조, 섹터 대표 ETF는 예외 — 이름 휴리스틱은 쓰지 않는다).
  - 유동성: daily_prices 최근 N일 평균 거래대금(close*volume 근사) < 기준,
      최근 종가 < 동전주 기준. 데이터 5일 미만/정체/불량이면 판정 보류(오판 방지).

태그 카테고리별 갱신 주체:
  - MARKET_ACTION_TAGS: 실시간 시세 확인(record_quote) 시 갱신/해제.
  - STATIC_NAME_TAGS:   이름/코드 기반 — record_quote/스윕에서 재계산.
  - SWEEP_ONLY_TAGS:    스윕(run_sweep)만 갱신/해제 (ETF_ETN, LOW_LIQUIDITY, PENNY).
  - MANUAL:             관리자 수동 — API로만 추가/해제.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger("exclusion")

# ─── 태그 정의 ────────────────────────────────────────────────────────────────

TAG_LABELS: dict[str, str] = {
    "TRADE_HALT":     "거래정지",
    "LIQUIDATION":    "정리매매",
    "ADMIN_ISSUE":    "관리종목",
    "SPAC":           "스팩(SPAC)",
    "PREFERRED":      "우선주",
    "REIT":           "리츠",
    "ETF_ETN":        "ETF/ETN",
    "LOW_LIQUIDITY":  "저유동성(평균 거래대금 미달)",
    "PENNY":          "동전주(초저가)",
    "MANUAL":         "수동 지정",
    # 폐기 태그 (주가·과열 기인 시장조치는 제외하지 않음 — 레거시 행 표시/정리용으로만 유지)
    "INVEST_RISK":    "투자위험(폐기)",
    "INVEST_WARN":    "투자경고(폐기)",
    "INVEST_CAUTION": "투자주의(폐기)",
    "SHORT_OVERHEAT": "단기과열(폐기)",
}

# INVEST_*/SHORT_OVERHEAT 는 더 이상 발행되지 않지만, 갱신 카테고리에 남겨 두어
# 과거에 기록된 레거시 행이 다음 시세 확인/스윕에서 자동 해제되도록 한다.
MARKET_ACTION_TAGS = {
    "TRADE_HALT", "LIQUIDATION", "ADMIN_ISSUE",
    "INVEST_RISK", "INVEST_WARN", "INVEST_CAUTION", "SHORT_OVERHEAT",
}
STATIC_NAME_TAGS = {"SPAC", "PREFERRED", "REIT"}
SWEEP_ONLY_TAGS = {"ETF_ETN", "LOW_LIQUIDITY", "PENNY"}

# iscd_stat_cls_code 보조 매핑 — 여기 명시된 값에만 반응 (그 외 값은 무시)
_STAT_CODE_TAGS = {
    "51": "ADMIN_ISSUE",
    "58": "TRADE_HALT",
}


def sector_etf_codes() -> set[str]:
    """섹터 대표 ETF 코드 — 제외 금지 대상 (scoring_engine.SECTOR_ETF_MAP 기준)."""
    try:
        import scoring_engine

        return {str(t).split(".")[0].strip() for t in scoring_engine.SECTOR_ETF_MAP.values()}
    except Exception:
        # scoring_engine 로드 실패 시에도 동일 목록 유지 (KODEX 반도체/2차전지/K-바이오/K-방산/인공지능/미디어&엔터)
        return {"091160", "305720", "244580", "459580", "476600", "140570"}


class ExcludedStockError(Exception):
    """제외 종목 문의에 대한 의견 거부. payload는 표준 거부 메시지."""

    def __init__(self, payload: dict):
        super().__init__(payload.get("message", "excluded stock"))
        self.payload = payload


# ─── 인덱스 테이블 보장 + 인메모리 캐시 ─────────────────────────────────────

_table_ready = False
_cache: dict[str, dict] | None = None
_cache_at: float = 0.0
_CACHE_TTL = 600.0
_lock = threading.Lock()


def _ensure_table() -> None:
    global _table_ready
    if _table_ready:
        return
    import db
    import models

    models.Base.metadata.create_all(db.get_engine(), tables=[models.ExcludedStock.__table__])
    _table_ready = True


def invalidate_cache() -> None:
    global _cache, _cache_at
    with _lock:
        _cache = None
        _cache_at = 0.0


def get_exclusions(session: Session, *, force: bool = False) -> dict[str, dict]:
    """전체 제외 인덱스를 {code: {name, tags, detail}}로 반환 (TTL 캐시)."""
    global _cache, _cache_at
    with _lock:
        if (not force) and _cache is not None and (time.time() - _cache_at) < _CACHE_TTL:
            return _cache

    import models

    _ensure_table()
    rows = session.execute(select(models.ExcludedStock)).scalars().all()
    fresh: dict[str, dict] = {}
    for r in rows:
        tags = [t for t in str(r.tags or "").split(",") if t]
        fresh[str(r.code)] = {
            "name": str(r.name or ""),
            "tags": tags,
            "detail": str(r.detail or "") or None,
        }
    with _lock:
        _cache = fresh
        _cache_at = time.time()
    return fresh


def get_entry(session: Session, code: str) -> dict | None:
    return get_exclusions(session).get(str(code).strip())


def is_excluded(session: Session, code: str) -> bool:
    return get_entry(session, code) is not None


def filter_codes(session: Session, codes: Iterable[str]) -> list[str]:
    """제외 종목을 걸러낸 코드 목록 (DB 저장 파이프라인 입구용)."""
    all_codes = [str(c).strip() for c in codes]
    excluded = get_exclusions(session)
    allow = sector_etf_codes()  # 섹터 대표 ETF는 항상 통과 (정보 정상 저장)
    kept = [c for c in all_codes if c not in excluded or c in allow]
    dropped = len(all_codes) - len(kept)
    if dropped:
        logger.info("제외 종목 %d건 파이프라인 제외", dropped)
    return kept


# ─── 판정 규칙 ────────────────────────────────────────────────────────────────

def evaluate_quote_status(quote: Any) -> list[str]:
    """KisQuote의 시장조치 필드 → 태그. Y/N 필드가 1차, 코드값은 보조.

    주가·시장 과열 기인 조치(투자주의/경고/위험, 단기과열)는 제외 사유가 아니다 —
    해당 종목은 정상적으로 모든 정보를 저장한다 (2026-06-12 사용자 확정).
    """
    tags: set[str] = set()
    if getattr(quote, "is_trade_halt", False):
        tags.add("TRADE_HALT")
    if getattr(quote, "is_liquidation", False):
        tags.add("LIQUIDATION")
    if getattr(quote, "is_admin_issue", False):
        tags.add("ADMIN_ISSUE")

    stat = str(getattr(quote, "status_code", "") or "").strip()
    if stat in _STAT_CODE_TAGS:
        tags.add(_STAT_CODE_TAGS[stat])

    return sorted(tags)


def evaluate_static(code: str, name: str) -> list[str]:
    """이름/코드 기반 상품유형 태그 (결정론 — 언제든 재계산 가능)."""
    tags: set[str] = set()
    code = str(code or "").strip()
    name = str(name or "").strip()

    if len(code) == 6 and code.isdigit() and not code.endswith("0"):
        tags.add("PREFERRED")
    if name and "스팩" in name:
        tags.add("SPAC")
    if name.endswith("리츠"):
        tags.add("REIT")
    return sorted(tags)


def evaluate_liquidity(
    session: Session,
    code: str,
    *,
    days: int | None = None,
    min_avg_value: float | None = None,
    min_price: float | None = None,
) -> tuple[list[str], str | None]:
    """daily_prices 기반 유동성 판정. 거래대금은 close*volume 근사.

    데이터 품질 가드 (잘못된 정보로 제외하지 않는다 — 판정 보류):
      - 데이터 5일 미만
      - 신선도: 해당 종목 최신 일자가 테이블 전체 최신 일자보다 7일 이상 뒤처짐(수집 중단)
      - 무결성: 판정 구간의 절반 이상이 volume=0 (yfinance 불량/정지 데이터)
    """
    from datetime import timedelta as _td

    from sqlalchemy import desc as _desc, func as _func

    import models
    from settings import settings

    days = days or getattr(settings, "exclusion_liquidity_days", 20)
    min_avg_value = min_avg_value if min_avg_value is not None else getattr(
        settings, "exclusion_min_avg_trading_value", 1_000_000_000.0
    )
    min_price = min_price if min_price is not None else getattr(settings, "exclusion_min_price", 1000.0)

    rows = session.execute(
        select(models.DailyPrice.trading_date, models.DailyPrice.close_price, models.DailyPrice.volume, models.DailyPrice.value)
        .where(models.DailyPrice.stock_code == str(code).strip())
        .order_by(_desc(models.DailyPrice.trading_date))
        .limit(int(days))
    ).all()

    if len(rows) < 5:
        return [], None  # 데이터 부족 — 판정 보류

    # 신선도: 전체 데이터셋의 최신 일자 대비 7일 이상 뒤처지면 수집 중단으로 보고 보류
    dataset_max = session.execute(select(_func.max(models.DailyPrice.trading_date))).scalar_one_or_none()
    latest_date = rows[0][0]
    if dataset_max and latest_date and latest_date < (dataset_max - _td(days=7)):
        logger.info("유동성 판정 보류(데이터 중단) %s: 최신 %s < 기준 %s", code, latest_date, dataset_max)
        return [], None

    # 무결성: 절반 이상 volume=0 이면 불량 데이터로 보고 보류
    zero_vol = sum(1 for _d, _c, v, _val in rows if not v)
    if zero_vol * 2 >= len(rows):
        logger.info("유동성 판정 보류(불량 데이터) %s: volume=0 %d/%d일", code, zero_vol, len(rows))
        return [], None

    values: list[float] = []
    for _d, close, volume, value in rows:
        v = float(value) if value else float(close or 0) * float(volume or 0)
        values.append(v)
    avg_value = sum(values) / len(values)
    latest_close = float(rows[0][1] or 0)

    tags: list[str] = []
    details: list[str] = []
    if avg_value < float(min_avg_value):
        tags.append("LOW_LIQUIDITY")
        details.append(f"{len(rows)}일 평균 거래대금 {avg_value / 1e8:.1f}억원 < 기준 {float(min_avg_value) / 1e8:.0f}억원")
    if 0 < latest_close < float(min_price):
        tags.append("PENNY")
        details.append(f"최근 종가 {latest_close:,.0f}원 < 기준 {float(min_price):,.0f}원")
    if tags:
        details.append(f"기준일 {latest_date}")
    return tags, ("; ".join(details) or None)


# ─── 인덱스 갱신 ──────────────────────────────────────────────────────────────

def _write_entry(
    session: Session,
    code: str,
    name: str,
    tags: list[str],
    *,
    source: str,
    detail: str | None = None,
) -> None:
    """tags가 비면 행 삭제, 있으면 upsert. 호출자가 commit 책임."""
    import models

    _ensure_table()
    code = str(code).strip()
    row = session.execute(
        select(models.ExcludedStock).where(models.ExcludedStock.code == code)
    ).scalar_one_or_none()

    if not tags:
        if row is not None:
            session.delete(row)
            invalidate_cache()
        return

    tags_s = ",".join(sorted(set(tags)))
    if row is None:
        session.add(models.ExcludedStock(code=code, name=(name or code), tags=tags_s, source=source, detail=detail))
    else:
        row.tags = tags_s
        row.source = source
        row.last_checked = datetime.now()
        if name:
            row.name = name
        if detail:
            row.detail = detail
    invalidate_cache()


def merge_tags(
    session: Session,
    code: str,
    name: str,
    new_tags: list[str],
    *,
    refresh_categories: set[str],
    source: str,
    detail: str | None = None,
) -> list[str]:
    """카테고리 단위 갱신: refresh_categories에 속한 기존 태그는 new_tags로 대체,
    그 외 카테고리 태그는 보존. 결과 태그 목록 반환."""
    entry = get_entry(session, code)
    preserved = [t for t in (entry["tags"] if entry else []) if t not in refresh_categories]
    final = sorted(set(preserved) | set(new_tags))
    keep_detail = detail if detail is not None else (entry.get("detail") if entry else None)
    _write_entry(session, code, name, final, source=source, detail=keep_detail)
    return final


def record_quote(session: Session, quote: Any) -> list[str]:
    """실시간 시세 응답에서 시장조치/상품유형 태그를 탐지해 인덱스 갱신.

    시장조치+이름 기반 태그는 현재 시세 기준으로 대체(해제 포함),
    스윕 전용 태그(ETF/유동성)와 MANUAL은 보존. 활성 태그 목록 반환.
    """
    code = str(getattr(quote, "code", "") or "").strip()
    if not code:
        return []
    name = str(getattr(quote, "name", "") or "").strip()
    live = set(evaluate_quote_status(quote)) | set(evaluate_static(code, name))
    return merge_tags(
        session, code, name, sorted(live),
        refresh_categories=(MARKET_ACTION_TAGS | STATIC_NAME_TAGS),
        source="quote",
    )


# ─── 의견 거부 메시지 (요구사항 2) ───────────────────────────────────────────

def rejection_payload(code: str, name: str, tags: list[str], detail: str | None = None) -> dict:
    labels = [TAG_LABELS.get(t, t) for t in tags]
    disp = f"{name}({code})" if name else code
    return {
        "ok": False,
        "excluded": True,
        "opinion": "REFUSED",
        "policy": "excluded-stock-no-opinion",
        "code": code,
        "name": name or None,
        "tags": tags,
        "reasons": [{"tag": t, "label": TAG_LABELS.get(t, t)} for t in tags],
        "detail": detail,
        "message": f"[의견 거부] {disp} — 거래 제외 종목입니다. 분석/추천 의견을 제공하지 않습니다. 사유: {', '.join(labels)}",
    }


def gate(session: Session, code: str, name: str = "") -> None:
    """문의/저장 진입 게이트 — 제외 종목이면 ExcludedStockError를 발생시킨다.

    이 에러는 main.py 핸들러가 HTTP 200의 '의견 거부' 메시지(사유 태그 포함)로
    발행한다 — 요청을 에러로 거부하는 것이 아니다.

    인덱스에 없어도 이름/코드 기반 정적 규칙(스팩/우선주/리츠)에 걸리면 즉시 거부하고
    인덱스에 등재한다(최초 발견 시점 기록). 섹터 대표 ETF는 어떤 경우에도 통과시킨다.
    """
    from settings import settings

    if not getattr(settings, "exclusion_enabled", True):
        return

    code = str(code or "").strip()
    if code in sector_etf_codes():
        return  # 섹터 대표 ETF는 제외 금지 (수동 지정보다 우선)
    entry = get_entry(session, code)
    if entry is not None:
        raise ExcludedStockError(
            rejection_payload(code, entry["name"] or name, entry["tags"], entry.get("detail"))
        )

    static_tags = evaluate_static(code, name)
    if static_tags:
        _write_entry(session, code, name, static_tags, source="static")
        try:
            session.commit()
        except Exception:
            session.rollback()
        raise ExcludedStockError(rejection_payload(code, name, static_tags))


# ─── 전수 스윕 (스크립트/관리자 엔드포인트 공용) ────────────────────────────

def run_sweep(
    session: Session,
    *,
    kis_profile: Any | None = None,
    do_kis_status: bool = False,
    kis_call_interval: float = 0.06,
) -> dict:
    """stocks 전 종목에 대해 정적/유동성(+선택: KIS 시장조치) 판정 후 인덱스 재구축.

    kis_profile: app_key/app_secret/is_paper 속성을 가진 객체 (kis_profiles 행).
    do_kis_status=True면 종목당 KIS 현재가 1콜 — 초당 호출 제한을 위해 interval 유지.
    """
    import kis_client
    import models
    from settings import settings

    _ensure_table()

    stocks = session.execute(select(models.Stock.code, models.Stock.name)).all()

    # ETF/ETN 목록 (pykrx — 실패 시 해당 태그 갱신 생략, 기존 값 보존)
    etf_codes: set[str] | None = None
    try:
        from pykrx import stock as _pykrx

        today = datetime.now().strftime("%Y%m%d")
        etf = set(_pykrx.get_etf_ticker_list(today) or [])
        try:
            etn = set(_pykrx.get_etn_ticker_list(today) or [])
        except Exception:
            etn = set()
        etf_codes = etf | etn
    except Exception as exc:
        logger.warning("pykrx ETF/ETN 목록 조회 실패 — ETF_ETN 태그는 기존 값 유지: %s", exc)

    checked = 0
    excluded_count = 0
    kis_errors = 0
    sector_etfs = sector_etf_codes()  # 섹터 대표 ETF는 제외 금지 (정보 정상 저장)

    for code, name in stocks:
        code = str(code).strip()
        name = str(name or "").strip()
        checked += 1

        new_tags: set[str] = set(evaluate_static(code, name))
        refresh: set[str] = set(STATIC_NAME_TAGS)

        if etf_codes is not None:
            refresh.add("ETF_ETN")
            if code in etf_codes and code not in sector_etfs:
                new_tags.add("ETF_ETN")

        liq_tags, liq_detail = evaluate_liquidity(session, code)
        refresh |= {"LOW_LIQUIDITY", "PENNY"}
        new_tags |= set(liq_tags)

        detail = liq_detail

        if do_kis_status and kis_profile is not None:
            try:
                quote = kis_client.inquire_price(
                    app_key=str(kis_profile.app_key),
                    app_secret=str(kis_profile.app_secret),
                    is_paper=bool(getattr(kis_profile, "is_paper", False)),
                    code=code,
                    live_base_url=settings.kis_live_base_url,
                    paper_base_url=settings.kis_paper_base_url,
                    timeout_seconds=5.0,
                )
                refresh |= MARKET_ACTION_TAGS
                new_tags |= set(evaluate_quote_status(quote))
                time.sleep(max(kis_call_interval, 0.0))
            except Exception:
                kis_errors += 1  # 조회 실패 시 시장조치 태그는 기존 값 보존

        final = merge_tags(
            session, code, name, sorted(new_tags),
            refresh_categories=refresh, source="sweep", detail=detail,
        )
        if final:
            excluded_count += 1

        if checked % 200 == 0:
            session.commit()

    session.commit()
    get_exclusions(session, force=True)
    return {
        "checked": checked,
        "excluded": excluded_count,
        "kis_status_checked": bool(do_kis_status and kis_profile is not None),
        "kis_errors": kis_errors,
    }
