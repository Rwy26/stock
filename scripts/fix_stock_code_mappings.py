"""
stocks 코드↔이름 매핑 오류 2차 정정 (2026-06-12).

배경: 2026-06-10 fix_watchlist_codes.py 1차 정정에서 빠진 오류가 네이버 전수
교차검증(142종목)으로 추가 발견됨.
  - 코드 교체 6건: DB 이름(사용자 의도)은 맞고 코드가 다른 회사
      011810(실제 STX) -> 064350 현대로템
      033160(실제 엠케이전자) -> 131970 두산테스나
      040610(실제 SG&G) -> 043260 성호전자
      104480(실제 티케이케미칼) -> 064760 티씨케이
      267260(실제 HD현대일렉트릭) -> 010120 LS ELECTRIC
      111870(폐지 코드) -> 099320 쎄트렉아이
  - 이름 정정 7건: 코드 기준 실제 회사명으로 정정 (남는 행이 거짓말하지 않도록)
  - 폐지/무효 코드 6건: 네이버 조회 불가 → daily_prices 삭제 후 참조 0건이면 stocks 행 삭제
  - daily_prices 불량 행 일괄 삭제: volume=0 & OHLC 동일 (yfinance 거래정지일 패딩)

모든 신규 코드는 적용 전에 네이버 실시간 API로 이름을 재검증한다.
검증 실패 시 해당 건은 건너뛰고 보고만 한다.

사용법:
  .\\backend\\.venv\\Scripts\\python.exe scripts\\fix_stock_code_mappings.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"
LOGO_DIR = BACKEND_DIR / "static" / "logos"
SECTOR_JSON = BACKEND_DIR / "sector_classification.json"

sys.path.insert(0, str(BACKEND_DIR))

import httpx
from sqlalchemy import text

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# (잘못된 코드, 올바른 코드, 의도한 종목명)
CODE_SWAPS = [
    ("011810", "064350", "현대로템"),
    ("033160", "131970", "두산테스나"),
    ("040610", "043260", "성호전자"),
    ("104480", "064760", "티씨케이"),
    ("267260", "010120", "LS ELECTRIC"),
    ("111870", "099320", "쎄트렉아이"),
]

# 코드는 유효하나 이름이 틀린 행 — 네이버 실시간 이름으로 정정
NAME_FIX_CODES = [
    "011810",  # STX (현대로템 아님)
    "033160",  # 엠케이전자
    "040610",  # SG&G
    "104480",  # 티케이케미칼
    "267260",  # HD현대일렉트릭
    "182400",  # 엔케이젠바이오텍코리아 (1차 정정 때 이름 누락)
    "079550",  # LIG넥스원 -> LIG디펜스앤에어로스페이스 (사명 변경)
]

# 네이버 조회 불가(폐지/무효) — daily_prices 삭제, 참조 없으면 stocks 행도 삭제
DEAD_CODES = ["036490", "111870", "288490", "314760", "384490", "477010"]


def naver_name(code: str) -> str | None:
    try:
        r = httpx.get(
            f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}",
            headers=HEADERS, timeout=10,
        )
        datas = r.json().get("datas", [])
        return str(datas[0].get("stockName") or "").strip() if datas else None
    except Exception:
        return None


def main() -> None:
    import db
    import models

    session = db.get_session_factory()()
    applied_swaps: list[tuple[str, str, str]] = []
    try:
        # 1) 신규 코드 전건 네이버 재검증
        print("[1/7] 신규 코드 네이버 재검증")
        verified: dict[str, str] = {}
        for old, new, intended in CODE_SWAPS:
            real = naver_name(new)
            ok = real is not None and real.replace(" ", "") == intended.replace(" ", "")
            print(f"  {old} -> {new} ({intended}): naver={real} {'OK' if ok else 'MISMATCH - skip'}")
            if ok:
                verified[old] = new

        # 2) stocks 테이블: 신규 코드 행 upsert
        print("[2/7] stocks 테이블 정비")
        for old, new, intended in CODE_SWAPS:
            if old not in verified:
                continue
            row = session.get(models.Stock, new)
            if row is None:
                session.add(models.Stock(code=new, name=intended, market=None))
                print(f"  + stocks {new} {intended}")
            elif (row.name or "").replace(" ", "") != intended.replace(" ", ""):
                print(f"  ~ stocks {new} 이름 {row.name} -> {intended}")
                row.name = intended

        # 3) 이름 정정 — 네이버 실시간 이름이 진실
        print("[3/7] 종목명 정정 (네이버 기준)")
        for code in NAME_FIX_CODES:
            real = naver_name(code)
            if not real:
                print(f"  ? {code}: 네이버 조회 실패 - skip")
                continue
            row = session.get(models.Stock, code)
            if row is not None and (row.name or "") != real:
                print(f"  ~ {code}: {row.name} -> {real}")
                row.name = real

        # 4) watchlist + stock_interest 코드 이전
        print("[4/7] watchlist / stock_interest 코드 이전")
        from sqlalchemy import select
        for old, new, intended in CODE_SWAPS:
            if old not in verified:
                continue
            for model, label in ((models.Watchlist, "watchlist"),
                                 (models.StockInterest, "stock_interest")):
                rec = session.execute(
                    select(model).where(model.user_id == 1, model.stock_code == old)
                ).scalar_one_or_none()
                if rec is None:
                    continue
                dup = session.execute(
                    select(model).where(model.user_id == 1, model.stock_code == new)
                ).scalar_one_or_none()
                if dup is not None:
                    session.delete(rec)
                    print(f"  - {label} {old} 삭제 ({new} 이미 존재)")
                else:
                    rec.stock_code = new
                    print(f"  ~ {label} {old} -> {new}")
            applied_swaps.append((old, new, intended))
        session.commit()

        # 5) daily_prices 불량 행 삭제
        print("[5/7] daily_prices 불량 행 삭제")
        r = session.execute(text("""
            DELETE FROM daily_prices
            WHERE volume = 0
              AND open_price = close_price
              AND high_price = close_price
              AND low_price  = close_price
        """))
        print(f"  - volume=0 & OHLC 플랫 (거래정지일 패딩): {r.rowcount}행")
        for code in DEAD_CODES:
            r = session.execute(
                text("DELETE FROM daily_prices WHERE stock_code=:c"), {"c": code})
            if r.rowcount:
                print(f"  - 폐지 코드 {code} 일봉: {r.rowcount}행")
        session.commit()

        # 6) 폐지/무효 stocks 행 삭제 (참조 0건일 때만)
        print("[6/7] 폐지/무효 stocks 행 정리")
        fks = session.execute(text("""
            SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE
            WHERE REFERENCED_TABLE_SCHEMA = DATABASE()
              AND REFERENCED_TABLE_NAME = 'stocks'
        """)).all()
        for code in DEAD_CODES:
            refs = []
            for tbl, col in fks:
                n = session.execute(
                    text(f"SELECT COUNT(*) FROM {tbl} WHERE {col}=:c"), {"c": code}
                ).scalar()
                if n:
                    refs.append(f"{tbl}({n})")
            if refs:
                print(f"  ! {code}: 참조 잔존 {', '.join(refs)} - stocks 행 유지")
                continue
            r = session.execute(text("DELETE FROM stocks WHERE code=:c"), {"c": code})
            if r.rowcount:
                print(f"  - stocks {code} 삭제 (폐지/무효, 참조 없음)")
        session.commit()
    finally:
        session.close()

    # 7) 파일 정리: 옛 코드 로고/펀더멘털 캐시 + sector_classification.json 키 이동
    print("[7/7] 로고·캐시·섹터분류 파일 정리")
    try:
        from pipeline_paths import get_pipeline_paths
        fund_dir = get_pipeline_paths().data_fundamentals
    except Exception:
        fund_dir = None
    for old, new, _ in applied_swaps:
        for ext in ("svg", "png"):
            p = LOGO_DIR / f"{old}.{ext}"
            if p.exists():
                p.unlink()
                print(f"  - logo {p.name}")
        if fund_dir is not None:
            fp = fund_dir / f"{old}.json"
            if fp.exists():
                fp.unlink()
                print(f"  - fundamentals {fp.name}")

    data = json.loads(SECTOR_JSON.read_text(encoding="utf-8"))
    changed = False
    for old, new, _ in applied_swaps:
        if old in data:
            data[new] = data.pop(old)
            changed = True
            print(f"  ~ sector key {old} -> {new} ({data[new]})")
    if changed:
        SECTOR_JSON.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(f"\n완료: 코드 교체 {len(applied_swaps)}건 / 이름 정정 {len(NAME_FIX_CODES)}건 / 폐지 코드 정리 {len(DEAD_CODES)}건")


if __name__ == "__main__":
    main()
