"""refresh_exclusions.py — 거래 제외 종목 인덱스 전수 스윕.

판정 (backend/exclusion_engine.run_sweep):
  - 정적 규칙: 스팩 / 우선주 / 리츠 / ETF·ETN(pykrx 목록 대조)
  - 유동성: daily_prices 최근 20일 평균 거래대금 < 기준(기본 10억), 동전주(기본 1,000원 미만)
  - --kis: 종목당 KIS 현재가 1콜로 시장조치(거래정지/관리종목/정리매매/투자경고 등) 갱신
           (관리자(user_id=1) KIS 프로필 사용 — 읽기 전용 시세 조회만, 주문 없음)

제외 종목의 기존 데이터 정리 (--purge — 명시할 때만 실행):
  daily_prices / indicator_scores / recommendations / daily_investor_flow /
  short_selling_daily / news_articles / ai_analysis_cache 에서 제외 종목 행 삭제.
  매매 기록(자동매매 로그/포지션/포트폴리오/워치리스트)은 삭제하지 않는다.

사용법:
  python scripts/refresh_exclusions.py                # 정적 + 유동성
  python scripts/refresh_exclusions.py --kis          # + KIS 시장조치
  python scripts/refresh_exclusions.py --kis --purge  # + 기존 데이터 정리
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select, text  # noqa: E402

import db as apollo_db  # noqa: E402
import exclusion_engine  # noqa: E402
import models  # noqa: E402

PURGE_TABLES = [
    "daily_prices",
    "indicator_scores",
    "recommendations",
    "daily_investor_flow",
    "short_selling_daily",
    "news_articles",
    "ai_analysis_cache",
]


def main() -> int:
    do_kis = "--kis" in sys.argv
    do_purge = "--purge" in sys.argv

    s = apollo_db.get_session_factory()()
    try:
        profile = None
        if do_kis:
            profile = s.execute(
                select(models.KisProfile).where(models.KisProfile.user_id == 1)
            ).scalar_one_or_none()
            if profile is None or not getattr(profile, "app_key", None):
                print("관리자 KIS 프로필 없음 — --kis 생략하고 정적/유동성만 수행")
                do_kis = False

        print(f"[{datetime.now().isoformat(timespec='seconds')}] 스윕 시작 (kis={do_kis} purge={do_purge})")
        result = exclusion_engine.run_sweep(s, kis_profile=profile, do_kis_status=do_kis)
        print(
            f"검사 {result['checked']}종목 / 제외 {result['excluded']}종목"
            + (f" / KIS 조회실패 {result['kis_errors']}건(기존 태그 유지)" if do_kis else "")
        )

        entries = exclusion_engine.get_exclusions(s, force=True)
        for code, e in sorted(entries.items()):
            labels = ", ".join(exclusion_engine.TAG_LABELS.get(t, t) for t in e["tags"])
            print(f"  {code} {e['name'] or '':<22} {labels}" + (f" — {e['detail']}" if e.get("detail") else ""))

        if do_purge and entries:
            codes = list(entries.keys())
            print(f"\n[purge] 제외 {len(codes)}종목의 종목별 데이터 삭제 (매매 기록은 보존):")
            placeholders = ",".join(f":c{i}" for i in range(len(codes)))
            params = {f"c{i}": c for i, c in enumerate(codes)}
            for table in PURGE_TABLES:
                res = s.execute(
                    text(f"DELETE FROM {table} WHERE stock_code IN ({placeholders})"), params
                )
                print(f"  {table:<22} {res.rowcount}행 삭제")
            s.commit()
    finally:
        s.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
