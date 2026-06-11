from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from typing import Literal

import httpx


DEFAULT_LIVE_BASE_URL = "https://openapi.koreainvestment.com:9443"
DEFAULT_PAPER_BASE_URL = "https://openapivts.koreainvestment.com:29443"


class KisError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, payload: Any | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


@dataclass(frozen=True)
class KisQuote:
    code: str
    name: str
    price: float
    change: float
    change_rate: float
    as_of: str
    market_name: str = ""
    volume: int = 0
    trading_value: float = 0.0
    trade_strength: float = 0.0
    shares: int = 0  # 상장주식수 (lstn_stcn)
    # 시장조치 상태 (exclusion_engine 소비) — FHKST01010100 output 필드
    status_code: str = ""            # iscd_stat_cls_code 종목상태구분코드 (원본값 보관)
    warn_code: str = ""              # mrkt_warn_cls_code 00없음/01투자주의/02투자경고/03투자위험
    is_admin_issue: bool = False     # mang_issu_cls_code == Y 관리종목
    is_trade_halt: bool = False      # temp_stop_yn == Y 거래정지(임시정지)
    is_liquidation: bool = False     # sltr_yn == Y 정리매매
    is_invest_caution: bool = False  # invt_caful_yn == Y 투자유의
    is_short_overheat: bool = False  # short_over_yn == Y 단기과열


@dataclass
class _TokenCacheItem:
    access_token: str
    expires_at: datetime


_TOKEN_CACHE: dict[tuple[str, bool], _TokenCacheItem] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _base_url(is_paper: bool, *, live_base_url: str | None = None, paper_base_url: str | None = None) -> str:
    if is_paper:
        return (paper_base_url or DEFAULT_PAPER_BASE_URL).rstrip("/")
    return (live_base_url or DEFAULT_LIVE_BASE_URL).rstrip("/")


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def get_access_token(
    *,
    app_key: str,
    app_secret: str,
    is_paper: bool,
    force_refresh: bool = False,
    live_base_url: str | None = None,
    paper_base_url: str | None = None,
    timeout_seconds: float = 10.0,
) -> tuple[str, int]:
    """Return (access_token, expires_in_seconds). Uses in-memory caching."""

    cache_key = (app_key, is_paper)
    cached = _TOKEN_CACHE.get(cache_key)
    if cached is not None:
        # Keep a small skew to avoid edge expiry.
        if (not force_refresh) and (cached.expires_at - _utcnow() > timedelta(seconds=30)):
            remaining = int((cached.expires_at - _utcnow()).total_seconds())
            return cached.access_token, max(remaining, 0)

    base = _base_url(is_paper, live_base_url=live_base_url, paper_base_url=paper_base_url)
    url = f"{base}/oauth2/tokenP"

    payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret,
    }

    try:
        resp = httpx.post(url, json=payload, timeout=timeout_seconds)
    except Exception as exc:
        raise KisError(f"KIS token request failed: {exc}") from exc

    data = _safe_json(resp)
    if resp.status_code >= 400:
        msg = data.get("msg1") or data.get("message") or f"HTTP {resp.status_code}"
        raise KisError(f"KIS token HTTP error: {msg}", status_code=resp.status_code, payload=data)

    token = data.get("access_token")
    expires_in = int(data.get("expires_in") or 0)
    if not token:
        raise KisError("KIS token response missing access_token", status_code=resp.status_code, payload=data)

    expires_at = _utcnow() + timedelta(seconds=max(expires_in, 0))
    _TOKEN_CACHE[cache_key] = _TokenCacheItem(access_token=token, expires_at=expires_at)

    return token, expires_in


def inquire_price(
    *,
    app_key: str,
    app_secret: str,
    is_paper: bool,
    code: str,
    live_base_url: str | None = None,
    paper_base_url: str | None = None,
    timeout_seconds: float = 10.0,
) -> KisQuote:
    """Domestic stock current price (inquire-price)."""

    code = code.strip()
    if not code:
        raise KisError("code is required")

    token, _expires_in = get_access_token(
        app_key=app_key,
        app_secret=app_secret,
        is_paper=is_paper,
        live_base_url=live_base_url,
        paper_base_url=paper_base_url,
        timeout_seconds=timeout_seconds,
    )

    base = _base_url(is_paper, live_base_url=live_base_url, paper_base_url=paper_base_url)
    url = f"{base}/uapi/domestic-stock/v1/quotations/inquire-price"

    headers = {
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        # Common TR id for domestic price inquiry.
        "tr_id": "FHKST01010100",
        "custtype": "P",
    }

    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": code,
    }

    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=timeout_seconds)
    except Exception as exc:
        raise KisError(f"KIS inquire-price request failed: {exc}") from exc

    data = _safe_json(resp)
    if resp.status_code >= 400:
        msg = data.get("msg1") or data.get("message") or f"HTTP {resp.status_code}"
        raise KisError(f"KIS inquire-price HTTP error: {msg}", status_code=resp.status_code, payload=data)

    # KIS returns { rt_cd, msg_cd, msg1, output: {...} }
    rt_cd = str(data.get("rt_cd") or "")
    if rt_cd and rt_cd != "0":
        msg = data.get("msg1") or "KIS error"
        raise KisError(f"KIS inquire-price error: {msg}", status_code=resp.status_code, payload=data)

    output = data.get("output") or {}

    name = str(
        output.get("hts_kor_isnm")
        or output.get("HTS_KOR_ISNM")
        or output.get("prdt_name")
        or output.get("PRDT_NAME")
        or ""
    ).strip()
    market_name = str(
        output.get("bstp_kor_isnm")
        or output.get("BSTP_KOR_ISNM")
        or output.get("rprs_mrkt_kor_name")
        or output.get("RPRS_MRKT_KOR_NAME")
        or ""
    ).strip()

    def _to_float(value: Any) -> float:
        try:
            return float(str(value).replace(",", ""))
        except Exception:
            return 0.0

    price = _to_float(output.get("stck_prpr"))
    change = _to_float(output.get("prdy_vrss"))
    change_rate = _to_float(output.get("prdy_ctrt"))
    volume = int(_to_float(output.get("acml_vol") or output.get("ACML_VOL")))
    trading_value = _to_float(output.get("acml_tr_pbmn") or output.get("ACML_TR_PBMN"))
    trade_strength = _to_float(
        output.get("cttr") or output.get("CTTR") or output.get("tday_rltv") or output.get("TDAY_RLTV")
    )
    shares = int(_to_float(output.get("lstn_stcn") or output.get("LSTN_STCN")))

    as_of = output.get("stck_cntg_hour") or datetime.now().isoformat()

    def _yn(*keys: str) -> bool:
        for k in keys:
            v = str(output.get(k) or output.get(k.upper()) or "").strip().upper()
            if v == "Y":
                return True
        return False

    def _s(*keys: str) -> str:
        for k in keys:
            v = str(output.get(k) or output.get(k.upper()) or "").strip()
            if v:
                return v
        return ""

    return KisQuote(
        code=code,
        name=name,
        price=price,
        change=change,
        change_rate=change_rate,
        as_of=str(as_of),
        market_name=market_name,
        volume=volume,
        trading_value=trading_value,
        trade_strength=trade_strength,
        shares=shares,
        status_code=_s("iscd_stat_cls_code"),
        warn_code=_s("mrkt_warn_cls_code"),
        is_admin_issue=_yn("mang_issu_cls_code"),
        is_trade_halt=_yn("temp_stop_yn"),
        is_liquidation=_yn("sltr_yn"),
        is_invest_caution=_yn("invt_caful_yn"),
        is_short_overheat=_yn("short_over_yn"),
    )


def generate_hashkey(
    *,
    app_key: str,
    app_secret: str,
    is_paper: bool,
    payload: dict[str, Any],
    live_base_url: str | None = None,
    paper_base_url: str | None = None,
    timeout_seconds: float = 10.0,
) -> str:
    """Generate hashkey for trading POST APIs.

    KIS requires a hashkey header for certain trading endpoints.
    """

    base = _base_url(is_paper, live_base_url=live_base_url, paper_base_url=paper_base_url)
    url = f"{base}/uapi/hashkey"

    headers = {
        "content-type": "application/json",
        "appkey": app_key,
        "appsecret": app_secret,
    }

    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=timeout_seconds)
    except Exception as exc:
        raise KisError(f"KIS hashkey request failed: {exc}") from exc

    data = _safe_json(resp)
    if resp.status_code >= 400:
        msg = data.get("msg1") or data.get("message") or f"HTTP {resp.status_code}"
        raise KisError(f"KIS hashkey HTTP error: {msg}", status_code=resp.status_code, payload=data)

    # Most responses include { HASH: "..." }
    key = data.get("HASH") or data.get("hash") or data.get("hashkey")
    if not key:
        raise KisError("KIS hashkey response missing HASH", status_code=resp.status_code, payload=data)
    return str(key)


def place_cash_order(
    *,
    app_key: str,
    app_secret: str,
    is_paper: bool,
    account_prefix: str,
    account_product_code: str = "01",
    side: Literal["buy", "sell"],
    code: str,
    qty: int,
    order_type: Literal["market", "limit"] = "market",
    limit_price: float | None = None,
    live_base_url: str | None = None,
    paper_base_url: str | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Place a domestic stock cash order.

    Returns the raw JSON payload for logging/auditing.
    """

    code = code.strip()
    if not code:
        raise KisError("code is required")
    if qty <= 0:
        raise KisError("qty must be > 0")

    token, _expires_in = get_access_token(
        app_key=app_key,
        app_secret=app_secret,
        is_paper=is_paper,
        live_base_url=live_base_url,
        paper_base_url=paper_base_url,
        timeout_seconds=timeout_seconds,
    )

    base = _base_url(is_paper, live_base_url=live_base_url, paper_base_url=paper_base_url)
    url = f"{base}/uapi/domestic-stock/v1/trading/order-cash"

    # KIS order type: 00=limit, 01=market (commonly)
    ord_dvsn = "01" if order_type == "market" else "00"
    ord_unpr = "0"
    if order_type == "limit":
        if limit_price is None:
            raise KisError("limit_price is required for limit orders")
        try:
            ord_unpr = str(int(round(float(limit_price))))
        except Exception as exc:
            raise KisError("invalid limit_price") from exc

    body = {
        "CANO": str(account_prefix).strip(),
        "ACNT_PRDT_CD": str(account_product_code).zfill(2),
        "PDNO": code,
        "ORD_DVSN": ord_dvsn,
        "ORD_QTY": str(int(qty)),
        "ORD_UNPR": ord_unpr,
    }

    tr_id = None
    if side == "buy":
        tr_id = "VTTC0802U" if is_paper else "TTTC0802U"
    elif side == "sell":
        tr_id = "VTTC0801U" if is_paper else "TTTC0801U"
    else:
        raise KisError("side must be buy|sell")

    hashkey = generate_hashkey(
        app_key=app_key,
        app_secret=app_secret,
        is_paper=is_paper,
        payload=body,
        live_base_url=live_base_url,
        paper_base_url=paper_base_url,
        timeout_seconds=timeout_seconds,
    )

    headers = {
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",
        "hashkey": hashkey,
    }

    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=timeout_seconds)
    except Exception as exc:
        raise KisError(f"KIS order request failed: {exc}") from exc

    data = _safe_json(resp)
    if resp.status_code >= 400:
        msg = data.get("msg1") or data.get("message") or f"HTTP {resp.status_code}"
        raise KisError(f"KIS order HTTP error: {msg}", status_code=resp.status_code, payload=data)

    rt_cd = str(data.get("rt_cd") or "")
    if rt_cd and rt_cd != "0":
        msg = data.get("msg1") or "KIS error"
        raise KisError(f"KIS order error: {msg}", status_code=resp.status_code, payload=data)

    return data


def inquire_balance(
    *,
    app_key: str,
    app_secret: str,
    is_paper: bool,
    account_prefix: str,
    account_product_code: str = "01",
    live_base_url: str | None = None,
    paper_base_url: str | None = None,
    timeout_seconds: float = 10.0,
    ctx_area_fk100: str = "",
    ctx_area_nk100: str = "",
) -> dict[str, Any]:
    """Inquire domestic stock balance/holdings.

    Returns raw JSON. Callers can parse output1 holdings list.
    """

    token, _expires_in = get_access_token(
        app_key=app_key,
        app_secret=app_secret,
        is_paper=is_paper,
        live_base_url=live_base_url,
        paper_base_url=paper_base_url,
        timeout_seconds=timeout_seconds,
    )

    base = _base_url(is_paper, live_base_url=live_base_url, paper_base_url=paper_base_url)
    url = f"{base}/uapi/domestic-stock/v1/trading/inquire-balance"

    tr_id = "VTTC8434R" if is_paper else "TTTC8434R"
    headers = {
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",
    }

    params = {
        "CANO": str(account_prefix).strip(),
        "ACNT_PRDT_CD": str(account_product_code).zfill(2),
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",
        "CTX_AREA_FK100": ctx_area_fk100,
        "CTX_AREA_NK100": ctx_area_nk100,
    }

    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=timeout_seconds)
    except Exception as exc:
        raise KisError(f"KIS inquire-balance request failed: {exc}") from exc

    data = _safe_json(resp)
    if resp.status_code >= 400:
        msg = data.get("msg1") or data.get("message") or f"HTTP {resp.status_code}"
        raise KisError(f"KIS inquire-balance HTTP error: {msg}", status_code=resp.status_code, payload=data)

    rt_cd = str(data.get("rt_cd") or "")
    if rt_cd and rt_cd != "0":
        msg = data.get("msg1") or "KIS error"
        raise KisError(f"KIS inquire-balance error: {msg}", status_code=resp.status_code, payload=data)

    return data


# ─── 수급 데이터 조회 ──────────────────────────────────────────────────────────

def inquire_investor(
    *,
    app_key: str,
    app_secret: str,
    is_paper: bool,
    code: str,
    period_div: str = "D",
    start_date: str = "",
    end_date: str = "",
    live_base_url: str | None = None,
    paper_base_url: str | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """투자자별 매매 동향 조회 (외국인/기관/개인 누적 순매수).

    TR: FHKST01010900 (국내주식 투자자별 매매동향)

    Args:
        period_div: "D"=일별, "W"=주별, "M"=월별
        start_date: "YYYYMMDD", 빈 문자열이면 오늘 기준 30거래일
        end_date:   "YYYYMMDD", 빈 문자열이면 오늘

    Returns raw KIS JSON. output 리스트에 날짜별 매매 내역.
    각 행: stck_bsop_date, frgn_ntby_qty(외국인 순매수), orgn_ntby_qty(기관), etc.
    """
    from datetime import date as _date

    code = code.strip()
    if not code:
        raise KisError("code is required")

    token, _ = get_access_token(
        app_key=app_key,
        app_secret=app_secret,
        is_paper=is_paper,
        live_base_url=live_base_url,
        paper_base_url=paper_base_url,
        timeout_seconds=timeout_seconds,
    )
    base = _base_url(is_paper, live_base_url=live_base_url, paper_base_url=paper_base_url)
    url = f"{base}/uapi/domestic-stock/v1/quotations/inquire-investor"

    if not end_date:
        end_date = _date.today().strftime("%Y%m%d")
    if not start_date:
        # 약 30 거래일 전 (≈42 캘린더일)
        from datetime import timedelta
        start_date = (_date.today() - timedelta(days=42)).strftime("%Y%m%d")

    headers = {
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST01010900",
        "custtype": "P",
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": code,
        "FID_INPUT_DATE_1": start_date,
        "FID_INPUT_DATE_2": end_date,
        "FID_PERIOD_DIV_CODE": period_div,
    }

    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=timeout_seconds)
    except Exception as exc:
        raise KisError(f"KIS inquire-investor request failed: {exc}") from exc

    data = _safe_json(resp)
    if resp.status_code >= 400:
        msg = data.get("msg1") or data.get("message") or f"HTTP {resp.status_code}"
        raise KisError(f"KIS inquire-investor HTTP error: {msg}", status_code=resp.status_code, payload=data)

    rt_cd = str(data.get("rt_cd") or "")
    if rt_cd and rt_cd != "0":
        msg = data.get("msg1") or "KIS error"
        raise KisError(f"KIS inquire-investor error: {msg}", status_code=resp.status_code, payload=data)

    return data


def parse_investor_flow(data: dict[str, Any], lookback_days: int = 7) -> dict[str, int]:
    """inquire_investor 응답 → 수급 딕셔너리 변환.

    Returns:
        {
            "foreign_net_buy_days": int,   # 최근 N일 중 외국인 순매수 연속 일수
            "inst_net_buy_days":    int,   # 최근 N일 중 기관 순매수 연속 일수
            "foreign_net_qty":      int,   # 최근 N일 누적 외국인 순매수량
            "inst_net_qty":         int,   # 최근 N일 누적 기관 순매수량
        }
    """
    rows = data.get("output") or []
    if not isinstance(rows, list):
        rows = [rows] if rows else []

    # 최신 날짜 순 정렬
    def _date_key(r: dict) -> str:
        return str(r.get("stck_bsop_date") or "")

    rows_sorted = sorted(rows, key=_date_key, reverse=True)[:lookback_days]

    def _int(v: Any) -> int:
        try:
            return int(str(v or 0).replace(",", "").strip() or 0)
        except Exception:
            return 0

    # 연속 순매수 일수 (최신부터 카운트)
    foreign_streak = 0
    inst_streak = 0
    for i, row in enumerate(rows_sorted):
        fq = _int(row.get("frgn_ntby_qty") or row.get("FRGN_NTBY_QTY"))
        iq = _int(row.get("orgn_ntby_qty") or row.get("ORGN_NTBY_QTY"))
        if i == foreign_streak and fq > 0:
            foreign_streak += 1
        if i == inst_streak and iq > 0:
            inst_streak += 1

    foreign_net_qty = sum(_int(r.get("frgn_ntby_qty") or r.get("FRGN_NTBY_QTY")) for r in rows_sorted)
    inst_net_qty    = sum(_int(r.get("orgn_ntby_qty") or r.get("ORGN_NTBY_QTY")) for r in rows_sorted)

    return {
        "foreign_net_buy_days": foreign_streak,
        "inst_net_buy_days":    inst_streak,
        "foreign_net_qty":      foreign_net_qty,
        "inst_net_qty":         inst_net_qty,
    }


def inquire_program_trade(
    *,
    app_key: str,
    app_secret: str,
    is_paper: bool,
    code: str,
    start_date: str = "",
    end_date: str = "",
    live_base_url: str | None = None,
    paper_base_url: str | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """프로그램 매매 동향 조회.

    TR: FHPPG04650100 (국내주식 프로그램매매 추이(종목))
    각 행: bsop_date, whol_ntby_qty(전체 순매수), whol_ntby_tr_pbmn(순매수 대금)
    """
    from datetime import date as _date, timedelta

    code = code.strip()
    if not code:
        raise KisError("code is required")

    token, _ = get_access_token(
        app_key=app_key,
        app_secret=app_secret,
        is_paper=is_paper,
        live_base_url=live_base_url,
        paper_base_url=paper_base_url,
        timeout_seconds=timeout_seconds,
    )
    base = _base_url(is_paper, live_base_url=live_base_url, paper_base_url=paper_base_url)
    url = f"{base}/uapi/domestic-stock/v1/quotations/program-trade-by-stock"

    if not end_date:
        end_date = _date.today().strftime("%Y%m%d")
    if not start_date:
        start_date = (_date.today() - timedelta(days=14)).strftime("%Y%m%d")

    headers = {
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHPPG04650100",
        "custtype": "P",
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": code,
        "FID_INPUT_DATE_1": start_date,
        "FID_INPUT_DATE_2": end_date,
        "FID_PERIOD_DIV_CODE": "D",
    }

    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=timeout_seconds)
    except Exception as exc:
        raise KisError(f"KIS program-trade request failed: {exc}") from exc

    data = _safe_json(resp)
    if resp.status_code >= 400:
        msg = data.get("msg1") or data.get("message") or f"HTTP {resp.status_code}"
        raise KisError(f"KIS program-trade HTTP error: {msg}", status_code=resp.status_code, payload=data)

    rt_cd = str(data.get("rt_cd") or "")
    if rt_cd and rt_cd != "0":
        msg = data.get("msg1") or "KIS error"
        raise KisError(f"KIS program-trade error: {msg}", status_code=resp.status_code, payload=data)

    return data


def parse_program_trade(data: dict[str, Any], lookback_days: int = 5) -> int:
    """inquire_program_trade 응답 → 프로그램 순매수 연속 일수."""
    rows = data.get("output") or []
    if not isinstance(rows, list):
        rows = [rows] if rows else []

    def _date_key(r: dict) -> str:
        return str(r.get("bsop_date") or r.get("stck_bsop_date") or "")

    rows_sorted = sorted(rows, key=_date_key, reverse=True)[:lookback_days]

    def _int(v: Any) -> int:
        try:
            return int(str(v or 0).replace(",", "").strip() or 0)
        except Exception:
            return 0

    streak = 0
    for i, row in enumerate(rows_sorted):
        qty = _int(row.get("whol_ntby_qty") or row.get("WHOL_NTBY_QTY"))
        if i == streak and qty > 0:
            streak += 1
        else:
            break
    return streak


def inquire_daily_chart(
    *,
    app_key: str,
    app_secret: str,
    is_paper: bool,
    code: str,
    period: str = "D",  # D=일봉 W=주봉 M=월봉 Y=년봉
    end_date: str | None = None,  # YYYYMMDD — 이 날짜까지의 100봉 (장기 이력 페이지네이션용)
    live_base_url: str | None = None,
    paper_base_url: str | None = None,
    timeout_seconds: float = 10.0,
) -> list[dict[str, Any]]:
    """국내주식 기간별 시세 (TR FHKST03010100) — 한 번에 최대 100봉, 수정주가.

    반환: 과거→현재 순 [{date, open, high, low, close, volume}].
    """
    from datetime import date as _date, datetime as _dt, timedelta as _td

    code = code.strip()
    token, _ = get_access_token(
        app_key=app_key, app_secret=app_secret, is_paper=is_paper,
        live_base_url=live_base_url, paper_base_url=paper_base_url,
        timeout_seconds=timeout_seconds,
    )
    base = _base_url(is_paper, live_base_url=live_base_url, paper_base_url=paper_base_url)
    url = f"{base}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"

    # 100봉을 덮는 달력 범위 (D: 150일, W: 750일, M: 3200일)
    span = {"D": 150, "W": 750, "M": 3200, "Y": 36500}.get(period, 150)
    end = _dt.strptime(end_date, "%Y%m%d").date() if end_date else _date.today()
    start = end - _td(days=span)

    headers = {
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST03010100",
        "custtype": "P",
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": code,
        "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
        "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
        "FID_PERIOD_DIV_CODE": period,
        "FID_ORG_ADJ_PRC": "0",
    }
    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=timeout_seconds)
    except Exception as exc:
        raise KisError(f"KIS daily-chart request failed: {exc}") from exc
    data = _safe_json(resp)
    if resp.status_code >= 400 or str(data.get("rt_cd") or "") not in ("", "0"):
        msg = data.get("msg1") or f"HTTP {resp.status_code}"
        raise KisError(f"KIS daily-chart error: {msg}", status_code=resp.status_code, payload=data)

    def _f(row: dict, key: str) -> float:
        try:
            return float(str(row.get(key) or "0").replace(",", ""))
        except Exception:
            return 0.0

    out = []
    for row in data.get("output2") or []:
        d = str(row.get("stck_bsop_date") or "")
        if not d:
            continue
        out.append({
            "date": d,
            "open": _f(row, "stck_oprc"),
            "high": _f(row, "stck_hgpr"),
            "low": _f(row, "stck_lwpr"),
            "close": _f(row, "stck_clpr"),
            "volume": _f(row, "acml_vol"),
        })
    out.sort(key=lambda r: r["date"])
    return out


def inquire_minute_chart(
    *,
    app_key: str,
    app_secret: str,
    is_paper: bool,
    code: str,
    max_calls: int = 13,
    live_base_url: str | None = None,
    paper_base_url: str | None = None,
    timeout_seconds: float = 10.0,
) -> list[dict[str, Any]]:
    """당일 1분봉 (TR FHKST03010200) — 호출당 30건, 뒤에서부터 연속 조회로 전일장 커버.

    반환: 과거→현재 순 [{time(HHMMSS), open, high, low, close, volume}].
    """
    import time as _time

    code = code.strip()
    token, _ = get_access_token(
        app_key=app_key, app_secret=app_secret, is_paper=is_paper,
        live_base_url=live_base_url, paper_base_url=paper_base_url,
        timeout_seconds=timeout_seconds,
    )
    base = _base_url(is_paper, live_base_url=live_base_url, paper_base_url=paper_base_url)
    url = f"{base}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
    headers = {
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST03010200",
        "custtype": "P",
    }

    def _f(row: dict, key: str) -> float:
        try:
            return float(str(row.get(key) or "0").replace(",", ""))
        except Exception:
            return 0.0

    bars: dict[str, dict] = {}
    hour = "153000"
    for _ in range(max_calls):
        params = {
            "FID_ETC_CLS_CODE": "",
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_HOUR_1": hour,
            "FID_PW_DATA_INCU_YN": "N",
        }
        try:
            resp = httpx.get(url, headers=headers, params=params, timeout=timeout_seconds)
        except Exception as exc:
            raise KisError(f"KIS minute-chart request failed: {exc}") from exc
        data = _safe_json(resp)
        if resp.status_code >= 400 or str(data.get("rt_cd") or "") not in ("", "0"):
            break
        rows = data.get("output2") or []
        if not rows:
            break
        earliest = None
        for row in rows:
            t = str(row.get("stck_cntg_hour") or "")
            if not t:
                continue
            bars[t] = {
                "time": t,
                "open": _f(row, "stck_oprc"),
                "high": _f(row, "stck_hgpr"),
                "low": _f(row, "stck_lwpr"),
                "close": _f(row, "stck_prpr"),
                "volume": _f(row, "cntg_vol"),
            }
            if earliest is None or t < earliest:
                earliest = t
        if earliest is None or earliest <= "090100":
            break
        # 다음 호출: 가장 이른 봉 직전 분
        hh, mm = int(earliest[:2]), int(earliest[2:4])
        mm -= 1
        if mm < 0:
            hh, mm = hh - 1, 59
        hour = f"{hh:02d}{mm:02d}00"
        _time.sleep(0.08)

    return [bars[k] for k in sorted(bars)]


def inquire_daily_minute_chart(
    *,
    app_key: str,
    app_secret: str,
    is_paper: bool,
    code: str,
    date_yyyymmdd: str,
    live_base_url: str | None = None,
    paper_base_url: str | None = None,
    timeout_seconds: float = 10.0,
) -> list[dict[str, Any]]:
    """특정 일자의 1분봉 전체 (TR FHKST03010230, 일별분봉조회) — 호출당 120건, 하루 4콜.

    반환: 과거→현재 순 [{date, time, open, high, low, close, volume}].
    """
    import time as _time

    code = code.strip()
    token, _ = get_access_token(
        app_key=app_key, app_secret=app_secret, is_paper=is_paper,
        live_base_url=live_base_url, paper_base_url=paper_base_url,
        timeout_seconds=timeout_seconds,
    )
    base = _base_url(is_paper, live_base_url=live_base_url, paper_base_url=paper_base_url)
    url = f"{base}/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice"
    headers = {
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST03010230",
        "custtype": "P",
    }

    def _f(row: dict, key: str) -> float:
        try:
            return float(str(row.get(key) or "0").replace(",", ""))
        except Exception:
            return 0.0

    bars: dict[str, dict] = {}
    hour = "153000"
    for _ in range(5):  # 390분 / 120봉 = 4콜이면 전체 커버 (+1 여유)
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_DATE_1": date_yyyymmdd,
            "FID_INPUT_HOUR_1": hour,
            "FID_PW_DATA_INCU_YN": "N",
            "FID_FAKE_TICK_INCU_YN": "N",
        }
        try:
            resp = httpx.get(url, headers=headers, params=params, timeout=timeout_seconds)
        except Exception as exc:
            raise KisError(f"KIS daily-minute request failed: {exc}") from exc
        data = _safe_json(resp)
        if resp.status_code >= 400 or str(data.get("rt_cd") or "") not in ("", "0"):
            break
        rows = data.get("output2") or []
        if not rows:
            break
        earliest = None
        for row in rows:
            t = str(row.get("stck_cntg_hour") or "")
            if not t:
                continue
            bars[t] = {
                "date": date_yyyymmdd,
                "time": t,
                "open": _f(row, "stck_oprc"),
                "high": _f(row, "stck_hgpr"),
                "low": _f(row, "stck_lwpr"),
                "close": _f(row, "stck_prpr"),
                "volume": _f(row, "cntg_vol"),
            }
            if earliest is None or t < earliest:
                earliest = t
        if earliest is None or earliest <= "090100":
            break
        hh, mm = int(earliest[:2]), int(earliest[2:4])
        mm -= 1
        if mm < 0:
            hh, mm = hh - 1, 59
        hour = f"{hh:02d}{mm:02d}00"
        _time.sleep(0.08)

    return [bars[k] for k in sorted(bars)]


def inquire_short_sale(
    *,
    app_key: str,
    app_secret: str,
    is_paper: bool,
    code: str,
    days: int = 60,
    live_base_url: str | None = None,
    paper_base_url: str | None = None,
    timeout_seconds: float = 10.0,
) -> list[dict[str, Any]]:
    """국내주식 공매도 일별추이 (TR FHPST04830000).

    반환: 과거→현재 순 [{date, close, shortQty(공매도 수량), shortRatio(거래량 대비 %)}].
    대차잔고는 KIS 미제공 — 공매도 비중 추이가 수급 압력의 대용 지표.
    """
    from datetime import date as _date, timedelta as _td

    code = code.strip()
    token, _ = get_access_token(
        app_key=app_key, app_secret=app_secret, is_paper=is_paper,
        live_base_url=live_base_url, paper_base_url=paper_base_url,
        timeout_seconds=timeout_seconds,
    )
    base = _base_url(is_paper, live_base_url=live_base_url, paper_base_url=paper_base_url)
    url = f"{base}/uapi/domestic-stock/v1/quotations/daily-short-sale"
    end = _date.today()
    start = end - _td(days=days)
    headers = {
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHPST04830000",
        "custtype": "P",
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": code,
        "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
        "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
    }
    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=timeout_seconds)
    except Exception as exc:
        raise KisError(f"KIS short-sale request failed: {exc}") from exc
    data = _safe_json(resp)
    if resp.status_code >= 400 or str(data.get("rt_cd") or "") not in ("", "0"):
        msg = data.get("msg1") or f"HTTP {resp.status_code}"
        raise KisError(f"KIS short-sale error: {msg}", status_code=resp.status_code, payload=data)

    def _f(row: dict, key: str) -> float:
        try:
            return float(str(row.get(key) or "0").replace(",", ""))
        except Exception:
            return 0.0

    out = []
    for row in data.get("output2") or []:
        d = str(row.get("stck_bsop_date") or "")
        if not d:
            continue
        out.append({
            "date": d,
            "close": _f(row, "stck_clpr"),
            "shortQty": _f(row, "ssts_cntg_qty"),
            "shortRatio": _f(row, "ssts_vol_rlim"),
        })
    out.sort(key=lambda r: r["date"])
    return out
