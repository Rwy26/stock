"""VKOSPI(변동성지수) 과거 일봉 크롤러.

소스: TradingView 차트 웹소켓 — KRX 변동성지수 선물 연속물(KRX:VKI1!).
  - 현물 VKOSPI는 야후/네이버/다음 미제공, KRX 정보데이터시스템은 이 네트워크에서 DNS 불가.
  - 선물 연속물이므로 현물과 약간의 베이시스가 있음 (source 컬럼에 'VKI1!' 명시).

동작: 일봉 최대 5000개 요청 → vkospi_history 테이블 upsert.
재실행 안전 (이미 있는 날짜는 갱신).

사용법:
  cd c:\stock\backend
  .\.venv\Scripts\python.exe ..\scripts\vkospi_crawl.py
"""

from __future__ import annotations

import json
import random
import re
import string
import sys
from datetime import datetime, date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from websocket import create_connection  # noqa: E402

SYMBOL = "KRX:VKI1!"
BARS = 5000
WS_URL = "wss://data.tradingview.com/socket.io/websocket?from=chart%2F&type=chart"
ORIGIN = "https://www.tradingview.com"


def _msg(func: str, args: list) -> str:
    payload = json.dumps({"m": func, "p": args}, separators=(",", ":"))
    return f"~m~{len(payload)}~m~{payload}"


def _session(prefix: str) -> str:
    return prefix + "_" + "".join(random.choices(string.ascii_lowercase, k=12))


def fetch_bars() -> list[tuple[date, float, float, float, float]]:
    """TradingView 웹소켓에서 (날짜, 시, 고, 저, 종) 일봉 리스트 수신."""
    ws = create_connection(WS_URL, origin=ORIGIN, timeout=30,
                           header={"User-Agent": "Mozilla/5.0"})
    chart = _session("cs")
    try:
        ws.send(_msg("set_auth_token", ["unauthorized_user_token"]))
        ws.send(_msg("chart_create_session", [chart, ""]))
        ws.send(_msg("resolve_symbol", [chart, "sds_sym_1",
                                        f'={{"symbol":"{SYMBOL}","adjustment":"splits"}}']))
        ws.send(_msg("create_series", [chart, "sds_1", "s1", "sds_sym_1", "1D", BARS, ""]))

        bars: list = []
        for _ in range(200):  # 메시지 수신 루프 (충분히 큰 상한)
            try:
                raw = ws.recv()
            except Exception:
                break
            if not raw:
                break
            # 핑 응답
            for ping in re.findall(r"~m~\d+~m~(~h~\d+)", raw):
                ws.send(f"~m~{len(ping)}~m~{ping}")
            # 시리즈 데이터 추출
            for part in re.split(r"~m~\d+~m~", raw):
                if not part or part.startswith("~h~"):
                    continue
                try:
                    obj = json.loads(part)
                except Exception:
                    continue
                m = obj.get("m")
                if m in ("timescale_update", "du"):
                    series = obj.get("p", [None, {}])[1].get("sds_1", {})
                    for item in series.get("s", []):
                        v = item.get("v", [])
                        if len(v) >= 5:
                            bars.append(v)
                elif m == "series_completed":
                    out = []
                    for v in bars:
                        d = datetime.fromtimestamp(v[0]).date()
                        out.append((d, float(v[1]), float(v[2]), float(v[3]), float(v[4])))
                    return out
                elif m in ("symbol_error", "series_error", "critical_error", "protocol_error"):
                    raise RuntimeError(f"TradingView error: {part[:200]}")
        raise RuntimeError("series_completed 수신 실패 (타임아웃)")
    finally:
        ws.close()


def upsert(rows: list[tuple[date, float, float, float, float]]) -> tuple[int, int]:
    """(날짜, OHLC) 리스트를 vkospi_history 에 upsert. (신규, 갱신) 건수 반환."""
    import db
    import models
    from sqlalchemy import select

    models.Base.metadata.create_all(db.get_engine(), tables=[models.VkospiHistory.__table__])

    session = db.get_session_factory()()
    try:
        existing = {
            r for r in session.execute(select(models.VkospiHistory.trade_date)).scalars().all()
        }
        ins = upd = 0
        for d, o, h, lo, c in rows:
            if d in existing:
                row = session.execute(
                    select(models.VkospiHistory).where(models.VkospiHistory.trade_date == d)
                ).scalar_one()
                row.open, row.high, row.low, row.close = o, h, lo, c
                upd += 1
            else:
                session.add(models.VkospiHistory(
                    trade_date=d, open=o, high=h, low=lo, close=c, source="VKI1!",
                ))
                ins += 1
        session.commit()
        return ins, upd
    finally:
        session.close()


def sync_recent(days: int = 10) -> tuple[int, int]:
    """최근 N개 일봉만 받아 upsert — fundamentals_sync 일일 갱신용."""
    global BARS
    old = BARS
    BARS = days
    try:
        rows = fetch_bars()
    finally:
        BARS = old
    return upsert(rows) if rows else (0, 0)


def main() -> int:
    print(f"[vkospi] {SYMBOL} 일봉 {BARS}개 요청...")
    rows = fetch_bars()
    print(f"[vkospi] 수신: {len(rows)}개 ({rows[0][0]} ~ {rows[-1][0]})" if rows else "[vkospi] 수신 0개")
    if not rows:
        return 1
    ins, upd = upsert(rows)
    print(f"[vkospi] DB 적재 완료: 신규 {ins}, 갱신 {upd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
