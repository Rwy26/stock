"""마지막 세션 등락률 스냅샷 1회 백필.

장전(전 종목 등락률 0)에 화면이 무채색이 되는 문제의 초기 데이터.
이후에는 장중 watchlist 조회가 자동으로 스냅샷을 갱신하므로 재실행 불필요.

KIS 일봉 마지막 2개 종가로 직전 거래일 등락률 계산 → last_session_quotes.json
사용법: cd c:\stock\backend && .\.venv\Scripts\python.exe ..\scripts\backfill_last_session.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

ETF_CODES = ["069500", "487240", "471990", "0098F0", "445290", "0080G0", "305720", "117700", "0167Z0"]


def main() -> int:
    import db
    import models
    import kis_client
    from settings import settings
    from sqlalchemy import select
    from pipeline_paths import get_pipeline_paths

    s = db.get_session_factory()()
    try:
        prof = s.execute(
            select(models.KisProfile).where(models.KisProfile.user_id == 1)
        ).scalar_one_or_none()
        codes = [str(c) for c in s.execute(
            select(models.Watchlist.stock_code).where(models.Watchlist.user_id == 1)
        ).scalars().all()]
    finally:
        s.close()
    if prof is None:
        print("KIS 프로필 없음")
        return 1
    kw = dict(
        app_key=str(prof.app_key), app_secret=str(prof.app_secret),
        is_paper=bool(prof.is_paper),
        live_base_url=settings.kis_live_base_url,
        paper_base_url=settings.kis_paper_base_url,
    )

    ratios: dict[str, float] = {}
    targets = codes + ETF_CODES
    for i, code in enumerate(targets):
        try:
            bars = kis_client.inquire_daily_chart(code=code, period="D", **kw)
            if len(bars) >= 2 and bars[-2]["close"] > 0:
                # 마지막 봉이 오늘(미개장 0봉)일 수 있으므로 종가>0 인 마지막 두 봉 사용
                closes = [b["close"] for b in bars if b["close"] > 0]
                if len(closes) >= 2:
                    ratios[code] = round((closes[-1] / closes[-2] - 1) * 100, 2)
        except Exception:
            pass
        time.sleep(0.12)
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(targets)}")

    out = get_pipeline_paths().data_external / "last_session_quotes.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"ratios": ratios}, ensure_ascii=False), encoding="utf-8")
    print(f"백필 완료: {len(ratios)}종목 → {out}")
    return 0


if __name__ == "__main__":
    import time as _t
    _t.sleep(65)  # KIS 토큰 발급 1분 제한
    raise SystemExit(main())
