"""목표가·손절가·확률 엔진 — 시장 나침반 9~11단계.

[9단계] 목표가 — 5가지 독립 계산 후 평균:
  1. 피보나치 확장   : 주 스윙(저→고) 1.272 확장
  2. 거래량 프로파일 : 현재가 위 최근접 매물대(HVN) 상단 (저항→목표)
  3. 과거 사이클     : 과거 상승 사이클 평균 상승률을 최근 스윙 저점에 적용
  4. 기관 목표주가   : 네이버 컨센서스 priceTargetMean (증권사 평균)
  5. 섹터 밸류에이션 : 추정EPS × 업종 PER (네이버 industryCompareInfo)

[10단계] 손절가 — 3가지:
  1. 기술적 손절 : 일봉 직전 스윙 저점 -1%
  2. 수급 손절   : 현재가 아래 최대 매물대 하단
  3. 구조 손절   : 주 스윙 저점 (이탈 시 상승 구조 무효)

[11단계] 확률 — 최근 ~500거래일 표본의 "빈도 기반 추정" (만들어낸 수치 아님):
  - 유사 국면 판정: 6차원(추세·모멘텀·변동성·거래량·가격위치·단기수익률)
    + 7차원(P/E 자기 이력 252일 백분위 — KRX 일별 PER, 가용 시) 특징을
    z-정규화한 뒤 현재와 유클리드 거리가 가장 가까운 과거 시점 k-NN 표본
    (PER 무데이터·ETF·적자 시 6차원, 표본 부족 시 단일 차원 추세 상태로 폴백)
  - 상승 지속 확률  : 유사 국면 시점들의 20일 후 양(+)수익 비율
  - 목표가 도달 확률 : 같은 국면에서 손절폭 이탈 전에 목표폭 도달한 비율 (선도달 검사)
  - 손절 이탈 확률   : 같은 국면에서 목표 도달 전 손절폭 이탈 비율
  - 표본 수·매칭 일자·차원별 현재값 vs 유사표본 평균을 함께 표기 —
    표본 30건 미만이면 "통계적 신뢰 낮음" 명시
  - 닷컴 보조 표본(dotcomAnalogs): 1995~2002 미국 검증 데이터셋(regime_analogs)
    에서 동일 6차원 최근접 시점들의 실제 20일 후 수익 빈도 — 한국 ~500봉에
    없는 과열·붕괴 국면 대조용 (데이터 부재 시 error 블록, 본 확률엔 무영향)

데이터 정확성 원칙: 계산 불가 항목은 None + 사유. 추정치는 표본 수와 함께 제공.
"""

from __future__ import annotations

import time as _time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

KST = ZoneInfo("Asia/Seoul")  # 시장 바 날짜·표시 기준 — KST

import httpx

from mtf_analysis import _swings, _ema, _rsi, _volume_profile, _volume_profile_full  # noqa: F401

NAVER_H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _fetch_daily_long(code: str, kw: dict, windows: int = 5) -> list[dict]:
    """일봉 장기 이력 (~500봉) — 100봉 윈도우를 뒤로 이어붙임."""
    import kis_client
    from datetime import datetime as _dt, timedelta as _td

    all_bars: dict[str, dict] = {}
    end_date: Optional[str] = None
    for _ in range(windows):
        bars = kis_client.inquire_daily_chart(code=code, period="D", end_date=end_date, **kw)
        if not bars:
            break
        for b in bars:
            all_bars[b["date"]] = b
        earliest = min(b["date"] for b in bars)
        prev = _dt.strptime(earliest, "%Y%m%d").replace(tzinfo=KST).date() - _td(days=1)
        end_date = prev.strftime("%Y%m%d")
        _time.sleep(0.12)
        if len(bars) < 50:  # 상장 초기 도달
            break
    return [all_bars[k] for k in sorted(all_bars)]


def _naver_fundamentals(code: str) -> dict:
    """네이버 통합 API: 컨센서스 목표가, PER/EPS/추정EPS, 업종 PER."""
    out: dict = {}
    try:
        r = httpx.get(f"https://m.stock.naver.com/api/stock/{code}/integration",
                      headers=NAVER_H, timeout=8)
        d = r.json()
        cons = d.get("consensusInfo") or {}
        if cons.get("priceTargetMean"):
            out["consensusTarget"] = float(str(cons["priceTargetMean"]).replace(",", ""))
            out["consensusDate"] = cons.get("createDate")

        def _num(s):
            try:
                return float(str(s).replace(",", "").replace("배", "").replace("원", ""))
            except Exception:
                return None

        for t in d.get("totalInfos", []):
            c = str(t.get("code") or "")
            if c == "per":
                out["per"] = _num(t.get("value"))
            elif c == "eps":
                out["eps"] = _num(t.get("value"))
            elif c == "cnsEps":
                out["cnsEps"] = _num(t.get("value"))

        # 업종 PER: industryCompareInfo는 피어 목록만 제공 → 상위 3개 피어의 PER 평균
        peers = d.get("industryCompareInfo") or []
        peer_pers: list[float] = []
        for p in peers[:3]:
            pc = str(p.get("itemCode") or "")
            if not pc:
                continue
            try:
                pr = httpx.get(f"https://m.stock.naver.com/api/stock/{pc}/integration",
                               headers=NAVER_H, timeout=8)
                for t in pr.json().get("totalInfos", []):
                    if str(t.get("code")) == "per":
                        n = _num(t.get("value"))
                        if n and 0 < n < 200:
                            peer_pers.append(n)
                        break
            except Exception:
                continue
            _time.sleep(0.05)
        if peer_pers:
            out["industryPer"] = round(sum(peer_pers) / len(peer_pers), 2)
            out["industryPerPeers"] = len(peer_pers)
    except Exception:
        pass
    return out


def _past_cycles(bars: list[dict]) -> dict:
    """과거 상승 사이클: 스윙 저점→고점 상승률들의 평균."""
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    sw = _swings(highs, lows, n=5)  # 굵은 스윙만
    gains = []
    last_low = None
    for s in sw:
        if s["type"] == "L":
            last_low = s["price"]
        elif s["type"] == "H" and last_low and last_low > 0:
            g = (s["price"] - last_low) / last_low
            if g > 0.05:  # 5% 이상 움직임만 사이클로 인정
                gains.append(g)
            last_low = None
    recent_lows = [s["price"] for s in sw if s["type"] == "L"]
    return {
        "cycles": len(gains),
        "avgGainPct": round(sum(gains) / len(gains) * 100, 1) if gains else None,
        "lastSwingLow": recent_lows[-1] if recent_lows else None,
    }


def _first_passage_prob(bars: list[dict], up_pct: float, dn_pct: float,
                        horizon: int = 60) -> dict:
    """현재와 같은 추세 상태(EMA20>60 여부)였던 과거 시점들에서
    목표폭(up) 선도달 vs 손절폭(dn) 선이탈 빈도."""
    closes = [b["close"] for b in bars]
    if len(closes) < 140 or up_pct <= 0 or dn_pct <= 0:
        return {"error": "표본 부족 또는 목표/손절폭 비정상"}

    # 현재 상태
    cur_up = (_ema(closes, 20) or 0) > (_ema(closes, 60) or 0)

    hit_t = hit_s = undecided = cont_up = total = 0
    for i in range(120, len(closes) - 1):
        seg = closes[: i + 1]
        st_up = (_ema(seg[-120:], 20) or 0) > (_ema(seg[-120:], 60) or 0)
        if st_up != cur_up:
            continue
        total += 1
        # 20일 후 수익 (상승 지속)
        j20 = min(i + 20, len(closes) - 1)
        if closes[j20] > closes[i]:
            cont_up += 1
        # 선도달 검사
        target = closes[i] * (1 + up_pct)
        stop = closes[i] * (1 - dn_pct)
        outcome = 0
        for j in range(i + 1, min(i + horizon, len(bars))):
            if bars[j]["high"] >= target:
                outcome = 1
                break
            if bars[j]["low"] <= stop:
                outcome = -1
                break
        if outcome == 1:
            hit_t += 1
        elif outcome == -1:
            hit_s += 1
        else:
            undecided += 1

    if total == 0:
        return {"error": "동일 상태 표본 없음"}
    return {
        "sample": total,
        "trendState": "상승(EMA20>60)" if cur_up else "하락(EMA20<60)",
        "continueUpPct": round(cont_up / total * 100, 1),
        "reachTargetPct": round(hit_t / total * 100, 1),
        "hitStopPct": round(hit_s / total * 100, 1),
        "undecidedPct": round(undecided / total * 100, 1),
        "lowConfidence": total < 30,
    }


# ── 다차원 유사 국면 확률 엔진 ──────────────────────────────────────────────
# 기존 _first_passage_prob 의 "유사 국면" 판정은 EMA20>60 불리언 1차원뿐이라
# 상승장 표본 전체가 한 덩어리로 묶였다. 아래는 6개 차원의 특징 벡터를
# z-정규화한 뒤 현재와 유클리드 거리가 가장 가까운 과거 시점(k-NN)만 표본으로
# 쓰는 강화판 — 확률은 동일하게 실제 결과의 빈도이며 만들어낸 수치가 아니다.

_REGIME_DIMS = [
    ("추세", "EMA20/60 괴리율 %"),
    ("모멘텀", "RSI(14)"),
    ("변동성", "20일 수익률 표준편차 %"),
    ("거래량", "5일/20일 평균 거래량비"),
    ("가격위치", "60일 범위 내 백분위 %"),
    ("단기수익률", "20일 수익률 %"),
]
_VALUATION_DIM = ("밸류에이션", "P/E 자기 이력 252일 백분위 % (KRX 일별 PER)")


def _fetch_per_series(code: str, start: str, end: str) -> dict[str, float]:
    """KRX 일별 PER (pykrx — 직전 사업연도 EPS 기준). 실패·무데이터 시 빈 dict.

    ETF·적자 종목은 PER 0/결측 → 자동으로 7차원 미사용 (6차원 폴백).
    """
    try:
        from pykrx import stock as _krx
        df = _krx.get_market_fundamental(start, end, code)
        if df is None or df.empty or "PER" not in df.columns:
            return {}
        return {d.strftime("%Y%m%d"): float(v)
                for d, v in df["PER"].items()
                if v is not None and float(v) > 0}
    except Exception:
        return {}


def _per_pctile_list(bars: list[dict], per_map: dict[str, float]) -> list[Optional[float]]:
    """봉별 P/E 백분위: 시점 기준 과거 252봉 내 순위 (미래 참조 없음, 최소 120관측)."""
    per = [per_map.get(b["date"]) for b in bars]
    out: list[Optional[float]] = []
    for i in range(len(bars)):
        v = per[i]
        if v is None or v <= 0:
            out.append(None)
            continue
        win = [x for x in per[max(0, i - 251): i + 1] if x and x > 0]
        if len(win) < 120:
            out.append(None)
            continue
        rank = sum(1 for x in win if x <= v)
        out.append(round(rank / len(win) * 100, 1))
    return out


def _regime_features(closes: list[float], vols: list[float], i: int) -> Optional[list[float]]:
    """i 시점의 6차원 국면 특징 — i 이후 데이터는 사용하지 않음 (미래 참조 금지).

    모든 시점이 동일한 윈도우 길이로 계산되어 시점 간 비교가 공정하다.
    """
    if i < 120 or closes[i] <= 0:
        return None
    c = closes[i]
    seg = closes[i - 119: i + 1]                      # 120봉
    e20, e60 = _ema(seg, 20), _ema(seg, 60)
    rsi = _rsi(closes[i - 59: i + 1], 14)             # 60봉 윈도우로 통일
    if not e20 or not e60 or e60 <= 0 or rsi is None:
        return None
    rets = [
        closes[j] / closes[j - 1] - 1
        for j in range(i - 19, i + 1)
        if closes[j - 1] > 0
    ]
    if len(rets) < 15:
        return None
    m = sum(rets) / len(rets)
    vol_sd = (sum((r - m) ** 2 for r in rets) / len(rets)) ** 0.5 * 100
    v20 = sum(vols[i - 19: i + 1]) / 20
    vol_ratio = (sum(vols[i - 4: i + 1]) / 5) / v20 if v20 > 0 else 1.0
    w60 = closes[i - 59: i + 1]
    hi, lo = max(w60), min(w60)
    pos = (c - lo) / (hi - lo) * 100 if hi > lo else 50.0
    ret20 = (c / closes[i - 20] - 1) * 100 if closes[i - 20] > 0 else 0.0
    return [(e20 / e60 - 1) * 100, rsi, vol_sd, vol_ratio, pos, ret20]


def _similar_regime_prob(bars: list[dict], up_pct: float, dn_pct: float,
                         horizon: int = 60,
                         per_map: Optional[dict[str, float]] = None) -> dict:
    """현재와 가장 유사한 과거 국면(k-NN)들의 실제 결과 빈도.

    출력 키는 _first_passage_prob 와 호환(sample/continueUpPct/reachTargetPct/
    hitStopPct/undecidedPct/lowConfidence/trendState) + 다차원 근거(dimensions,
    matchedDates, totalCandidates, method)를 추가.
    """
    closes = [b["close"] for b in bars]
    vols = [b["volume"] for b in bars]
    n = len(closes)
    if n < 200 or up_pct <= 0 or dn_pct <= 0:
        return {"error": "표본 부족(200봉 미만) 또는 목표/손절폭 비정상"}

    cur_f = _regime_features(closes, vols, n - 1)
    if cur_f is None:
        return {"error": "현재 국면 특징 계산 불가"}

    # 후보: 20일 후 결과가 항상 실재하는 구간만 (말단 잘림 표본 배제)
    cands = []
    for i in range(120, n - 21):
        f = _regime_features(closes, vols, i)
        if f is not None:
            cands.append((i, f))
    if len(cands) < 60:
        return {"error": f"유사 국면 후보 부족 ({len(cands)}건)"}

    # 7번째 차원: P/E 자기 이력 백분위 — 현재값이 있고 후보 70% 이상이 보유할 때만.
    # (ETF·적자·데이터 부재 시 6차원 폴백 — 차원 수는 method/dimensions 에 명시)
    pctiles = _per_pctile_list(bars, per_map) if per_map else None
    cur_valp = pctiles[n - 1] if pctiles else None
    use_val = False
    val_note = "미사용 (PER 데이터 없음)" if not per_map else "미사용 (백분위 산출 불가 — 관측 부족/적자)"
    if cur_valp is not None:
        cov = sum(1 for i, _ in cands if pctiles[i] is not None) / len(cands)
        if cov >= 0.7:
            use_val = True
            cands = [(i, f + [pctiles[i]]) for i, f in cands if pctiles[i] is not None]
            cur_f = cur_f + [cur_valp]
            val_note = f"사용 (현재 백분위 {cur_valp}, 후보 커버리지 {cov*100:.0f}%)"
        else:
            val_note = f"미사용 (후보 커버리지 {cov*100:.0f}% < 70%)"

    dims = len(cur_f)
    means, stds = [], []
    for d in range(dims):
        vals = [f[d] for _, f in cands]
        mu = sum(vals) / len(vals)
        sd = (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5
        means.append(mu)
        stds.append(sd if sd > 1e-9 else 1.0)

    def _z(f: list[float]) -> list[float]:
        return [(f[d] - means[d]) / stds[d] for d in range(dims)]

    zc = _z(cur_f)
    scored = sorted(
        ((sum((a - b) ** 2 for a, b in zip(_z(f), zc)) ** 0.5, i, f) for i, f in cands),
        key=lambda t: t[0],
    )

    # 자기상관 완화: 채택 시점 간 최소 5봉 간격 (연속봉은 사실상 같은 국면)
    k_target = min(60, max(30, round(len(cands) * 0.15)))
    picked: list[tuple[float, int, list[float]]] = []
    for dist, i, f in scored:
        if all(abs(i - pi) >= 5 for _, pi, _ in picked):
            picked.append((dist, i, f))
            if len(picked) >= k_target:
                break
    if not picked:
        return {"error": "유사 국면 선택 실패"}

    hit_t = hit_s = undecided = cont_up = 0
    for _, i, _f in picked:
        if closes[i + 20] > closes[i]:
            cont_up += 1
        target = closes[i] * (1 + up_pct)
        stop = closes[i] * (1 - dn_pct)
        outcome = 0
        for j in range(i + 1, min(i + horizon, n)):
            if bars[j]["high"] >= target:
                outcome = 1
                break
            if bars[j]["low"] <= stop:
                outcome = -1
                break
        if outcome == 1:
            hit_t += 1
        elif outcome == -1:
            hit_s += 1
        else:
            undecided += 1

    total = len(picked)
    e20 = _ema(closes[-120:], 20) or 0
    e60 = _ema(closes[-120:], 60) or 0

    # 닷컴(1995~2002 미국) 보조 표본 — 한국 ~500봉에 없는 과열·붕괴 국면 대조.
    # zc 앞 6개가 기본 차원의 z-값, 밸류에이션은 백분위 원값으로 별도 전달
    # (양쪽 모두 자기 분포 내 백분위라 시장중립). 실패해도 본 확률엔 무영향.
    try:
        import regime_analogs
        dotcom = regime_analogs.find_analogs(zc[:6], val_pctile=cur_valp)
    except Exception as exc:  # noqa: BLE001
        dotcom = {"error": f"닷컴 표본 조회 실패: {type(exc).__name__}"}

    def _date(i: int) -> str:
        d = str(bars[i]["date"])
        return f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else d

    return {
        "sample": total,
        "totalCandidates": len(cands),
        "method": f"{dims}차원 유사 국면 k-NN (z-정규화 유클리드 거리, 5봉 간격 디커플링)",
        "valuationDim": {"used": use_val, "currentPctile": cur_valp, "note": val_note},
        "trendState": "상승(EMA20>60)" if e20 > e60 else "하락(EMA20<60)",
        "continueUpPct": round(cont_up / total * 100, 1),
        "reachTargetPct": round(hit_t / total * 100, 1),
        "hitStopPct": round(hit_s / total * 100, 1),
        "undecidedPct": round(undecided / total * 100, 1),
        "lowConfidence": total < 30,
        "avgDistance": round(sum(d for d, _, _ in picked) / total, 3),
        "dimensions": [
            {
                "name": name,
                "desc": desc,
                "current": round(cur_f[d], 2),
                "analogMean": round(sum(f[d] for _, _, f in picked) / total, 2),
            }
            for d, (name, desc) in enumerate(
                list(_REGIME_DIMS) + ([_VALUATION_DIM] if use_val else []))
        ],
        "matchedDates": [_date(i) for _, i, _ in picked[:5]],
        "dotcomAnalogs": dotcom,
    }


# KR 섹터(sector_classification.json) → US 선행 섹터(us_lead) 매핑.
# us_lead 가 다루는 섹터만 키 — 나머지(모빌리티·방산 등)는 선행 데이터 없음 → None(no-op).
_KR_TO_US_LEAD_SECTOR = {"반도체": "반도체", "AI 생태계": "AI"}


def _us_lead_score_for_code(code: str) -> tuple[Optional[str], Optional[float]]:
    """종목코드 → (US lead 섹터명, lead_score). 매핑·데이터 없으면 (섹터, None)."""
    import json
    from pathlib import Path

    kr_sector = None
    try:
        p = Path(__file__).resolve().parent / "sector_classification.json"
        m = json.loads(p.read_text(encoding="utf-8"))
        kr_sector = m.get(code)
    except Exception:
        return None, None
    us_sector = _KR_TO_US_LEAD_SECTOR.get(kr_sector or "")
    if not us_sector:
        return kr_sector, None
    try:
        import us_lead
        return us_sector, us_lead.get_sector_lead_score(us_sector)
    except Exception:
        return us_sector, None


def analyze_targets(code: str) -> dict:
    """9~11단계: 목표가 5종 + 손절가 3종 + 빈도 기반 확률."""
    import db
    import models
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

    import kis_client

    bars = _fetch_daily_long(code, kw)
    if len(bars) < 120:
        raise RuntimeError(f"일봉 이력 부족 ({len(bars)}봉)")

    # ── 공매도 수급 (KIS 일별추이 — 대차잔고는 KIS 미제공이라 공매도 비중이 대용 지표) ──
    # 점수 설계: 50 기준 ± [추세(20일평균-최근5일평균)×12] + [(2% - 최근비중)×8]
    #   → 공매도 '감소 중'이면 가점(숏커버/재평가 신호), 비중 자체가 높으면 감점.
    short_data: dict = {}
    try:
        srows = kis_client.inquire_short_sale(code=code, days=60, **kw)
        if len(srows) >= 10:
            ratios = [r["shortRatio"] for r in srows]
            recent5 = sum(ratios[-5:]) / 5
            base_seg = ratios[-25:-5] or ratios[:-5]
            base20 = sum(base_seg) / max(len(base_seg), 1)
            trend = round(base20 - recent5, 2)  # 양수 = 공매도 감소 중 (우호)
            score = max(0.0, min(100.0, 50 + trend * 12 + (2.0 - recent5) * 8))
            short_data = {
                "recentRatio5d": round(recent5, 2),
                "baseRatio20d": round(base20, 2),
                "trend": trend,
                "score": round(score, 1),
                "days": len(srows),
                "interpretation": (
                    "공매도 감소 중 — 숏커버/재평가 신호 가능" if trend > 0.2
                    else "공매도 증가 중 — 하락 베팅 확대" if trend < -0.2
                    else "공매도 중립"
                ),
            }
        else:
            short_data = {"error": f"공매도 데이터 부족 ({len(srows)}일)"}
    except Exception as exc:  # noqa: BLE001
        short_data = {"error": f"공매도 조회 실패: {type(exc).__name__}"}
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    vols = [b["volume"] for b in bars]
    cur = closes[-1]

    fund = _naver_fundamentals(code)

    # ── [9단계] 목표가 5종 ──────────────────────────────────────────────
    targets: dict[str, Optional[dict]] = {}

    # 1) 피보나치 확장 (최근 120봉 주 스윙)
    w = 120
    hi, lo = max(highs[-w:]), min(lows[-w:])
    fib_t = lo + (hi - lo) * 1.272 if hi > lo else None
    targets["피보나치 확장 1.272"] = (
        {"price": round(fib_t)} if fib_t and fib_t > cur else
        {"price": None, "note": "확장 레벨이 현재가 아래 — 이미 도달"}
    )

    # 2) 거래량 프로파일 (250봉) — H/L/V 기반 full VP (POC/VAH/VAL + HVN)
    vp_full = _volume_profile_full(bars[-250:], bins=80)
    vp = vp_full.get("zones", []) if vp_full else []
    vp_20 = _volume_profile_full(bars[-20:], bins=40) if len(bars) >= 20 else {}
    above_zones = [z for z in vp if z["priceFrom"] > cur]
    targets["거래량 프로파일 저항"] = (
        {"price": round(min(above_zones, key=lambda z: z["priceFrom"])["priceTo"])}
        if above_zones else {"price": None, "note": "현재가 위 매물대 없음 (신고가권)"}
    )

    # 3) 과거 사이클
    cyc = _past_cycles(bars)
    if cyc["avgGainPct"] and cyc["lastSwingLow"]:
        targets["과거 사이클 평균"] = {
            "price": round(cyc["lastSwingLow"] * (1 + cyc["avgGainPct"] / 100)),
            "note": f"과거 {cyc['cycles']}개 사이클 평균 +{cyc['avgGainPct']}%",
        }
    else:
        targets["과거 사이클 평균"] = {"price": None, "note": "사이클 표본 부족"}

    # 4) 기관 목표주가 (네이버 컨센서스)
    targets["기관 컨센서스"] = (
        {"price": round(fund["consensusTarget"]), "note": f"기준일 {fund.get('consensusDate')}"}
        if fund.get("consensusTarget") else {"price": None, "note": "컨센서스 없음"}
    )

    # 5) 섹터 밸류에이션 (추정EPS × 업종 PER)
    if fund.get("cnsEps") and fund.get("industryPer"):
        targets["섹터 밸류에이션"] = {
            "price": round(fund["cnsEps"] * fund["industryPer"]),
            "note": f"추정EPS {fund['cnsEps']:,.0f} × 업종PER {fund['industryPer']}",
        }
    else:
        targets["섹터 밸류에이션"] = {"price": None, "note": "업종 PER 또는 추정 EPS 없음"}

    # 평균 산출 시 이상치 가드: 현재가 대비 -20% ~ +100% 범위 밖이면 제외 (표기는 유지).
    # 예: 업종 PER이 일시 왜곡(적자 전환 피어 등)되면 밸류에이션 목표가가 수배로 튐.
    valid = []
    for k, t in targets.items():
        p = t.get("price") if t else None
        if not p:
            continue
        if cur * 0.8 <= p <= cur * 2.0:
            valid.append(p)
        else:
            t["excluded"] = True
            t["note"] = (t.get("note", "") + " | 이상치 — 평균에서 제외").strip(" |")
    avg_target = round(sum(valid) / len(valid)) if valid else None

    # ── [10단계] 손절가 3종 ─────────────────────────────────────────────
    # 전부 "현재가 -20% 이내"의 실용 구간으로 제한 — 수백 % 아래의 과거 레벨은 손절로 무의미.
    sw_d = _swings(highs[-120:], lows[-120:], n=2)
    below_ls = [p["price"] for p in sw_d if p["type"] == "L" and cur * 0.8 <= p["price"] < cur]
    tech_stop = round(max(below_ls) * 0.99) if below_ls else None

    below_zones = [z for z in vp if cur * 0.8 <= z["priceTo"] < cur]
    supply_stop = (
        round(max(below_zones, key=lambda z: z["volumePct"])["priceFrom"])
        if below_zones else None
    )

    # 구조 손절: 현재 상승 다리의 기점 (굵은 스윙 n=5 의 마지막 저점)
    sw_major = _swings(highs[-120:], lows[-120:], n=5)
    major_ls = [p["price"] for p in sw_major if p["type"] == "L" and p["price"] < cur]
    struct_stop = round(major_ls[-1]) if major_ls else None

    stops = {
        "기술적 손절": {"price": tech_stop, "basis": "일봉 직전 스윙 저점 -1% (-20% 이내)"},
        "수급 손절": {"price": supply_stop, "basis": "현재가 아래 최대 매물대 하단 (-20% 이내)"},
        "구조 손절": {"price": struct_stop, "basis": "현 상승 다리 기점 스윙 저점 (이탈 시 구조 무효)"},
    }

    # ── 트레이딩 플랜 레벨 (분할 매수·단계별 목표·매집 추정 구간) ────────
    # 분할 매수: 현 상승 다리(주 스윙 저점→현재가)의 피보나치 되돌림 0.236/0.382/0.5
    leg_low = struct_stop if struct_stop and struct_stop < cur else lo
    buy_levels = []
    if leg_low and cur > leg_low:
        rng_leg = cur - leg_low
        for i, ratio in enumerate((0.236, 0.382, 0.5), start=1):
            lvl = cur - rng_leg * ratio
            if lvl > (tech_stop or 0):  # 손절선 아래 매수 레벨은 무의미
                buy_levels.append({
                    "stage": f"{i}차",
                    "price": round(lvl),
                    "basis": f"상승 다리 {ratio} 되돌림",
                })

    # 단계별 목표: 유효 목표가(평균 가드 통과 + 현재가 위)를 낮은 순으로 1·2·3차
    staged = sorted(
        [
            {"price": t["price"], "basis": k}
            for k, t in targets.items()
            if t and t.get("price") and not t.get("excluded") and t["price"] > cur
        ],
        key=lambda x: x["price"],
    )[:3]
    staged_targets = [
        {"stage": f"{i}차", **s} for i, s in enumerate(staged, start=1)
    ]

    # 매집 추정 구간: 현재가 아래 거래량 집중 가격대 상위 2개 (추정임을 명시)
    accumulation = sorted(
        [z for z in vp if z["priceTo"] <= cur],
        key=lambda z: -z["volumePct"],
    )[:2]

    # ── [11단계] 확률 (빈도 기반) ────────────────────────────────────────
    # 1순위: 다차원 유사 국면 k-NN — 표본 부족 시 기존 단일 차원 방식으로 폴백.
    prob = {}
    stop_for_prob = tech_stop or supply_stop or struct_stop
    if avg_target and stop_for_prob and cur > 0:
        up_pct = avg_target / cur - 1
        dn_pct = 1 - stop_for_prob / cur
        # 7차원용 KRX 일별 PER (1회 조회, 실패 시 빈 dict → 6차원 폴백)
        per_map = _fetch_per_series(code, bars[0]["date"], bars[-1]["date"])
        prob = _similar_regime_prob(bars, up_pct, dn_pct, per_map=per_map)
        if "error" in prob:
            fallback_reason = prob["error"]
            prob = _first_passage_prob(bars, up_pct, dn_pct)
            if "error" not in prob:
                prob["method"] = (
                    f"단일 차원 폴백 — EMA20/60 추세 상태 동일 표본 (사유: {fallback_reason})"
                )
        if "error" not in prob:
            sample_desc = (
                f"{len(prob['dimensions'])}차원 유사 국면 최근접 {prob['sample']}건"
                if prob.get("dimensions")
                else "현재와 같은 추세 상태 표본"
            )
            prob["basis"] = (
                f"최근 {len(bars)}거래일 중 {sample_desc}의 빈도 "
                f"(목표 +{up_pct*100:.1f}% vs 손절 -{dn_pct*100:.1f}%, 60일 한도)"
            )
            # 닷컴 보조 표본 확률에 US 선행점수 조건화 (순수 후처리, 6D 매칭 불변).
            # 종목 섹터 → US lead 섹터 매핑 후 lead_score 주입. 실패·무데이터는 no-op.
            try:
                import regime_analogs
                dc = prob.get("dotcomAnalogs")
                if dc and "error" not in dc:
                    sector = _us_lead_score_for_code(code)
                    regime_analogs.condition_on_us_lead(dc, sector[1], sector[0])
            except Exception:
                pass
    else:
        prob = {"error": "목표가 또는 손절가 산출 불가로 확률 계산 생략"}

    return {
        "code": code,
        "name": getattr(stock, "name", code) if stock else code,
        "asOf": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "currentPrice": cur,
        "barsUsed": len(bars),
        # 핵심 차트용 시계열 — 퀀트 추세선 엔진(고/저가 피벗)용으로 highs/lows/volumes 추가
        "series": {
            "dates":   [b["date"]   for b in bars[-120:]],
            "closes":  [b["close"]  for b in bars[-120:]],
            "highs":   [b["high"]   for b in bars[-120:]],
            "lows":    [b["low"]    for b in bars[-120:]],
            "volumes": [b["volume"] for b in bars[-120:]],
            # 52주(252거래일) 최고 종가 — 신고가 판정용
            "high52w": max(b["close"] for b in bars[-252:]),
        },
        "targets": targets,
        "avgTarget": avg_target,
        "avgTargetUpside": round((avg_target / cur - 1) * 100, 1) if avg_target else None,
        "stops": stops,
        "probability": prob,
        "fundamentals": fund,
        "tradePlan": {
            "buyLevels": buy_levels,           # 분할 매수 1·2·3차 (피보나치 되돌림)
            "stagedTargets": staged_targets,   # 단계별 목표 1·2·3차 (유효 목표 낮은 순)
            "accumulationZones": accumulation, # 매집 추정 구간 (거래량 집중 가격대 — 추정)
        },
        "shortSelling": short_data,            # 공매도 비중·추세 (KIS) — 대차잔고는 미제공
        "volumeProfile": {
            # zones 필드는 메모리 절약을 위해 제외 (poc/vah/val/hvn으로 충분)
            "mid": {k: v for k, v in vp_full.items() if k != "zones"} if vp_full else {},
            "short": {k: v for k, v in vp_20.items() if k != "zones"} if vp_20 else {},
        },
        "notes": [
            "확률은 과거 빈도 기반 추정 — 미래 보장 아님",
            "목표가 5종은 독립 계산 — 편차가 크면 불확실성이 큰 것",
        ],
    }
