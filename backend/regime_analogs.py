"""닷컴(1995~2002) 유사 국면 보조 표본 — 시장 나침반 11단계 확장.

근거 데이터: D:\STOCK DATA-US\dotcom_1995_2002\features\*.csv
  (나스닥 3지수 + AMZN/CSCO/INTC/ORCL/MSFT 일봉에서 target_engine._regime_features
   와 동일 정의로 산출한 6차원 국면 특징 + 실제 20일 후 수익 — 구축·검증 내역은
   해당 폴더 README.md / verification_report.json)

매칭 방식: **시장별 자체 z-정규화** — 한국 종목의 현재 벡터는 자국 후보 분포로,
미국 표본은 미국 풀 분포로 각각 z-정규화한 뒤 유클리드 거리 비교.
즉 "자국 분포 내에서 어떤 위치의 국면인가"를 기준으로 시장 간 대응시킨다.

사용량: 기동 시 1회 적재(~14.5천 행, ~160ms, 상주 ~2.3MB), 쿼리당 ~20ms,
외부 API 호출 0건. 데이터 폴더가 없으면 error 반환 — 본 확률 계산엔 영향 없음.
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
                                 "dd": _opt("drawdown_pct")})
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
        _cache = {"rows": rows, "means": means, "sds": sds}
        return _cache


def find_analogs(z_query: list[float], k: int = 20) -> dict:
    """한국 종목의 z-국면 벡터와 가장 가까운 닷컴 시점 k건의 실제 결과 빈도.

    z_query: target_engine._similar_regime_prob 가 자국 후보 분포로 정규화한
             현재 6차원 벡터. 반환 확률은 전부 실제 빈도 — 만들어낸 수치 아님.
    """
    data = _load()
    if "error" in data:
        return {"error": data["error"]}
    if len(z_query) != len(DIMS):
        return {"error": f"차원 불일치 ({len(z_query)} != {len(DIMS)})"}

    rows = data["rows"]
    scored = sorted(
        (sum((r["z"][d] - z_query[d]) ** 2 for d in range(len(DIMS))) ** 0.5, i)
        for i, r in enumerate(rows)
    )
    # 자기상관 완화: 같은 종목 내 5봉 미만 간격 중복 채택 금지
    picked: list[tuple[float, dict]] = []
    taken: dict[str, list[int]] = {}
    for dist, i in scored:
        r = rows[i]
        if any(abs(r["seq"] - s) < 5 for s in taken.get(r["sym"], [])):
            continue
        picked.append((dist, r))
        taken.setdefault(r["sym"], []).append(r["seq"])
        if len(picked) >= k:
            break
    if not picked:
        return {"error": "닷컴 유사 국면 매칭 실패"}

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
        "continueUpPct": round(ups / total * 100, 1),
        "medianFwd20Pct": round(median20, 2),
        "phaseDistribution": dict(sorted(phases.items(), key=lambda x: -x[1])),
        "topMatches": [
            {"symbol": r["sym"], "date": r["date"], "phase": _phase(r["date"]),
             "fwd20Pct": r["fwd20"], "drawdownPct": r["dd"], "distance": round(dist, 3)}
            for dist, r in picked[:5]
        ],
        "avgDistance": round(sum(d for d, _ in picked) / total, 3),
        "basis": ("1995~2002 미국 닷컴 표본(나스닥 3지수 + 기술주 5종, 검증 데이터셋) "
                  "6차원 유사 국면 — 시장별 z-정규화 후 최근접, 실제 20일 후 수익 빈도"),
    }
