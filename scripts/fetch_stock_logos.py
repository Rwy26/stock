"""
관심종목 전체 로고를 Naver pstatic CDN에서 다운로드해 아이콘 태그를 URL로 교체한다.

사용법:
  cd c:\stock\backend
  c:\stock\backend\.venv\Scripts\python.exe ..\scripts\fetch_stock_logos.py
"""

from __future__ import annotations

import os
import sys
import time
import json
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT   = SCRIPT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"
LOGO_DIR    = BACKEND_DIR / "static" / "logos"

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

SVG_URL = "https://ssl.pstatic.net/imgstock/fn/real/logo/stock/Stock{code}.svg"
PNG_URL = "https://ssl.pstatic.net/imgstock/fn/real/logo/png/stock/Stock{code}.png"
# 네이버에 없는 종목 보완: 토스 증권 로고 CDN (PNG)
TOSS_URL = "https://static.toss.im/png-icons/securities/icn-sec-fill-{code}.png"

LOGO_SERVE_PREFIX = "/static/logos"


def fetch_logo(code: str) -> tuple[bytes | None, str]:
    """SVG 우선, 없으면 PNG. (content, ext) 반환."""
    for url, ext in [
        (SVG_URL.format(code=code), "svg"),
        (PNG_URL.format(code=code), "png"),
        (TOSS_URL.format(code=code), "png"),
    ]:
        try:
            r = httpx.get(url, headers=HEADERS, timeout=8, follow_redirects=True)
            if r.status_code == 200 and len(r.content) > 200:
                ct = r.headers.get("content-type", "")
                if "image" in ct or "svg" in ct or "xml" in ct:
                    return r.content, ext
        except Exception:
            pass
    return None, ""


def as_tag_list(raw) -> list[str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, list):
        return []
    return [str(t).strip() for t in raw if str(t).strip()]


def main() -> None:
    import db
    import models

    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[logo] output dir: {LOGO_DIR}")

    session = db.get_session_factory()()
    try:
        rows = session.execute(
            select(models.Watchlist.stock_code, models.Stock.name)
            .join(models.Stock, models.Stock.code == models.Watchlist.stock_code)
            .where(models.Watchlist.user_id == 1)
            .order_by(models.Stock.code)
        ).all()

        print(f"[logo] total watchlist stocks: {len(rows)}")
        ok = skipped = failed = 0

        for stock_code, name in rows:
            code = str(stock_code)
            name = str(name or code)

            # 파일 저장
            svg_path = LOGO_DIR / f"{code}.svg"
            png_path = LOGO_DIR / f"{code}.png"
            existing = svg_path if svg_path.exists() else (png_path if png_path.exists() else None)

            if existing:
                ext = existing.suffix.lstrip(".")
                logo_url = f"{LOGO_SERVE_PREFIX}/{code}.{ext}"
                skipped += 1
            else:
                content, ext = fetch_logo(code)
                if content:
                    dest = LOGO_DIR / f"{code}.{ext}"
                    dest.write_bytes(content)
                    logo_url = f"{LOGO_SERVE_PREFIX}/{code}.{ext}"
                    ok += 1
                    print(f"  [OK]   {code} {name:16s} -> {logo_url}")
                else:
                    failed += 1
                    print(f"  [FAIL] {code} {name}")
                    continue
                time.sleep(0.04)

            # stock_interest.tags 아이콘 태그 교체
            interest = session.execute(
                select(models.StockInterest).where(
                    models.StockInterest.user_id == 1,
                    models.StockInterest.stock_code == code,
                )
            ).scalar_one_or_none()

            new_icon_tag = f"아이콘|{logo_url}"
            if interest is None:
                session.add(
                    models.StockInterest(
                        user_id=1,
                        stock_code=code,
                        mention_count=1,
                        interest_weight=1.0,
                        analysis_depth=1,
                        tags=[new_icon_tag],
                    )
                )
            else:
                tags = as_tag_list(interest.tags)
                # 기존 아이콘 태그 교체
                tags = [t for t in tags if not t.startswith("아이콘|")]
                tags.insert(0, new_icon_tag)
                interest.tags = tags

        session.commit()
        total = ok + skipped
        print(f"\n[logo] done - downloaded={ok}  reused={skipped}  failed={failed}  icon_tags_updated={total}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
