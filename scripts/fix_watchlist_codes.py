"""
관심종목 코드↔이름 매핑 오류 일괄 정정 (2026-06-10).

배경: 종목을 이름으로 추가하면서 잘못된 코드가 입력된 건이 13건 발견됨.
  - 코드 교체 9건: DB 이름(사용자 의도)은 맞고 코드가 다른 회사/폐지 코드
  - 이름 정정 4건: 코드는 맞고 DB 이름이 틀림

모든 신규 코드는 적용 전에 네이버 금융 실시간 API로 이름을 재검증한다.
검증 실패 시 해당 건은 건너뛰고 보고만 한다.

사용법:
  cd c:\stock\backend
  .\.venv\Scripts\python.exe ..\scripts\fix_watchlist_codes.py
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
from sqlalchemy import select

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# (잘못된 코드, 올바른 코드, 의도한 종목명)
CODE_SWAPS = [
    ("042660", "329180", "HD현대중공업"),
    ("050890", "031980", "피에스케이홀딩스"),
    ("064260", "064400", "LG씨엔에스"),
    ("182400", "290650", "엘앤씨바이오"),
    ("036490", "036010", "아비코전자"),
    ("288490", "281740", "레이크머티리얼즈"),
    ("314760", "356860", "티엘비"),
    ("384490", "483650", "달바글로벌"),
    ("477010", "448900", "한국피아이엠"),
]

# (코드, 올바른 이름) — 코드는 맞고 이름만 정정
NAME_FIXES = [
    ("103590", "일진전기"),
    ("267250", "HD현대"),
    ("066970", "엘앤에프"),
    ("327260", "RF머트리얼즈"),
    # 교체로 빠지는 옛 코드들의 이름도 사실대로 바로잡는다 (남는 stocks 행이 거짓말하지 않도록)
    ("042660", "한화오션"),
    ("050890", "쏠리드"),
    ("064260", "다날"),
]

# sector_classification.json 키 이동 + 값 변경
SECTOR_KEY_MOVES = {old: new for old, new, _ in CODE_SWAPS}
SECTOR_VALUE_CHANGES = {"267250": "조선"}  # HD현대로보틱스(비상장)가 아니라 HD현대(조선 지주)


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
        print("[1/6] 신규 코드 네이버 재검증")
        verified: dict[str, str] = {}
        for old, new, intended in CODE_SWAPS:
            real = naver_name(new)
            ok = real is not None and real.replace(" ", "") == intended.replace(" ", "")
            print(f"  {old} -> {new} ({intended}): naver={real} {'OK' if ok else 'MISMATCH - skip'}")
            if ok:
                verified[old] = new

        # 2) stocks 테이블: 신규 코드 행 upsert
        print("[2/6] stocks 테이블 정비")
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

        # 3) 이름 정정 (잘못된 이름이 남지 않도록)
        print("[3/6] 종목명 정정")
        for code, correct in NAME_FIXES:
            row = session.get(models.Stock, code)
            if row is not None and (row.name or "") != correct:
                print(f"  ~ {code}: {row.name} -> {correct}")
                row.name = correct

        # 4) watchlist + stock_interest 코드 이전
        print("[4/6] watchlist / stock_interest 코드 이전")
        for old, new, intended in CODE_SWAPS:
            if old not in verified:
                continue
            dup = session.execute(
                select(models.Watchlist).where(
                    models.Watchlist.user_id == 1,
                    models.Watchlist.stock_code == new,
                )
            ).scalar_one_or_none()
            wl = session.execute(
                select(models.Watchlist).where(
                    models.Watchlist.user_id == 1,
                    models.Watchlist.stock_code == old,
                )
            ).scalar_one_or_none()
            if wl is None:
                print(f"  ? watchlist에 {old} 없음 - skip")
                continue
            if dup is not None:
                session.delete(wl)
                print(f"  - watchlist {old} 삭제 ({new} 이미 존재)")
            else:
                wl.stock_code = new
                print(f"  ~ watchlist {old} -> {new}")

            si = session.execute(
                select(models.StockInterest).where(
                    models.StockInterest.user_id == 1,
                    models.StockInterest.stock_code == old,
                )
            ).scalar_one_or_none()
            if si is not None:
                si_dup = session.execute(
                    select(models.StockInterest).where(
                        models.StockInterest.user_id == 1,
                        models.StockInterest.stock_code == new,
                    )
                ).scalar_one_or_none()
                if si_dup is None:
                    tags = si.tags if isinstance(si.tags, list) else json.loads(si.tags or "[]")
                    si.tags = [t for t in tags if not str(t).startswith("아이콘|")]
                    si.stock_code = new
                    print(f"  ~ stock_interest {old} -> {new} (아이콘 태그 제거)")
            applied_swaps.append((old, new, intended))

        session.commit()
    finally:
        session.close()

    # 5) 파일 정리: 옛 코드의 로고 / D드라이브 펀더멘털 캐시 삭제
    print("[5/6] 옛 코드 로고·캐시 파일 삭제")
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

    # 6) sector_classification.json 키 이동
    print("[6/6] sector_classification.json 갱신")
    data = json.loads(SECTOR_JSON.read_text(encoding="utf-8"))
    changed = False
    for old, new, _ in applied_swaps:
        if old in data:
            data[new] = data.pop(old)
            changed = True
            print(f"  ~ key {old} -> {new} ({data[new]})")
    for code, sector in SECTOR_VALUE_CHANGES.items():
        if data.get(code) != sector:
            data[code] = sector
            changed = True
            print(f"  ~ {code} 섹터 -> {sector}")
    if changed:
        SECTOR_JSON.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(f"\n완료: 코드 교체 {len(applied_swaps)}건, 이름 정정 {len(NAME_FIXES)}건")


if __name__ == "__main__":
    main()
