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
  - 상승 지속 확률  : 현재와 같은 추세 상태였던 과거 시점의 20일 후 양(+)수익 비율
  - 목표가 도달 확률 : 같은 상태에서 손절폭 이탈 전에 목표폭 도달한 비율 (선도달 검사)
  - 손절 이탈 확률   : 같은 상태에서 목표 도달 전 손절폭 이탈 비율
  - 표본 수를 함께 표기 — 표본 30건 미만이면 "통계적 신뢰 낮음" 명시

데이터 정확성 원칙: 계산 불가 항목은 None + 사유. 추정치는 표본 수와 함께 제공.
"""

from __future__ import annotations

import time as _time
from datetime import datetime
from typing import Optional

import httpx

from mtf_analysis import _swings, _ema, _volume_profile  # noqa: F401

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
        prev = _dt.strptime(earliest, "%Y%m%d").date() - _td(days=1)
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

    # 2) 거래량 프로파일 (250봉) — 현재가 위 최근접 HVN 상단
    vp = _volume_profile(closes[-250:], vols[-250:], bins=16)
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
    prob = {}
    stop_for_prob = tech_stop or supply_stop or struct_stop
    if avg_target and stop_for_prob and cur > 0:
        up_pct = avg_target / cur - 1
        dn_pct = 1 - stop_for_prob / cur
        prob = _first_passage_prob(bars, up_pct, dn_pct)
        prob["basis"] = (
            f"최근 {len(bars)}거래일 중 현재와 같은 추세 상태 표본의 빈도 "
            f"(목표 +{up_pct*100:.1f}% vs 손절 -{dn_pct*100:.1f}%, 60일 한도)"
        )
    else:
        prob = {"error": "목표가 또는 손절가 산출 불가로 확률 계산 생략"}

    return {
        "code": code,
        "name": getattr(stock, "name", code) if stock else code,
        "asOf": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "currentPrice": cur,
        "barsUsed": len(bars),
        # 핵심 차트용 시계열 (최근 120봉 종가) — 뉴스레터 리포트의 가격 vs 목표/손절 차트
        "series": {
            "dates": [b["date"] for b in bars[-120:]],
            "closes": [b["close"] for b in bars[-120:]],
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
        "notes": [
            "확률은 과거 빈도 기반 추정 — 미래 보장 아님",
            "목표가 5종은 독립 계산 — 편차가 크면 불확실성이 큰 것",
        ],
    }
