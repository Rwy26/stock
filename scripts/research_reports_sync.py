"""research_reports_sync.py — 증권사 종목분석 리포트 다이렉트 수집 (kr_research_reports).

1차 출처 = 네이버 금융 종목분석 리포트(네이버 교차검증 제1원칙). moneyland 등 2차 출처는
오염 위험이라 쓰지 않는다(감사 세션 결론).
  리스트:  finance.naver.com/research/company_list.naver?searchType=itemCode&itemCode=<code>
  상세:    finance.naver.com/research/company_read.naver?nid=<nid>

흐름(종목별):
  1) 네이버 실시간 API로 종목명·현재가 확인(코드-이름 검증 + 목표가 sanity 기준가).
  2) 리스트 페이지에서 최근 리포트 행(종목명/증권사/제목/작성일/nid/PDF) 파싱.
  3) DB 에 이미 있는 (code,firm,date,title) 은 상세 재조회 생략(증분·예의).
  4) 신규 행만 상세 페이지에서 목표가·투자의견·요약 파싱 → UPSERT.
목표가는 KRW 정수, 무데이터는 NULL(N/A). 현재가 대비 비정상 배수면 경고 로그(저장은 유지 — 리포트는 실데이터).

실행:   backend/.venv/Scripts/python.exe scripts/research_reports_sync.py [--codes 005930,000660] [--pages 1] [--max-new 20]
스케줄: MOON-STOCK-Research-Reports-Sync (매일 19:00 KST — 장 마감 후)
로그:   logs/research-reports-sync.log
"""

from __future__ import annotations

import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

LOG = REPO / "logs" / "research-reports-sync.log"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

LIST_URL = "https://finance.naver.com/research/company_list.naver"
READ_URL = "https://finance.naver.com/research/company_read.naver"
REALTIME_URL = "https://polling.finance.naver.com/api/realtime/domestic/stock/{code}"

DEFAULT_PAGES = 1            # 종목당 리스트 페이지 수(1페이지 ≈ 최근 30건)
DEFAULT_MAX_NEW = 20         # 종목당 1회 실행에서 상세 조회할 신규 리포트 상한(부하 가드)
REQ_SLEEP = 0.15             # 요청 간 대기(예의)
TP_SANITY_HI = 5.0           # 현재가 대비 목표가 배수 상한 경고
TP_SANITY_LO = 0.2           # 현재가 대비 목표가 배수 하한 경고


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def ensure_tables() -> None:
    import db
    import models
    models.Base.metadata.create_all(db.get_engine(), tables=[models.KrResearchReport.__table__])


def _get(url: str, params: Optional[dict] = None) -> Optional[str]:
    """네이버 EUC-KR 페이지 GET → 디코딩 텍스트. 실패 시 None."""
    try:
        r = httpx.get(url, params=params, headers=HEADERS, timeout=10.0)
        r.raise_for_status()
        r.encoding = "euc-kr"
        return r.text
    except Exception:
        return None


def naver_realtime(code: str) -> Optional[dict]:
    """네이버 실시간 도메스틱 → {name, price}. 코드-이름 검증 + 목표가 sanity 기준가."""
    try:
        r = httpx.get(REALTIME_URL.format(code=code), headers=HEADERS, timeout=10.0)
        datas = r.json().get("datas", [])
        if not datas:
            return None
        d = datas[0]
        name = str(d.get("stockName") or "").strip() or None
        price = None
        raw = str(d.get("closePrice") or "").replace(",", "").strip()
        if raw:
            try:
                price = float(raw)
            except ValueError:
                price = None
        return {"name": name, "price": price}
    except Exception:
        return None


def _parse_date(s: str) -> Optional[date]:
    """'26.06.22' → date(2026,6,22). 실패 시 None."""
    s = s.strip()
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{2})", s)
    if not m:
        return None
    yy, mm, dd = (int(x) for x in m.groups())
    try:
        return date(2000 + yy, mm, dd)
    except ValueError:
        return None


_NID_RE = re.compile(r"nid=(\d+)")


def fetch_report_list(code: str, pages: int = DEFAULT_PAGES) -> list[dict]:
    """종목별 리스트 페이지 → [{stock_name, firm, title, report_date, nid, pdf_url}]. 최신순."""
    out: list[dict] = []
    seen_nid: set[str] = set()
    for page in range(1, pages + 1):
        html = _get(LIST_URL, {"searchType": "itemCode", "itemCode": code, "page": page})
        if not html:
            break
        soup = BeautifulSoup(html, "html.parser")
        tbl = soup.select_one("table.type_1")
        if tbl is None:
            break
        page_rows = 0
        for tr in tbl.select("tr"):
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue
            cells = [td.get_text(strip=True) for td in tds]
            # 컬럼: 종목명 | 제목 | 증권사 | 첨부 | 작성일 | 조회수
            links = [a.get("href", "") for a in tr.find_all("a", href=True)]
            nid_m = next((_NID_RE.search(h) for h in links if "company_read" in h), None)
            if not nid_m:
                continue
            nid = nid_m.group(1)
            if nid in seen_nid:
                continue
            rdate = _parse_date(cells[4]) if len(cells) > 4 else None
            if rdate is None:
                continue
            pdf = next((h for h in links if h.lower().endswith(".pdf")), None)
            seen_nid.add(nid)
            page_rows += 1
            out.append({
                "stock_name": (cells[0] or "").strip() or None,
                "title": (cells[1] or "").strip()[:300],
                "firm": (cells[2] or "").strip()[:40],
                "report_date": rdate,
                "nid": nid,
                "pdf_url": pdf,
            })
        if page_rows == 0:
            break
        time.sleep(REQ_SLEEP)
    return out


# div.view_info_1 텍스트 예: "목표가 480,000 | 투자의견 Buy"
_TP_RE = re.compile(r"목표가\s*([0-9][0-9,]*)")
_RCMD_RE = re.compile(r"투자의견\s*([^|]+)")


def fetch_report_detail(nid: str) -> dict:
    """상세 페이지 → {target_price, recommendation, summary}. 무데이터 필드는 None."""
    out = {"target_price": None, "recommendation": None, "summary": None}
    html = _get(READ_URL, {"nid": nid})
    if not html:
        return out
    soup = BeautifulSoup(html, "html.parser")
    info = soup.select_one("div.view_info_1")
    if info is not None:
        t = info.get_text(" ", strip=True)
        m = _TP_RE.search(t)
        if m:
            try:
                out["target_price"] = int(m.group(1).replace(",", ""))
            except ValueError:
                pass
        m = _RCMD_RE.search(t)
        if m:
            rc = m.group(1).strip()
            # 투자의견 토큰만(뒤에 제목이 붙는 경우 첫 단어 기준)
            rc = rc.split()[0] if rc else ""
            out["recommendation"] = rc[:30] or None
    body = soup.select_one("td.view_cnt")
    if body is not None:
        s = body.get_text(" ", strip=True)
        out["summary"] = s[:1000] or None
    return out


def _universe(codes_arg: Optional[list[str]]) -> list[tuple[str, str | None]]:
    """수집 대상 (code, name). --codes 미지정 시 stocks 마스터 − 거래 제외 종목."""
    import db
    import models
    from sqlalchemy import select

    s = db.get_session_factory()()
    try:
        if codes_arg:
            rows = s.execute(
                select(models.Stock.code, models.Stock.name)
                .where(models.Stock.code.in_(codes_arg))
            ).all()
            found = {c for c, _ in rows}
            # 마스터에 없는 코드도 명시 지정 시 그대로 수집(이름은 네이버에서 확인)
            extra = [(c, None) for c in codes_arg if c not in found]
            uni = [(c, n) for c, n in rows] + extra
        else:
            uni = [(c, n) for c, n in s.execute(
                select(models.Stock.code, models.Stock.name).order_by(models.Stock.code)
            ).all()]
            try:
                import exclusion_engine
                excluded = set(exclusion_engine.get_exclusions(s))
                before = len(uni)
                uni = [(c, n) for c, n in uni if c not in excluded]
                if before != len(uni):
                    log(f"[exclusion] 거래 제외 종목 {before - len(uni)}건 수집 제외")
            except Exception as exc:  # noqa: BLE001
                log(f"WARN: 제외 필터 스킵 — {type(exc).__name__}")
        return uni
    finally:
        s.close()


def sync(codes: Optional[list[str]] = None, pages: int = DEFAULT_PAGES,
         max_new: int = DEFAULT_MAX_NEW) -> dict:
    """종목별 네이버 리포트 수집 → kr_research_reports UPSERT. 통계 dict 반환."""
    import db
    import models
    from sqlalchemy import select

    uni = _universe(codes)
    log(f"수집 대상 {len(uni)}종목 (pages={pages}, max_new/종목={max_new})")

    total_seen = inserted = 0
    name_mismatch = sanity_warn = 0
    for idx, (code, master_name) in enumerate(uni, 1):
        rt = naver_realtime(code)
        # 코드-이름 검증: 네이버가 단일 진실원천. 불일치는 경고만 남기고 네이버 이름 채택.
        verified_name = (rt or {}).get("name") or master_name
        if rt and master_name and rt["name"] and rt["name"].replace(" ", "") != master_name.replace(" ", ""):
            name_mismatch += 1
            log(f"  WARN {code}: stocks='{master_name}' vs 네이버='{rt['name']}' — 네이버 채택")
        cur_price = (rt or {}).get("price")
        time.sleep(REQ_SLEEP)

        rows = fetch_report_list(code, pages=pages)
        total_seen += len(rows)

        s = db.get_session_factory()()
        try:
            existing = {
                (r.firm, r.report_date, r.title)
                for r in s.execute(
                    select(models.KrResearchReport.firm,
                           models.KrResearchReport.report_date,
                           models.KrResearchReport.title)
                    .where(models.KrResearchReport.stock_code == code)
                ).all()
            }
            new_this = 0
            for row in rows:
                key = (row["firm"], row["report_date"], row["title"])
                if key in existing or not row["firm"] or not row["title"]:
                    continue
                if new_this >= max_new:
                    break
                detail = fetch_report_detail(row["nid"])
                time.sleep(REQ_SLEEP)

                tp = detail["target_price"]
                if tp and cur_price and cur_price > 0:
                    ratio = tp / cur_price
                    if ratio > TP_SANITY_HI or ratio < TP_SANITY_LO:
                        sanity_warn += 1
                        log(f"  WARN {code} {row['firm']} {row['report_date']}: 목표가 {tp:,} "
                            f"vs 현재가 {cur_price:,.0f} (×{ratio:.2f} 비정상) — 저장은 유지")

                src = (f"{READ_URL}?nid={row['nid']}")
                s.add(models.KrResearchReport(
                    stock_code=code,
                    stock_name=verified_name,
                    firm=row["firm"],
                    report_date=row["report_date"],
                    title=row["title"],
                    recommendation=detail["recommendation"],
                    target_price=tp,
                    summary=detail["summary"],
                    source_url=row["pdf_url"] or src,
                ))
                existing.add(key)
                new_this += 1
                inserted += 1
            s.commit()
        except Exception as exc:  # noqa: BLE001
            s.rollback()
            log(f"  ERROR {code}: {type(exc).__name__}: {exc}")
        finally:
            s.close()

        if idx % 20 == 0 or idx == len(uni):
            log(f"  진행 {idx}/{len(uni)} — 누적 신규 {inserted}건")

    log(f"=== 완료: 리스트 {total_seen}행 스캔 / 신규 {inserted}건 UPSERT "
        f"(이름불일치 {name_mismatch}, 목표가 경고 {sanity_warn}) ===")
    return {"seen": total_seen, "inserted": inserted,
            "name_mismatch": name_mismatch, "sanity_warn": sanity_warn}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default=None, help="쉼표구분 종목코드(미지정=stocks 마스터 전체)")
    ap.add_argument("--pages", type=int, default=DEFAULT_PAGES, help="종목당 리스트 페이지 수")
    ap.add_argument("--max-new", type=int, default=DEFAULT_MAX_NEW, help="종목당 신규 상세조회 상한")
    cli = ap.parse_args()
    codes = [c.strip() for c in cli.codes.split(",") if c.strip()] if cli.codes else None

    log(f"=== research-reports-sync 시작 (codes={'전체' if not codes else len(codes)}) ===")
    try:
        ensure_tables()
    except Exception as exc:  # noqa: BLE001
        log(f"FATAL: 테이블 생성 실패 — {type(exc).__name__}: {exc}")
        return 1
    try:
        stats = sync(codes=codes, pages=cli.pages, max_new=cli.max_new)
    except Exception as exc:  # noqa: BLE001
        log(f"FATAL: 수집 실패 — {type(exc).__name__}: {exc}")
        return 1
    return 0 if stats["inserted"] >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
