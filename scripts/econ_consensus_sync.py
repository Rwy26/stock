"""econ_consensus_sync.py — 경제지표 시장 예상치(consensus) 자동 갱신.

소스: ForexFactory 공개 캘린더 JSON (nfs.faireconomy.media, 무인증·무료).
  실측(2026-06-13): Investing.com/TradingEconomics/MarketWatch 는 봇 차단(403/401),
  ForexFactory faireconomy 피드만 200 OK. forecast(컨센서스)+previous+actual 제공.

동작: 최근 3주(지난주/이번주/다음주) 이벤트를 받아 USD 지표 중 우리 FRED 키와 매칭되는
  forecast 를 backend/macro_consensus.json 에 upsert. 매칭 안 되는 항목은 건드리지 않음
  (no-consensus 유지 — 데이터 정확성: 추정 금지). 실패 시 파일 변경 없이 로그만.

매칭(FRED 시리즈 ↔ ForexFactory 제목):
  cpi_yoy   ← "CPI y/y"          core_cpi ← "Core CPI y/y"
  ppi_yoy   ← "PPI y/y"          unemployment ← "Unemployment Rate"
  gdp_qoq   ← "...GDP q/q"(연율)  ism_mfg  ← "ISM Manufacturing PMI"
  (FF 가 PPI 를 m/m 로만 줄 경우 ppi_yoy 는 단위 불일치라 건너뜀)

호출: scripts/fundamentals_sync.py (06:00 체인) → sync_consensus(). 단독 실행도 가능.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

# Windows 콘솔(cp949)에서 유니코드 출력 깨짐 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CONSENSUS_PATH = Path(__file__).resolve().parents[1] / "backend" / "macro_consensus.json"
_FEEDS = [
    "https://nfs.faireconomy.media/ff_calendar_lastweek.json",
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"}

# (우리 키, 단위, 매칭 술어). title 은 소문자 비교. core/ m/m 오매칭 방지 위해 술어로 정밀화.
_MATCHERS = [
    ("core_cpi",     "% YoY",        lambda t: t == "core cpi y/y"),
    ("cpi_yoy",      "% YoY",        lambda t: t == "cpi y/y"),
    ("ppi_yoy",      "% YoY",        lambda t: t == "ppi y/y"),  # FF 가 m/m 만 주면 매칭 안 됨
    ("unemployment", "%",            lambda t: t == "unemployment rate"),
    ("gdp_qoq",      "% annualized", lambda t: t.endswith("gdp q/q")),  # advance/prelim/final 포함
    ("ism_mfg",      "index",        lambda t: t == "ism manufacturing pmi"),
]


def _parse_num(s: str):
    m = re.search(r"-?\d+(?:\.\d+)?", str(s or ""))
    return float(m.group(0)) if m else None


def _event_dt(ev: dict):
    raw = str(ev.get("date") or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _fetch_one(url: str) -> list[dict]:
    """단일 피드 — 429(rate-limit) 시 백오프 1회 재시도. 비JSON/실패 시 []."""
    for attempt in (1, 2):
        try:
            r = httpx.get(url, headers={**_UA, "Accept": "application/json,*/*"},
                          timeout=15.0, follow_redirects=True)
            if r.status_code == 429 and attempt == 1:
                time.sleep(8)
                continue
            r.raise_for_status()
            if "json" not in (r.headers.get("content-type") or "").lower():
                return []
            data = r.json()
            return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


def _fetch_events() -> list[dict]:
    events: list[dict] = []
    for i, url in enumerate(_FEEDS):
        if i:
            time.sleep(1.5)   # 피드 간 간격 — rate-limit 회피
        events.extend(_fetch_one(url))
    return events


def sync_consensus() -> dict:
    """ForexFactory 피드 → macro_consensus.json upsert. {updated, matched, source} 반환."""
    events = _fetch_events()
    if not events:
        return {"updated": [], "matched": 0, "note": "feed unavailable — file unchanged"}

    # USD 지표만, 키별로 forecast 있는 최신 이벤트 선택
    best: dict[str, dict] = {}
    for ev in events:
        if str(ev.get("country") or "").upper() != "USD":
            continue
        fc = str(ev.get("forecast") or "").strip()
        if not fc:
            continue
        title = str(ev.get("title") or "").strip().lower()
        for key, unit, pred in _MATCHERS:
            if not pred(title):
                continue
            val = _parse_num(fc)
            if val is None:
                continue
            dt = _event_dt(ev)
            prev = best.get(key)
            if prev is None or (dt and prev["dt"] and dt > prev["dt"]) or (dt and not prev["dt"]):
                best[key] = {"value": val, "unit": unit, "title": ev.get("title"),
                             "date": ev.get("date"), "dt": dt}
            break

    # 기존 파일 로드 후 매칭분만 갱신
    try:
        doc = json.loads(CONSENSUS_PATH.read_text(encoding="utf-8")) if CONSENSUS_PATH.exists() else {}
    except Exception:
        doc = {}

    today = datetime.now().date().isoformat()
    updated = []
    for key, info in best.items():
        doc[key] = {
            "consensus": info["value"],
            "unit": info["unit"],
            "note": f"ForexFactory {info['title']} ({str(info['date'])[:10]})",
            "source": "forexfactory",
            "updated": today,
        }
        updated.append(f"{key}={info['value']}")
    doc["_updated"] = today
    doc.setdefault("_doc", "경제지표 시장 예상치(consensus). ForexFactory 피드 자동 갱신 + 수동 보정 가능. surprise = sign(actual - consensus).")

    if updated:
        CONSENSUS_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {"updated": updated, "matched": len(updated), "source": "forexfactory"}


def main() -> int:
    res = sync_consensus()
    print(f"[econ_consensus_sync] matched={res['matched']} {res.get('note', '')}")
    for u in res.get("updated", []):
        print(f"  {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
