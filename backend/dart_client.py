"""dart_client.py

DART(금융감독원 전자공시시스템) OpenAPI 연동.
- 분기별 손익계산서에서 매출, 영업이익, 순이익 추출
- EPS 성장률, 영업이익률, 순이익률 계산
- opendart.fss.or.kr/uss/umt/EgovMberInfoEdit.do 에서 API 키 발급

의존: OpenDartReader (pip install opendartreader)
fallback: API 키 없거나 조회 실패 시 빈 dict 반환 (스코어링 미영향)
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

# DART corp_code 조회 결과를 프로세스 내 캐싱 (1회 로딩 후 재사용)
_CORP_CODE_CACHE: dict[str, str] = {}   # {stock_code_6: corp_code}


def _get_dart(api_key: str):
    """OpenDartReader 인스턴스 반환."""
    try:
        import OpenDartReader
        return OpenDartReader.OpenDartReader(api_key)
    except ImportError as exc:
        raise ImportError("OpenDartReader 미설치: pip install opendartreader") from exc


def lookup_corp_code(stock_code: str, *, api_key: str) -> str | None:
    """6자리 종목코드 → DART corp_code 변환.

    캐싱 적용 (프로세스 수명 동안 유지).
    """
    cached = _CORP_CODE_CACHE.get(stock_code)
    if cached:
        return cached
    try:
        dart = _get_dart(api_key)
        result = dart.find_corp_code(stock_code)
        if result:
            corp_code = str(result)
            _CORP_CODE_CACHE[stock_code] = corp_code
            return corp_code
    except Exception as exc:
        logger.debug("DART corp_code 조회 실패 %s: %s", stock_code, exc)
    return None


def fetch_income_statement(
    stock_code: str,
    *,
    api_key: str,
    year: int | None = None,
    quarters: int = 4,
) -> list[dict[str, Any]]:
    """분기별 손익계산서 조회.

    Returns:
        [{"year": 2024, "quarter": 2, "revenue": 80000, "op_income": 5000,
          "net_income": 3500, "op_margin": 0.062, "net_margin": 0.044}, ...]
        최신 순 정렬. 조회 실패 시 [].
    """
    if not api_key:
        return []

    corp_code = lookup_corp_code(stock_code, api_key=api_key)
    if not corp_code:
        return []

    current_year = year or datetime.now().year

    rows: list[dict[str, Any]] = []
    try:
        dart = _get_dart(api_key)
        for yr in range(current_year, current_year - 2, -1):   # 최근 2년
            for qtr in ["11014", "11013", "11012", "11011"]:   # Q4,Q3,Q2,Q1 순
                # reprt_code: 11011=1Q, 11012=반기, 11013=3Q, 11014=연간
                try:
                    fs = dart.finstate(corp_code, yr, reprt_code=qtr)
                    if fs is None or (hasattr(fs, "empty") and fs.empty):
                        continue

                    # 연결 재무제표 우선, 없으면 별도
                    if hasattr(fs, "iterrows"):
                        rows_df = fs
                    else:
                        continue

                    rev = _extract_account(rows_df, ["매출액", "영업수익"])
                    opi = _extract_account(rows_df, ["영업이익", "영업이익(손실)"])
                    net = _extract_account(rows_df, ["당기순이익", "당기순이익(손실)"])

                    if rev is None:
                        continue

                    quarter_num = {"11011": 1, "11012": 2, "11013": 3, "11014": 4}.get(qtr, 0)
                    op_margin  = float(opi / rev) if (opi is not None and rev and rev != 0) else None
                    net_margin = float(net / rev) if (net is not None and rev and rev != 0) else None

                    rows.append({
                        "year":       yr,
                        "quarter":    quarter_num,
                        "revenue":    rev,
                        "op_income":  opi,
                        "net_income": net,
                        "op_margin":  round(op_margin,  4) if op_margin  is not None else None,
                        "net_margin": round(net_margin, 4) if net_margin is not None else None,
                    })
                    if len(rows) >= quarters:
                        break
                except Exception:
                    continue
            if len(rows) >= quarters:
                break
    except Exception as exc:
        logger.debug("DART finstate 조회 실패 %s: %s", stock_code, exc)

    return rows


def _extract_account(df: Any, account_names: list[str]) -> float | None:
    """DART 재무제표 DataFrame에서 특정 계정과목 값 추출."""
    try:
        import pandas as pd
        if not isinstance(df, pd.DataFrame):
            return None

        # account_nm 컬럼명 후보
        nm_col = next((c for c in df.columns if "account" in c.lower() or "account_nm" in c.lower()), None)
        val_col = next((c for c in df.columns if c in ("thstrm_amount", "thstrm_amt", "당기금액")), None)

        if nm_col is None or val_col is None:
            return None

        for name in account_names:
            mask = df[nm_col].astype(str).str.strip() == name
            matched = df[mask]
            if not matched.empty:
                raw = str(matched.iloc[0][val_col]).replace(",", "").strip()
                try:
                    return float(raw)
                except Exception:
                    continue
    except Exception:
        pass
    return None


def compute_eps_growth(rows: list[dict[str, Any]]) -> float | None:
    """최근 2개 분기(또는 연간) 순이익 기준 YoY EPS 성장률 계산.

    Returns:
        성장률 (예: 0.35 = 35%) 또는 None
    """
    if len(rows) < 2:
        return None
    try:
        latest = rows[0].get("net_income")
        prev   = rows[1].get("net_income")
        if latest is None or prev is None or prev == 0:
            return None
        return round((float(latest) - float(prev)) / abs(float(prev)), 4)
    except Exception:
        return None


def fetch_financials(
    stock_code: str,
    *,
    api_key: str,
) -> dict[str, float | None]:
    """종목 1개 재무 핵심 지표 반환 (스코어링 엔진용).

    Returns:
        {
            "eps_growth":    float | None,   # YoY 순이익 성장률
            "op_margin":     float | None,   # 최근 분기 영업이익률
            "net_margin":    float | None,   # 최근 분기 순이익률
        }
    """
    if not api_key:
        return {}

    try:
        rows = fetch_income_statement(stock_code, api_key=api_key, quarters=4)
        if not rows:
            return {}

        eps_growth = compute_eps_growth(rows)
        latest = rows[0]
        return {
            k: v for k, v in {
                "eps_growth":  eps_growth,
                "op_margin":   latest.get("op_margin"),
                "net_margin":  latest.get("net_margin"),
                "profit_margin": latest.get("net_margin"),   # scoring_engine 호환
            }.items() if v is not None
        }
    except Exception as exc:
        logger.debug("fetch_financials 실패 %s: %s", stock_code, exc)
        return {}


def fetch_financials_batch(
    stock_codes: list[str],
    *,
    api_key: str,
    max_workers: int = 4,
) -> dict[str, dict[str, float | None]]:
    """여러 종목 재무 지표 병렬 조회.

    Returns:
        {stock_code: {"eps_growth": ..., "profit_margin": ..., ...}}
    """
    from concurrent.futures import ThreadPoolExecutor

    if not api_key:
        logger.info("DART_API_KEY 미설정 — 재무 지표 조회 건너뜀")
        return {}

    def _one(code: str) -> tuple[str, dict]:
        result = fetch_financials(code, api_key=api_key)
        return code, result

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = dict(pool.map(_one, stock_codes))

    valid = sum(1 for v in results.values() if v)
    logger.info("DART fetch_financials_batch: %d종목 → 유효 %d건", len(results), valid)
    return results
