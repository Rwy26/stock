"""fundamentals_sync.py

매일 07:00 / 20:10 실행 (Windows 작업 스케줄러).

대상: 관심종목(워치리스트) 전체 ∪ AI 분석(ai_analysis_cache) 종목.
동작:
  1. KIS inquire_price 로 주가 + 발행주식수(상장주식수) 수집 → 시총 = 주가 × 발행주식수
  2. 네이버 금융(시총/주가)과 비교 → 1% 초과 차이는 불일치로 로그
  3. 발행주식수 등 기본적 분석 데이터를 D드라이브 캐시에 저장 (KIS 재호출 최소화)
  4. [무결성 검증] DB 종목명 ↔ 네이버 종목명 전수 대조.
     불일치(코드가 다른 회사를 가리킴)나 시세 없음(폐지/오타 코드)은
     logs/name-mismatch-alert.log 에 기록 — 2026-06-10 코드 매핑 오류 13건 재발 방지.
  5. VKOSPI(변동성지수 선물 VKI1!) 최근 일봉을 vkospi_history 테이블에 upsert.

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

                out[c] = {
                    "price": num("closePriceRaw", "closePrice"),
                    "cap": num("marketValueFullRaw"),
                    "name": str(d.get("stockName") or "").strip(),
                }
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


def _db_names(codes: list[str]) -> dict[str, str]:
    s = apollo_db.get_session_factory()()
    try:
        rows = s.execute(
            select(models.Stock.code, models.Stock.name).where(models.Stock.code.in_(codes))
        ).all()
        return {str(c): str(n or "") for c, n in rows}
    finally:
        s.close()


def verify_names(codes: list[str], naver: dict[str, dict], now: datetime) -> list[str]:
    """DB 종목명 ↔ 네이버 종목명 전수 대조. 문제 건 리스트 반환 + 알림 파일 기록.

    돈을 다루는 시스템에서 코드↔이름 불일치는 다른 회사를 매매하는 사고로 이어진다.
    불일치 발견 시 자동 수정하지 않고 알림만 남긴다 — 정정은 사람이 확인 후 수행.
    """
    db_names = _db_names(codes)
    problems: list[str] = []
    for c in codes:
        dbn = db_names.get(c, "")
        nv = naver.get(c)
        if nv is None or not nv.get("name"):
            problems.append(f"NO-QUOTE {c} DB={dbn} — 폐지되었거나 존재하지 않는 코드일 수 있음")
            continue
        nvn = str(nv["name"])
        if dbn.replace(" ", "") != nvn.replace(" ", ""):
            problems.append(f"NAME-MISMATCH {c} DB={dbn} NAVER={nvn} — 코드가 다른 회사를 가리킴")

    if problems:
        alert = Path(__file__).resolve().parents[1] / "logs" / "name-mismatch-alert.log"
        alert.parent.mkdir(parents=True, exist_ok=True)
        with alert.open("a", encoding="utf-8") as f:
            f.write(f"[{now.isoformat(timespec='seconds')}] {len(problems)}건 — 즉시 확인 필요\n")
            for p in problems:
                f.write(f"   {p}\n")
    return problems


def _admin_profile():
    s = apollo_db.get_session_factory()()
    try:
        return s.execute(select(models.KisProfile).where(models.KisProfile.user_id == 1)).scalar_one_or_none()
    finally:
        s.close()


def _sync_global_macro(now: datetime) -> str:
    """글로벌 매크로 점수 산출 → MacroSentimentDaily / PredictionMarketDaily upsert (스펙 §5).

    결정론 점수 엔진만 호출(LLM 없음). 두 테이블은 create_all 로 보장하고 trade_date upsert.
    반환: 로그용 요약 문자열.
    """
    import global_macro

    g = global_macro.compute_global_macro(force=True)
    scores = g.get("scores", {})
    pred = (g.get("inputs", {}) or {}).get("prediction", {}) or {}
    trade_date = now.date()

    models.Base.metadata.create_all(
        apollo_db.get_engine(),
        tables=[models.MacroSentimentDaily.__table__, models.PredictionMarketDaily.__table__],
    )

    session = apollo_db.get_session_factory()()
    try:
        row = session.get(models.MacroSentimentDaily, trade_date)
        if row is None:
            row = models.MacroSentimentDaily(trade_date=trade_date)
            session.add(row)
        for k in ("liquidity", "growth", "inflation", "ai_cycle", "geopolitics",
                  "risk_appetite", "us_equity", "kr_equity"):
            setattr(row, k, scores.get(k))
        row.composite = g.get("composite")
        row.flow = g.get("flow")
        row.prob_json = g.get("probabilities")
        row.inputs_json = {
            "evidence": g.get("evidence"),
            "kr_sectors": g.get("kr_sectors"),
            "market": (g.get("inputs", {}) or {}).get("market"),
            "econ": (g.get("inputs", {}) or {}).get("econ"),
            "news": (g.get("inputs", {}) or {}).get("news"),
        }

        n_pred = 0
        for key, p in pred.items():
            existing = session.execute(
                select(models.PredictionMarketDaily).where(
                    models.PredictionMarketDaily.trade_date == trade_date,
                    models.PredictionMarketDaily.target_key == key,
                )
            ).scalar_one_or_none()
            if existing is None:
                existing = models.PredictionMarketDaily(trade_date=trade_date, target_key=key)
                session.add(existing)
            existing.polymarket = p.get("polymarket")
            existing.kalshi = p.get("kalshi")
            existing.metaculus = p.get("metaculus")
            existing.consensus = p.get("consensus")
            existing.n_sources = p.get("n_sources", 0)
            n_pred += 1
        session.commit()
    finally:
        session.close()

    return f"macro(composite={g.get('composite')} {g.get('flow')} pred={n_pred} method={g.get('probabilities', {}).get('method')})"


def main() -> int:
    now = datetime.now()
    codes = _target_codes()
    prof = _admin_profile()
    app_key = getattr(prof, "app_key", None)
    app_secret = getattr(prof, "app_secret", None)
    is_paper = bool(getattr(prof, "is_paper", False))

    naver = _naver_quotes(codes)
    name_problems = verify_names(codes, naver, now)

    # VKOSPI 최근 일봉 동기화 (실패해도 본 동기화는 계속)
    vkospi_note = ""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import vkospi_crawl
        ins, upd = vkospi_crawl.sync_recent(days=10)
        vkospi_note = f" vkospi(+{ins}/~{upd})"
    except Exception as exc:  # noqa: BLE001
        vkospi_note = f" vkospi(FAIL {type(exc).__name__})"

    # 뉴스 수집 (시장 나침반 6단계 데이터 — 실패해도 본 동기화는 계속)
    try:
        import news_collector
        nres = news_collector.collect(pages=2, force=True)
        vkospi_note += f" news(+{nres.get('inserted', 0)})"
    except Exception as exc:  # noqa: BLE001
        vkospi_note += f" news(FAIL {type(exc).__name__})"

    # 글로벌 매크로 투자심리 지수 (스펙 §5 — 06:00 체인 합류, 실패해도 본 동기화는 계속)
    try:
        vkospi_note += " " + _sync_global_macro(now)
    except Exception as exc:  # noqa: BLE001
        vkospi_note += f" macro(FAIL {type(exc).__name__})"

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
    header = (
        f"[{now.isoformat(timespec='seconds')}] synced={len(codes)} "
        f"mismatches(>{MISMATCH_PCT}%)={len(mismatches)} name_problems={len(name_problems)}{vkospi_note}"
    )
    try:
        with logf.open("a", encoding="utf-8") as f:
            f.write(header + "\n")
            for r in mismatches:
                f.write(
                    f"   MISMATCH {r['code']} kis_cap={r['kis_cap']:.0f} naver_cap={r['naver_cap']:.0f} diff={r['diff_pct']}%\n"
                )
            for p in name_problems:
                f.write(f"   {p}\n")
    except Exception:
        pass

    print(header)
    for r in mismatches[:20]:
        print(f"  MISMATCH {r['code']} diff={r['diff_pct']}%")
    for p in name_problems:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
