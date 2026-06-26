"""뉴스 수집 파이프라인 — 시장 나침반 6단계(뉴스 분석) 데이터 공급.

소스: 네이버 모바일 증권 종목뉴스 API (키 불필요, 배치 불가 — 종목당 1콜)
  https://m.stock.naver.com/api/news/stock/{code}?pageSize=N&page=P

대상: 나침반 10개 섹터의 대표 종목 39개 (sector_rotation.SECTORS)
저장: news_articles 테이블 (article_key 로 중복 방지)
주기: 시장 나침반 계산 시 30분 TTL 자동 수집 + fundamentals_sync(07:00/20:10)

LLM 컨텍스트: 섹터별 24시간/7일/30일 버킷 기사 수 + 최신 헤드라인.
분류(단기/중기/장기 재료)는 LLM 레이어가 헤드라인을 보고 수행 — 수치는 만들지 않는다.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

KST = ZoneInfo("Asia/Seoul")  # 네이버 기사 시각·뉴스 버킷 기준 — 시장(KST)

import httpx

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

_collect_lock = threading.Lock()
_last_collect_ts: float = 0.0
COLLECT_TTL = 1800  # 30분


def _parse_dt(s: str) -> Optional[datetime]:
    """'202606110400' → datetime (네이버 기사 시각은 KST)."""
    try:
        return datetime.strptime(str(s)[:12], "%Y%m%d%H%M").replace(tzinfo=KST)
    except Exception:
        return None


def fetch_stock_news(code: str, pages: int = 1, page_size: int = 20) -> list[dict]:
    """종목 뉴스 기사 목록 (네이버 응답을 평탄화)."""
    out: list[dict] = []
    for page in range(1, pages + 1):
        try:
            r = httpx.get(
                f"https://m.stock.naver.com/api/news/stock/{code}",
                params={"pageSize": page_size, "page": page},
                headers=HEADERS, timeout=8.0,
            )
            r.raise_for_status()
            groups = r.json()
            if not isinstance(groups, list) or not groups:
                break
            for g in groups:
                for it in g.get("items", []):
                    key = f"{it.get('officeId','')}{it.get('articleId','')}"
                    dt = _parse_dt(it.get("datetime", ""))
                    if not key or dt is None:
                        continue
                    out.append({
                        "article_key": key,
                        "stock_code": code,
                        "title": str(it.get("title") or "")[:300],
                        "summary": str(it.get("body") or "")[:1000] or None,
                        "press": str(it.get("officeName") or "")[:80] or None,
                        "url": str(it.get("mobileNewsUrl") or "")[:400] or None,
                        "published_at": dt,
                    })
        except Exception:
            break
    return out


def collect(pages: int = 1, force: bool = False) -> dict:
    """나침반 대표종목 전체 뉴스 수집 → DB upsert. {fetched, inserted} 반환."""
    global _last_collect_ts
    with _collect_lock:
        if not force and (time.time() - _last_collect_ts) < COLLECT_TTL:
            return {"fetched": 0, "inserted": 0, "skipped": "ttl"}
        _last_collect_ts = time.time()

    import db
    import models
    import sector_rotation
    from sqlalchemy import select

    code_sector = {
        code: sector
        for sector, codes in sector_rotation.SECTORS.items()
        for code in codes
    }

    models.Base.metadata.create_all(db.get_engine(), tables=[models.NewsArticle.__table__])

    # 거래 제외 종목은 뉴스 수집/저장 대상에서 제외 (전역 제외 원칙)
    try:
        import exclusion_engine

        _s = db.get_session_factory()()
        try:
            _excluded = set(exclusion_engine.get_exclusions(_s))
        finally:
            _s.close()
        code_sector = {c: s for c, s in code_sector.items() if c not in _excluded}
    except Exception:
        pass

    fetched: list[dict] = []
    for code, sector in code_sector.items():
        for row in fetch_stock_news(code, pages=pages):
            row["sector"] = sector
            fetched.append(row)
        time.sleep(0.05)

    inserted = 0
    session = db.get_session_factory()()
    try:
        existing = {
            k for k in session.execute(select(models.NewsArticle.article_key)).scalars().all()
        }
        seen_now: set[str] = set()
        for row in fetched:
            k = row["article_key"]
            if k in existing or k in seen_now:
                continue
            seen_now.add(k)
            session.add(models.NewsArticle(**row))
            inserted += 1
        session.commit()
    finally:
        session.close()
    return {"fetched": len(fetched), "inserted": inserted}


def get_news_context(max_headlines_per_sector: int = 5) -> dict:
    """LLM 컨텍스트용 뉴스 요약: 섹터별 24시간/7일/30일 버킷 + 최신 헤드라인."""
    import db
    import models
    from sqlalchemy import select

    now = datetime.now(KST)
    d1, d7, d30 = now - timedelta(days=1), now - timedelta(days=7), now - timedelta(days=30)

    session = db.get_session_factory()()
    try:
        rows = session.execute(
            select(
                models.NewsArticle.sector,
                models.NewsArticle.title,
                models.NewsArticle.press,
                models.NewsArticle.published_at,
            )
            .where(models.NewsArticle.published_at >= d30)
            .order_by(models.NewsArticle.published_at.desc())
        ).all()
    finally:
        session.close()

    sectors: dict[str, dict] = {}
    for sector, title, press, pub in rows:
        s = sectors.setdefault(sector or "기타", {
            "count24h": 0, "count7d": 0, "count30d": 0, "headlines": [],
        })
        s["count30d"] += 1
        if pub >= d7:
            s["count7d"] += 1
        if pub >= d1:
            s["count24h"] += 1
        if len(s["headlines"]) < max_headlines_per_sector:
            s["headlines"].append({
                "title": title,
                "press": press,
                "at": pub.strftime("%m-%d %H:%M"),
            })

    return {
        "asOf": now.strftime("%Y-%m-%d %H:%M"),
        "totalArticles30d": len(rows),
        "sectors": sectors,
    }
