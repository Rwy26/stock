"""fundamentals_sync.py

매일 07:00 / 20:10 실행 (Windows 작업 스케줄러).

대상: 관심종목(워치리스트) 전체 ∪ AI 분석(ai_analysis_cache) 종목.
동작:
  1. KIS inquire_price 로 주가 + 발행주식수(상장주식수) 수집 → 시총 = 주가 × 발행주식수
  2. 네이버 금융(시총/주가)과 비교 → 1% 초과 차이는 불일치로 로그
  3. 발행주식수 등 기본적 분석 데이터를 D드라이브 캐시에 저장 (KIS 재호출 최소화)

KIS는 읽기 전용(시세 조회)만 사용 — 주문/거래 없음(킬스위치 무관).
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

import db as apollo_db  # noqa: E402
import models  # noqa: E402
import kis_client  # noqa: E402
import fundamentals_cache  # noqa: E402
from settings import settings  # noqa: E402
from pipeline_paths import get_pipeline_paths  # noqa: E402

MISMATCH_PCT = 1.0  # KIS vs 네이버 시총 차이 임계치(%)
KIS_SLEEP = 0.12    # KIS 호출 간 간격(초) — rate limit 보호


def _naver_quotes(codes: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    for i in range(0, len(codes), 40):
        part = codes[i:i + 40]
        url = "https://polling.finance.naver.com/api/realtime/domestic/stock/" + ",".join(part)
        try:
            r = httpx.get(url, headers=headers, timeout=8.0)
            r.raise_for_status()
            for d in r.json().get("datas", []):
                c = str(d.get("itemCode") or "")
                if not c:
                    continue

                def num(*keys: str) -> float:
                    for k in keys:
                        v = d.get(k)
                        if v not in (None, ""):
                            try:
                                return float(str(v).replace(",", ""))
                            except Exception:
                                continue
                    return 0.0

                out[c] = {"price": num("closePriceRaw", "closePrice"), "cap": num("marketValueFullRaw")}
        except Exception:
            continue
    return out


def _target_codes() -> list[str]:
    s = apollo_db.get_session_factory()()
    try:
        wl = s.execute(select(models.Watchlist.stock_code).distinct()).scalars().all()
        ai = s.execute(select(models.AiAnalysisCache.stock_code).distinct()).scalars().all()
    finally:
        s.close()
    codes = set()
    for c in list(wl) + list(ai):
        c = str(c or "").strip()
        if c:
            codes.add(c)
    return sorted(codes)


def _admin_profile():
    s = apollo_db.get_session_factory()()
    try:
        return s.execute(select(models.KisProfile).where(models.KisProfile.user_id == 1)).scalar_one_or_none()
    finally:
        s.close()


def main() -> int:
    now = datetime.now()
    codes = _target_codes()
    prof = _admin_profile()
    app_key = getattr(prof, "app_key", None)
    app_secret = getattr(prof, "app_secret", None)
    is_paper = bool(getattr(prof, "is_paper", False))

    naver = _naver_quotes(codes)
    mismatches: list[dict] = []

    for c in codes:
        kis_price = 0.0
        kis_shares = 0
        if app_key and app_secret:
            try:
                q = kis_client.inquire_price(
                    app_key=str(app_key),
                    app_secret=str(app_secret),
                    is_paper=is_paper,
                    code=c,
                    live_base_url=settings.kis_live_base_url,
                    paper_base_url=settings.kis_paper_base_url,
                )
                kis_price = float(q.price)
                kis_shares = int(q.shares)
            except Exception:
                pass
            time.sleep(KIS_SLEEP)

        nv = naver.get(c, {})
        naver_cap = float(nv.get("cap", 0.0))
        naver_price = float(nv.get("price", 0.0))

        shares = kis_shares if kis_shares > 0 else fundamentals_cache.get_shares(c)
        kis_cap = kis_price * shares if (kis_price > 0 and shares > 0) else 0.0
        diff_pct = (abs(kis_cap - naver_cap) / naver_cap * 100.0) if (kis_cap > 0 and naver_cap > 0) else None

        rec = {
            "code": c,
            "shares": shares,
            "kis_price": kis_price,
            "kis_cap": kis_cap,
            "naver_price": naver_price,
            "naver_cap": naver_cap,
            "diff_pct": round(diff_pct, 3) if diff_pct is not None else None,
            "source": "kis" if kis_shares > 0 else ("cache" if shares > 0 else "naver"),
            "updated_at": now.isoformat(timespec="seconds"),
        }
        fundamentals_cache.save(c, rec)
        if diff_pct is not None and diff_pct > MISMATCH_PCT:
            mismatches.append(rec)

    pp = get_pipeline_paths()
    pp.logs_dir.mkdir(parents=True, exist_ok=True)
    logf = pp.logs_dir / "fundamentals-sync.log"
    header = f"[{now.isoformat(timespec='seconds')}] synced={len(codes)} mismatches(>{MISMATCH_PCT}%)={len(mismatches)}"
    try:
        with logf.open("a", encoding="utf-8") as f:
            f.write(header + "\n")
            for r in mismatches:
                f.write(
                    f"   MISMATCH {r['code']} kis_cap={r['kis_cap']:.0f} naver_cap={r['naver_cap']:.0f} diff={r['diff_pct']}%\n"
                )
    except Exception:
        pass

    print(header)
    for r in mismatches[:20]:
        print(f"  MISMATCH {r['code']} diff={r['diff_pct']}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
