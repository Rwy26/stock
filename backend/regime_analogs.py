"""닷컴(1995~2002) 유사 국면 보조 표본 — 시장 나침반 11단계 확장.

근거 데이터: D:\STOCK DATA-US\dotcom_1995_2002\
  features\*.csv          target_engine._regime_features 와 동일 정의의 6차원 특징
                          + 실제 20일 후 수익 (나스닥 3지수 + 기술주 5종)
  valuation\pe_ps_daily.csv  10-K 전수 재대조 P/E·P/S → 7번째 차원(밸류에이션 백분위)

매칭 방식: **시장별 자체 z-정규화** — 한국 종목의 현재 벡터는 자국 후보 분포로,
미국 표본은 미국 풀 분포로 각각 z-정규화한 뒤 유클리드 거리 비교.
7번째 차원(밸류에이션 백분위 0~100)은 양쪽 모두 '자기 분포 내 백분위'라 그 자체로
시장중립 — 균등분포 표준편차(28.87)로 z-스케일 변환만 해서 합산한다.

품질 가드 (2026-06-12 30종목 실측 근거):
  DIST_CUTOFF    원거리 매칭 차단 (실측 최대 7.57 같은 무의미 매칭 제거)
  MAX_PER_SYMBOL 시계열당 상한 (AMZN 쏠림 38% 완화)
  매칭 10건 미만이면 lowConfidence — 프런트 점멸 보정은 15건 이상에서만 작동.

사용량: 기동 시 1회 적재(쿼리당 ~20ms), 외부 API 호출 0건.
데이터 폴더가 없으면 error 반환 — 본 확률 계산엔 영향 없음.
"""

from __future__ import annotations

import csv
import os
import threading
from pathlib import Path
from typing import Optional

DIMS = ["trend_ema_gap_pct", "rsi14", "ret20d_std_pct",
        "vol_ratio_5_20", "pos_60d_pctile", "ret_20d_pct"]

DATA_ROOT = Path(os.environ.get("DOTCOM_DATA_ROOT", r"D:\STOCK DATA-US\dotcom_1995_2002"))

DIST_CUTOFF = 3.0      # z-공간 유클리드 거리 상한
MAX_PER_SYMBOL = 6     # 매칭 k=20 중 같은 시계열 최대 채택 수
_UNIF_SD = 28.87       # 0~100 균등분포 표준편차 — 백분위 차원 z-스케일

# 버블 국면 구분 — 나스닥 종합 고점 2000-03-10 (FRED 검증값) 기준 결정론 라벨
_PHASES = [
    ("형성기", "1995-01-01", "1998-09-30"),
    ("과열기", "1998-10-01", "2000-03-10"),
    ("붕괴기", "2000-03-11", "2001-09-30"),
    ("바닥권", "2001-10-01", "2002-12-31"),
]

_lock = threading.Lock()
_cache: Optional[dict] = None


def _phase(date: str) -> str:
    for name, a, b in _PHASES:
        if a <= date <= b:
            return name
    return "기타"


def _valuation_pctiles() -> dict[tuple[str, str], float]:
    """(symbol, date) → 밸류에이션 252일 롤링 백분위 (P/E 4사, P/S AMZN).

    지수 3종은 밸류에이션이 없어 미포함 — 해당 행은 7차원 매칭에서 제외된다.
    백분위는 시점 기준 과거 252관측 내 순위 (미래 참조 없음, 최소 120관측).
    """
    out: dict[tuple[str, str], float] = {}
    f = DATA_ROOT / "valuation" / "pe_ps_daily.csv"
    if not f.exists():
        return out
    series: dict[str, list[tuple[str, float]]] = {}
    with open(f, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            v = r.get("pe_ttm") or r.get("ps_ttm")
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            series.setdefault(r["symbol"], []).append((r["date"], fv))
    for sym, vals in series.items():
        vals.sort()
        for i, (d, v) in enumerate(vals):
            window = [x for _, x in vals[max(0, i - 251): i + 1]]
            if len(window) >= 120:
                rank = sum(1 for x in window if x <= v)
                out[(sym, d)] = round(rank / len(window) * 100, 1)
    return out


def _load() -> dict:
    """features CSV → 표본 풀 + z-정규화 통계 (프로세스 1회, 스레드 안전)."""
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is not None:
            return _cache
        feat_dir = DATA_ROOT / "features"
        if not feat_dir.exists():
            _cache = {"error": f"닷컴 데이터 없음: {feat_dir}"}
            return _cache
        valp = _valuation_pctiles()
        rows: list[dict] = []
        for f in sorted(feat_dir.glob("*_features.csv")):
            sym = f.stem.replace("_features", "")
            seq = 0
            with open(f, encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    seq += 1
                    try:
                        vec = [float(r[d]) for d in DIMS]
                        fwd20 = float(r["fwd_ret_20d_pct"])  # 실제 결과 없는 행 제외
                    except (TypeError, ValueError, KeyError):
                        continue

                    def _opt(key: str) -> Optional[float]:
                        try:
                            return float(r[key])
                        except (TypeError, ValueError, KeyError):
                            return None

                    rows.append({"sym": sym, "seq": seq, "date": r["date"],
                                 "vec": vec, "fwd20": fwd20,
                                 "fwd60": _opt("fwd_ret_60d_pct"),
                                 "dd": _opt("drawdown_pct"),
                                 "valp": valp.get((sym, r["date"]))})
        if len(rows) < 500:
            _cache = {"error": f"닷컴 표본 부족 ({len(rows)}행)"}
            return _cache
        n = len(rows)
        means, sds = [], []
        for d in range(len(DIMS)):
            vals = [r["vec"][d] for r in rows]
            mu = sum(vals) / n
            sd = (sum((v - mu) ** 2 for v in vals) / n) ** 0.5
            means.append(mu)
            sds.append(sd if sd > 1e-9 else 1.0)
        for r in rows:
            r["z"] = [(r["vec"][d] - means[d]) / sds[d] for d in range(len(DIMS))]
        _cache = {"rows": rows, "means": means, "sds": sds,
                  "valpCount": sum(1 for r in rows if r["valp"] is not None)}
        return _cache


def find_analogs(z_query: list[float], k: int = 20,
                 val_pctile: Optional[float] = None) -> dict:
    """한국 종목의 z-국면 벡터와 가장 가까운 닷컴 시점 k건의 실제 결과 빈도.

    z_query    : 자국 후보 분포로 정규화한 6차원 벡터 (target_engine 산출).
    val_pctile : 한국 종목 P/E 의 자기 이력 내 백분위(0~100) — 제공 시
                 밸류에이션 보유 행(기술주 5종)만 대상으로 7차원 매칭.
    반환 확률은 전부 실제 빈도 — 만들어낸 수치 아님.
    """
    data = _load()
    if "error" in data:
        return {"error": data["error"]}
    if len(z_query) != len(DIMS):
        return {"error": f"차원 불일치 ({len(z_query)} != {len(DIMS)})"}

    rows = data["rows"]
    use_val = val_pctile is not None and data.get("valpCount", 0) >= 500
    zq_val = ((val_pctile - 50.0) / _UNIF_SD) if use_val else None

    def _dist(r: dict) -> Optional[float]:
        if use_val and r["valp"] is None:
            return None  # 밸류에이션 없는 행(지수)은 7차원 매칭에서 제외
        s = sum((r["z"][d] - z_query[d]) ** 2 for d in range(len(DIMS)))
        if use_val:
            s += ((r["valp"] - 50.0) / _UNIF_SD - zq_val) ** 2
        return s ** 0.5

    scored = sorted((dv, i) for i, r in enumerate(rows)
                    if (dv := _dist(r)) is not None)
    # 품질 가드: 거리 컷오프 + 시계열당 상한 + 같은 종목 5봉 미만 간격 금지
    picked: list[tuple[float, dict]] = []
    taken: dict[str, list[int]] = {}
    for dist, i in scored:
        if dist > DIST_CUTOFF:
            break
        r = rows[i]
        seqs = taken.get(r["sym"], [])
        if len(seqs) >= MAX_PER_SYMBOL or any(abs(r["seq"] - s) < 5 for s in seqs):
            continue
        picked.append((dist, r))
        taken.setdefault(r["sym"], []).append(r["seq"])
        if len(picked) >= k:
            break
    if not picked:
        return {"error": f"거리 {DIST_CUTOFF} 이내 닷컴 유사 국면 없음 — 전례 없는 국면"}

    total = len(picked)
    ups = sum(1 for _, r in picked if r["fwd20"] > 0)
    fwd20s = sorted(r["fwd20"] for _, r in picked)
    mid = total // 2
    median20 = fwd20s[mid] if total % 2 else (fwd20s[mid - 1] + fwd20s[mid]) / 2
    phases: dict[str, int] = {}
    for _, r in picked:
        p = _phase(r["date"])
        phases[p] = phases.get(p, 0) + 1

    return {
        "sample": total,
        "poolSize": len(rows),
        "lowConfidence": total < 10,
        "valuationDimUsed": bool(use_val),
        "continueUpPct": round(ups / total * 100, 1),
        "medianFwd20Pct": round(median20, 2),
        "phaseDistribution": dict(sorted(phases.items(), key=lambda x: -x[1])),
        "topMatches": [
            {"symbol": r["sym"], "date": r["date"], "phase": _phase(r["date"]),
             "fwd20Pct": r["fwd20"], "drawdownPct": r["dd"],
             "valuationPctile": r["valp"], "distance": round(dist, 3)}
            for dist, r in picked[:5]
        ],
        "avgDistance": round(sum(d for d, _ in picked) / total, 3),
        "basis": (("7차원(6차원 + 밸류에이션 백분위)" if use_val else "6차원")
                  + " 유사 국면 — 1995~2002 미국 닷컴 검증 표본, 시장별 z-정규화 후 "
                  f"최근접 (거리 {DIST_CUTOFF} 이내, 시계열당 최대 {MAX_PER_SYMBOL}건), "
                  "실제 20일 후 수익 빈도"),
    }
