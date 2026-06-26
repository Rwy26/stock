"""멀티 타임프레임(MTF) 차트 분석 — 시장 나침반 8단계.

월봉 → 주봉 → 일봉 → 60분 → 15분 순서로 분석한다.
(4시간봉은 한국 정규장이 6.5시간이라 의미가 없어 60분으로 대체 — 출력에 명시)

판단 항목 (전부 결정론 계산, LLM 없음):
  추세        : EMA20/60 배열 + 스윙 구조(HH/HL vs LH/LL)
  BOS/CHoCH  : 스윙 고저점 돌파 이벤트 (Break of Structure / Change of Character)
  유동성      : 미청산 스윙 고점/저점 (위·아래 유동성 풀)
  매물대      : 거래량 프로파일 상위 3개 가격대 (HVN)
  피보나치    : 주 스윙 되돌림(0.382/0.5/0.618/0.786) + 확장(1.272/1.618)
  거래량      : 최근 5봉 vs 20봉 평균 비율
  CDV        : 누적 델타 볼륨 근사 (양봉 +vol / 음봉 -vol) 방향
  RSI        : Wilder 14

데이터: KIS 차트 API (일/주/월봉 100개씩 + 당일 1분봉 → 15분/60분 리샘플).
분봉은 KIS 제약상 당일만 제공 — 60분/15분 판단은 당일 인트라데이 기준임을 명시.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# 지표 계산 (순수 파이썬)
# ---------------------------------------------------------------------------
def _rsi(closes: list[float], n: int = 14) -> Optional[float]:
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    avg_g, avg_l = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        g = max(d, 0.0)
        l = max(-d, 0.0)
        avg_g = (avg_g * (n - 1) + g) / n
        avg_l = (avg_l * (n - 1) + l) / n
    if avg_l == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_g / avg_l), 1)


def _ema(values: list[float], n: int) -> Optional[float]:
    if len(values) < n:
        return None
    k = 2 / (n + 1)
    e = sum(values[:n]) / n
    for v in values[n:]:
        e = v * k + e * (1 - k)
    return e


def _swings(highs: list[float], lows: list[float], n: int = 2) -> list[dict]:
    """프랙탈 스윙 포인트: 좌우 n봉보다 높은 고점 / 낮은 저점."""
    out = []
    for i in range(n, len(highs) - n):
        if highs[i] == max(highs[i - n:i + n + 1]):
            out.append({"idx": i, "type": "H", "price": highs[i]})
        if lows[i] == min(lows[i - n:i + n + 1]):
            out.append({"idx": i, "type": "L", "price": lows[i]})
    return out


def _structure(swings: list[dict], closes: list[float]) -> dict:
    """추세(스윙 구조) + BOS/CHoCH 이벤트."""
    hs = [s for s in swings if s["type"] == "H"]
    ls = [s for s in swings if s["type"] == "L"]
    trend = "중립"
    if len(hs) >= 2 and len(ls) >= 2:
        hh = hs[-1]["price"] > hs[-2]["price"]
        hl = ls[-1]["price"] > ls[-2]["price"]
        if hh and hl:
            trend = "상승 (HH+HL)"
        elif (not hh) and (not hl):
            trend = "하락 (LH+LL)"
        else:
            trend = "횡보 (구조 혼재)"

    event = None
    cur = closes[-1] if closes else 0.0
    if hs and cur > hs[-1]["price"]:
        event = {"type": "BOS↑" if "상승" in trend else "CHoCH↑",
                 "level": hs[-1]["price"],
                 "desc": "직전 스윙 고점 상향 돌파"}
    elif ls and cur < ls[-1]["price"]:
        event = {"type": "BOS↓" if "하락" in trend else "CHoCH↓",
                 "level": ls[-1]["price"],
                 "desc": "직전 스윙 저점 하향 이탈"}
    return {"trend": trend, "event": event}


def _liquidity(swings: list[dict], cur: float) -> dict:
    """미청산 유동성 풀: 현재가 위 최근접 스윙 고점 / 아래 최근접 스윙 저점."""
    above = [s["price"] for s in swings if s["type"] == "H" and s["price"] > cur]
    below = [s["price"] for s in swings if s["type"] == "L" and s["price"] < cur]
    return {
        "above": min(above) if above else None,   # 상방 유동성 (손절·돌파 매수 대기)
        "below": max(below) if below else None,   # 하방 유동성
    }


def _volume_profile_full(bars: list[dict], bins: int = 100, va_pct: float = 0.70) -> dict:
    """H/L/V 기반 Volume Profile — POC, VAH(70% 가치구간 상단), VAL(하단), HVN 상위5.

    bars: [{"high": float, "low": float, "volume": int}, ...]  (일봉 OHLCV 호환)
    각 캔들 거래량을 고가~저가 범위에 균등 분배해 가격대별 누적 거래량 히스토그램 산출.
    """
    valid = [b for b in bars if b.get("high") and b.get("low") and b.get("volume")]
    if len(valid) < 10:
        return {}
    lo = min(b["low"] for b in valid)
    hi = max(b["high"] for b in valid)
    if hi <= lo:
        return {}

    step = (hi - lo) / bins
    buckets = [0.0] * bins

    for b in valid:
        b0 = max(0, int((b["low"] - lo) / step))
        b1 = min(bins - 1, int((b["high"] - lo) / step))
        span = b1 - b0 + 1
        vpb = b["volume"] / span
        for i in range(b0, b1 + 1):
            buckets[i] += vpb

    poc_idx = max(range(bins), key=lambda i: buckets[i])
    poc = lo + (poc_idx + 0.5) * step

    total = sum(buckets) or 1.0
    target_vol = total * va_pct
    lo_i, hi_i = poc_idx, poc_idx
    acc = buckets[poc_idx]
    while acc < target_vol:
        add_lo = buckets[lo_i - 1] if lo_i > 0 else 0.0
        add_hi = buckets[hi_i + 1] if hi_i < bins - 1 else 0.0
        if add_lo >= add_hi and lo_i > 0:
            lo_i -= 1
            acc += buckets[lo_i]
        elif hi_i < bins - 1:
            hi_i += 1
            acc += buckets[hi_i]
        else:
            break

    zones = [
        {
            "priceFrom": round(lo + i * step),
            "priceTo": round(lo + (i + 1) * step),
            "midPrice": round(lo + (i + 0.5) * step),
            "volumePct": round(buckets[i] / total * 100, 1),
        }
        for i in range(bins)
    ]
    ranked_idx = sorted(range(bins), key=lambda i: -buckets[i])[:5]
    hvn = [zones[i] for i in sorted(ranked_idx)]

    return {
        "poc": round(poc),
        "vah": round(lo + (hi_i + 1) * step),
        "val": round(lo + lo_i * step),
        "hvn": hvn,
        "zones": zones,   # 전 구간 — 필터링용, JSON 직렬화 시 제외 권장
        "lookback": len(valid),
    }


def _volume_profile(closes: list[float], volumes: list[float], bins: int = 12) -> list[dict]:
    """매물대: 가격 구간별 거래량 상위 3개 (HVN)."""
    if not closes or max(closes) <= min(closes):
        return []
    lo, hi = min(closes), max(closes)
    width = (hi - lo) / bins
    acc = [0.0] * bins
    for c, v in zip(closes, volumes):
        i = min(int((c - lo) / width), bins - 1)
        acc[i] += v
    total = sum(acc) or 1.0
    ranked = sorted(range(bins), key=lambda i: -acc[i])[:3]
    return [
        {
            "priceFrom": round(lo + i * width, 1),
            "priceTo": round(lo + (i + 1) * width, 1),
            "volumePct": round(acc[i] / total * 100, 1),
        }
        for i in sorted(ranked)
    ]


def _fibonacci(highs: list[float], lows: list[float], closes: list[float]) -> dict:
    """주 스윙(최근 60봉 최저→최고) 기준 되돌림/확장 레벨 + 현재 위치."""
    window = min(60, len(closes))
    h_seg, l_seg = highs[-window:], lows[-window:]
    hi, lo = max(h_seg), min(l_seg)
    if hi <= lo:
        return {}
    rng = hi - lo
    cur = closes[-1]
    levels = {
        "0.0(고점)": hi,
        "0.382": hi - rng * 0.382,
        "0.5": hi - rng * 0.5,
        "0.618": hi - rng * 0.618,
        "0.786": hi - rng * 0.786,
        "1.0(저점)": lo,
        "ext1.272": lo + rng * 1.272,
        "ext1.618": lo + rng * 1.618,
    }
    pos = round((cur - lo) / rng, 3)
    return {
        "swingHigh": hi, "swingLow": lo,
        "levels": {k: round(v, 1) for k, v in levels.items()},
        "currentPosition": pos,  # 1.0=스윙 고점, 0.0=스윙 저점
    }


def _cdv(opens: list[float], closes: list[float], volumes: list[float]) -> dict:
    """누적 델타 볼륨 근사: 양봉 +vol, 음봉 -vol 누적의 방향."""
    cum, series = 0.0, []
    for o, c, v in zip(opens, closes, volumes):
        cum += v if c >= o else -v
        series.append(cum)
    if len(series) < 21:
        return {"direction": "데이터 부족"}
    delta20 = series[-1] - series[-21]
    return {
        "direction": "매수 우위" if delta20 > 0 else "매도 우위",
        "delta20Bars": round(delta20),
    }


def _fvg_zones(bars: list[dict], max_keep: int = 3) -> dict:
    """ICT Fair Value Gap (스마트머니 매물대) — 3봉 패턴, 미충전 갭만 반환.

    Pine 로직 이식 (ICT FVG & Swing Detector):
      bullish FVG: high[i-2] < low[i]  → 지지 구간 [high[i-2], low[i]]  (기관 매수 흔적)
      bearish FVG: low[i-2] > high[i] → 저항 구간 [high[i], low[i-2]]  (기관 매도 흔적)
    충전(mitigation) 판정: 이후 봉이 갭 반대편 끝까지 관통하면 무효 — 미충전만 유효.
    ceTouched: 갭 중앙선(CE, Consequent Encroachment) 터치 여부 — 절반 충전.
    """
    bulls: list[dict] = []
    bears: list[dict] = []
    n = len(bars)
    for i in range(2, n):
        when = bars[i].get("date") or bars[i].get("time") or ""
        # bullish FVG
        h2, l0 = bars[i - 2]["high"], bars[i]["low"]
        if h2 < l0:
            bottom, top = h2, l0
            mid = (top + bottom) / 2
            if not any(bars[j]["low"] <= bottom for j in range(i + 1, n)):
                bulls.append({
                    "type": "bullish", "top": top, "bottom": bottom,
                    "mid": round(mid, 1), "at": when,
                    "ceTouched": any(bars[j]["low"] <= mid for j in range(i + 1, n)),
                })
        # bearish FVG
        l2, h0 = bars[i - 2]["low"], bars[i]["high"]
        if l2 > h0:
            bottom, top = h0, l2
            mid = (top + bottom) / 2
            if not any(bars[j]["high"] >= top for j in range(i + 1, n)):
                bears.append({
                    "type": "bearish", "top": top, "bottom": bottom,
                    "mid": round(mid, 1), "at": when,
                    "ceTouched": any(bars[j]["high"] >= mid for j in range(i + 1, n)),
                })
    return {"bullish": bulls[-max_keep:], "bearish": bears[-max_keep:]}


def analyze_timeframe(bars: list[dict], label: str) -> dict:
    """단일 타임프레임 종합 분석."""
    if len(bars) < 25:
        return {"label": label, "error": f"봉 수 부족 ({len(bars)}개) — 판단 보류"}
    opens = [b["open"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    closes = [b["close"] for b in bars]
    vols = [b["volume"] for b in bars]

    sw = _swings(highs, lows)
    st = _structure(sw, closes)
    ema20, ema60 = _ema(closes, 20), _ema(closes, min(60, len(closes) - 1))
    ema_state = None
    if ema20 and ema60:
        ema_state = "정배열(20>60)" if ema20 > ema60 else "역배열(20<60)"

    vol_recent = sum(vols[-5:]) / 5 if len(vols) >= 5 else 0
    vol_base = sum(vols[-20:]) / 20 if len(vols) >= 20 else 1
    return {
        "label": label,
        "bars": len(bars),
        "close": closes[-1],
        "trend": st["trend"],
        "emaState": ema_state,
        "structureEvent": st["event"],
        "liquidity": _liquidity(sw, closes[-1]),
        "volumeProfile": _volume_profile(closes, vols),
        "fvg": _fvg_zones(bars),
        "fibonacci": _fibonacci(highs, lows, closes),
        "volumeRatio5v20": round(vol_recent / vol_base, 2) if vol_base else None,
        "cdv": _cdv(opens, closes, vols),
        "rsi14": _rsi(closes),
    }


def _resample_minutes_daily(minutes: list[dict], step_min: int) -> list[dict]:
    """여러 날의 1분봉 → N분봉 리샘플 (날짜 경계에서 버킷 분리)."""
    out: list[dict] = []
    bucket: list[dict] = []
    cur_key = None
    for b in minutes:
        t = b["time"]
        key = (b.get("date", ""), (int(t[:2]) * 60 + int(t[2:4])) // step_min)
        if cur_key is not None and key != cur_key and bucket:
            out.append(_merge(bucket))
            bucket = []
        cur_key = key
        bucket.append(b)
    if bucket:
        out.append(_merge(bucket))
    return out


def _merge(bucket: list[dict]) -> dict:
    return {
        "time": bucket[0]["time"],
        "open": bucket[0]["open"],
        "high": max(b["high"] for b in bucket),
        "low": min(b["low"] for b in bucket),
        "close": bucket[-1]["close"],
        "volume": sum(b["volume"] for b in bucket),
    }


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def analyze_mtf(code: str) -> dict:
    """월봉→주봉→일봉→60분→15분 멀티 타임프레임 분석 (KIS 차트 데이터)."""
    import time as _time
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import db
    import models
    import kis_client
    from settings import settings
    from sqlalchemy import select

    s = db.get_session_factory()()
    try:
        prof = s.execute(
            select(models.KisProfile).where(models.KisProfile.user_id == 1)
        ).scalar_one_or_none()
        stock = s.get(models.Stock, code)
    finally:
        s.close()
    if prof is None:
        raise RuntimeError("KIS 프로필 없음")

    kw = dict(
        app_key=str(prof.app_key), app_secret=str(prof.app_secret),
        is_paper=bool(prof.is_paper),
        live_base_url=settings.kis_live_base_url,
        paper_base_url=settings.kis_paper_base_url,
    )

    tf: dict[str, dict] = {}
    daily_bars: list[dict] = []
    for period, label in (("M", "월봉"), ("W", "주봉"), ("D", "일봉")):
        try:
            bars = kis_client.inquire_daily_chart(code=code, period=period, **kw)
            if period == "D":
                daily_bars = bars
            tf[label] = analyze_timeframe(bars, label)
        except Exception as exc:
            tf[label] = {"label": label, "error": f"조회 실패: {exc}"}
        _time.sleep(0.12)

    # 60분/15분: 최근 5거래일 분봉 (일별분봉 TR — 하루 4콜)
    try:
        recent_dates = [b["date"] for b in daily_bars[-5:]] if daily_bars else []
        minutes: list[dict] = []
        for d in recent_dates:
            minutes.extend(
                kis_client.inquire_daily_minute_chart(code=code, date_yyyymmdd=d, **kw)
            )
            _time.sleep(0.12)
        tf["60분(5일)"] = analyze_timeframe(_resample_minutes_daily(minutes, 60), "60분(5일)")
        tf["15분(5일)"] = analyze_timeframe(_resample_minutes_daily(minutes, 15), "15분(5일)")
    except Exception as exc:
        tf["60분(5일)"] = {"label": "60분(5일)", "error": f"분봉 조회 실패: {exc}"}
        tf["15분(5일)"] = {"label": "15분(5일)", "error": "분봉 조회 실패"}

    # 정렬도: 상승 구조 타임프레임 수
    order = ["월봉", "주봉", "일봉", "60분(5일)", "15분(5일)"]
    up = sum(1 for k in order if "상승" in str(tf.get(k, {}).get("trend", "")))
    down = sum(1 for k in order if "하락" in str(tf.get(k, {}).get("trend", "")))
    return {
        "code": code,
        "name": getattr(stock, "name", code) if stock else code,
        "asOf": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M"),
        "timeframes": [tf[k] for k in order if k in tf],
        "alignment": {
            "uptrendCount": up, "downtrendCount": down, "total": len(order),
            "summary": f"5개 타임프레임 중 상승 {up} / 하락 {down}",
        },
        "notes": [
            "4시간봉은 한국 정규장(6.5시간) 구조상 제외 — 60분봉으로 대체",
            "60분/15분은 최근 5거래일 분봉 기준 (KIS 일별분봉)",
        ],
    }
