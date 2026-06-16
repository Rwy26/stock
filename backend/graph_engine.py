"""관심종목 네트워크 그래프 엔진 — Force Directed Graph 데이터 공급.

노드 = 종목 (시총·섹터·AI 시그널), 엣지 = 종목 간 관계 가중치.

가중치 W_ij = α·Corr_ij + β·Sector_ij + γ·Gravity_ij   (Vendor 항은 데이터 확보 전 — δ=0)
  - Corr_ij   : 일봉 수익률 상관계수 (ai_analysis_cache 의 120봉 시계열 활용 — 추가 호출 0)
  - Sector_ij : 같은 섹터 = 1
  - Gravity_ij: 시총 기반 중력 (log 정규화 곱)

외부 환경 변수(환율·유가·금리·나스닥)는 섹터별 민감도 행렬로 군집 강화 계수(boost)를
산출해 프론트 물리엔진의 같은 섹터 스프링 힘에 곱한다 — "시장 기후".

캐시 30분. 외부 API 호출 없음 (모든 데이터 DB/캐시 재사용 — 비용 0).
"""

from __future__ import annotations

import math
import threading
import time
from datetime import datetime
from typing import Optional

_lock = threading.Lock()
_cache: Optional[dict] = None
_cache_ts: float = 0.0
TTL = 1800

# 가중치 계수
ALPHA, BETA, GAMMA = 0.5, 0.3, 0.2
TOP_K_EDGES = 4  # 노드당 최강 엣지 수

# 섹터별 외부 변수 민감도 (환율↑ / 유가↑ / 금리↑ / 나스닥↑ 에 대한 군집 강화 방향)
SENSITIVITY: dict[str, dict[str, float]] = {
    "반도체":      {"krw": +0.5, "oil": 0.0, "rate": -0.6, "nasdaq": +1.0},
    "AI 생태계":   {"krw": 0.0, "oil": 0.0, "rate": -0.8, "nasdaq": +1.0},
    "로봇 AI":     {"krw": +0.3, "oil": 0.0, "rate": -0.6, "nasdaq": +0.6},
    "2차전지":     {"krw": +0.3, "oil": 0.0, "rate": -0.5, "nasdaq": +0.3},
    "바이오":      {"krw": 0.0, "oil": 0.0, "rate": -0.7, "nasdaq": +0.3},
    "조선":        {"krw": +1.0, "oil": +0.5, "rate": 0.0, "nasdaq": 0.0},
    "방산":        {"krw": +0.8, "oil": +0.2, "rate": +0.2, "nasdaq": 0.0},
    "화학":        {"krw": +0.2, "oil": +0.8, "rate": 0.0, "nasdaq": 0.0},
    "금융":        {"krw": -0.3, "oil": 0.0, "rate": +1.0, "nasdaq": 0.0},
    "전력 인프라": {"krw": +0.3, "oil": +0.3, "rate": 0.0, "nasdaq": +0.3},
}
THETA = 0.05  # 변수별 조정 계수 (5일 변화율 % 단위 입력 기준)


def _ema_last(vals: list[float], n: int) -> float:
    """마지막 EMA 값 (표본 부족 시 0)."""
    if len(vals) < n:
        return 0.0
    k = 2 / (n + 1)
    e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e


def _corr(a: list[float], b: list[float]) -> float:
    """수익률 상관계수 (시계열 길이 불일치 시 뒤에서 맞춤)."""
    n = min(len(a), len(b))
    if n < 30:
        return 0.0
    ra = [(a[i] / a[i - 1] - 1) for i in range(len(a) - n + 1, len(a)) if a[i - 1] > 0]
    rb = [(b[i] / b[i - 1] - 1) for i in range(len(b) - n + 1, len(b)) if b[i - 1] > 0]
    m = min(len(ra), len(rb))
    if m < 30:
        return 0.0
    ra, rb = ra[-m:], rb[-m:]
    ma, mb = sum(ra) / m, sum(rb) / m
    cov = sum((ra[i] - ma) * (rb[i] - mb) for i in range(m))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((x - mb) ** 2 for x in rb))
    if va * vb == 0:
        return 0.0
    return cov / (va * vb)


def build_graph(force: bool = False) -> dict:
    global _cache, _cache_ts
    with _lock:
        if not force and _cache is not None and (time.time() - _cache_ts) < TTL:
            return _cache

    import db
    import models
    import fundamentals_cache
    from sqlalchemy import select

    s = db.get_session_factory()()
    try:
        rows = s.execute(
            select(models.AiAnalysisCache).order_by(models.AiAnalysisCache.analyzed_at.desc())
        ).scalars().all()
        # '관종 신입' 3일 뱃지: admin(user_id=1) 워치리스트 편입 3일 이내 종목
        from datetime import timedelta as _td
        cutoff = datetime.now() - _td(days=3)
        new_codes = {
            str(c) for c in s.execute(
                select(models.Watchlist.stock_code).where(
                    models.Watchlist.user_id == 1,
                    models.Watchlist.created_at >= cutoff,
                )
            ).scalars().all()
        }
    finally:
        s.close()

    nodes: list[dict] = []
    series: dict[str, list[float]] = {}
    etf_holdings: dict[str, list[dict]] = {}  # ETF 코드 → 구성종목 [{code, weight}]
    for r in rows:
        pj = r.result_json if isinstance(r.result_json, dict) else {}
        st = pj.get("stock", {}) or {}
        if pj.get("etfHoldings"):
            etf_holdings[r.stock_code] = pj["etfHoldings"]
        ser = (pj.get("series") or {}).get("closes") or []
        sector = st.get("sector") or ("ETF" if str(r.stock_code)[0].isalpha() or (r.stock_name or "").startswith("KODEX") else "기타")
        price = float(st.get("currentPrice") or (ser[-1] if ser else 0) or 0)
        shares = fundamentals_cache.get_shares(str(r.stock_code))
        cap = price * shares if (price > 0 and shares > 0) else 0.0
        chg1d = 0.0
        if len(ser) >= 2 and float(ser[-2] or 0) > 0:
            chg1d = round((float(ser[-1]) / float(ser[-2]) - 1) * 100, 2)
        # 정배열 판정 (EMA5 > EMA20 > EMA60) + 강도 (20일 수익률 0~30% → 0~1)
        fser = [float(x) for x in ser]
        aligned = False
        align_str = 0.0
        if len(fser) >= 60:
            e5, e20, e60 = _ema_last(fser, 5), _ema_last(fser, 20), _ema_last(fser, 60)
            aligned = e5 > e20 > e60
            if aligned and len(fser) >= 21 and fser[-21] > 0:
                chg20 = (fser[-1] / fser[-21] - 1) * 100
                align_str = round(max(0.0, min(1.0, chg20 / 30)), 3)
        nodes.append({
            "code": r.stock_code,
            "name": r.stock_name or r.stock_code,
            "sector": sector,
            "cap": cap,
            "score": float(r.confidence or 0),
            "signal": r.signal,
            "hasReport": bool(pj.get("aiReport")) or bool(pj),
            "chg1d": chg1d,
            "aligned": aligned,       # EMA 정배열 여부
            "alignStr": align_str,    # 정배열 상승 강도 0~1
            "isEtf": r.stock_code in etf_holdings or bool(pj.get("etfHoldings")),
            "isNew": str(r.stock_code) in new_codes,  # 관종 신입 (편입 3일 이내)
        })
        if len(ser) >= 40:
            series[r.stock_code] = [float(x) for x in ser]

    # 시총 정규화 (log) — 0~1
    caps = [n["cap"] for n in nodes if n["cap"] > 0]
    cmin = math.log(min(caps)) if caps else 0.0
    cmax = math.log(max(caps)) if caps else 1.0
    for n in nodes:
        n["capNorm"] = (
            (math.log(n["cap"]) - cmin) / (cmax - cmin) if n["cap"] > 0 and cmax > cmin else 0.2
        )

    # 섹터별 주도주: 정배열 상승 중인 종목 가운데 (강도+점수+시총) 최고 1개
    best: dict[str, tuple[float, int]] = {}
    for i, n in enumerate(nodes):
        if not n["aligned"] or n["sector"] in ("기타", "ETF") or n["isEtf"]:
            continue
        rank = n["alignStr"] * 50 + n["score"] * 0.3 + n["capNorm"] * 20
        if n["sector"] not in best or rank > best[n["sector"]][0]:
            best[n["sector"]] = (rank, i)
    leader_idx = {i for _, i in best.values()}
    for i, n in enumerate(nodes):
        n["leader"] = i in leader_idx

    # 엣지: W = α·corr + β·sameSector + γ·gravity, 노드당 상위 K개
    idx = {n["code"]: i for i, n in enumerate(nodes)}
    cand: dict[int, list[tuple[float, int]]] = {i: [] for i in range(len(nodes))}
    codes = [n["code"] for n in nodes]
    for i in range(len(codes)):
        for j in range(i + 1, len(codes)):
            a, b = nodes[i], nodes[j]
            corr = 0.0
            if a["code"] in series and b["code"] in series:
                corr = max(0.0, _corr(series[a["code"]], series[b["code"]]))
            same = 1.0 if (a["sector"] == b["sector"] and a["sector"] not in ("기타", "ETF")) else 0.0
            grav = a["capNorm"] * b["capNorm"]
            w = ALPHA * corr + BETA * same + GAMMA * grav
            if w > 0.18:
                cand[i].append((w, j))
                cand[j].append((w, i))

    edge_set: set[tuple[int, int]] = set()
    for i, lst in cand.items():
        lst.sort(reverse=True)
        for w, j in lst[:TOP_K_EDGES]:
            edge_set.add((min(i, j), max(i, j)))
    edges = []
    wmap = {}
    for i, lst in cand.items():
        for w, j in lst:
            wmap[(min(i, j), max(i, j))] = w
    # ETF ↔ 구성종목 엣지: 편입 비중 → 가중치 (TOP_K 제한과 무관하게 항상 연결)
    for etf_code, holdings in etf_holdings.items():
        ei = idx.get(etf_code)
        if ei is None:
            continue
        for h in holdings:
            hi = idx.get(str(h.get("code", "")))
            if hi is None:
                continue
            # 비중 34% → w≈0.85, 비중 2% → w≈0.33 (스프링이 실제로 당기는 수준으로)
            w_etf = min(0.95, 0.3 + float(h.get("weight", 0)) / 100 * 1.6)
            key = (min(ei, hi), max(ei, hi))
            if key not in wmap or wmap[key] < w_etf:
                wmap[key] = w_etf
            edge_set.add(key)

    for (i, j) in edge_set:
        edges.append({"a": i, "b": j, "w": round(wmap.get((i, j), 0.2), 3)})

    # 외부 환경 → 섹터별 군집 강화 계수 (시장 기후)
    boosts: dict[str, float] = {}
    climate: dict[str, float] = {}
    try:
        import sector_rotation
        rot = sector_rotation.compute_sector_rotation(force=False)
        m = rot.get("macroDetail", {})
        climate = {
            "krw": float(m.get("usKrwChg5d") or 0),
            "oil": float(m.get("oilChg5d") or 0),
            "rate": float(m.get("tnxChg5d") or 0),
            "nasdaq": float(m.get("nasdaqChg5d") or 0),
        }
        for sec, sens in SENSITIVITY.items():
            f = sum(THETA * climate[k] * sens.get(k, 0.0) for k in climate)
            boosts[sec] = round(max(0.6, min(1.6, 1.0 + f)), 3)
    except Exception:
        boosts = {}

    result = {
        "asOf": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "nodes": nodes,
        "edges": edges,
        "sectorBoost": boosts,   # 같은 섹터 스프링에 곱할 계수 (외부 바람)
        "climate": climate,      # 환율/유가/금리/나스닥 5일 변화율 (%)
        "cached": False,
    }
    with _lock:
        _cache = {**result, "cached": True}
        _cache_ts = time.time()
    return result
