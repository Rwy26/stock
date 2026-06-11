"""stocks 테이블 142종목 코드-이름 네이버 교차검증 (읽기 전용)."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import httpx
from sqlalchemy import text
from db import get_session_factory

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

def naver_info(code: str):
    """(이름, 현재가, 거래상태) 또는 None."""
    try:
        r = httpx.get(f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}",
                      headers=HEADERS, timeout=10)
        datas = r.json().get("datas", [])
        if not datas:
            return None
        d = datas[0]
        return (str(d.get("stockName") or "").strip(),
                d.get("closePrice"), d.get("tradeStopYn"), d.get("marketStatus"))
    except Exception as e:
        return ("ERR:" + str(e)[:40], None, None, None)

db = get_session_factory()()
rows = db.execute(text("SELECT code, name FROM stocks ORDER BY code")).all()
db.close()

mismatch, missing, ok = [], [], 0
for code, name in rows:
    info = naver_info(code)
    time.sleep(0.15)
    if info is None:
        missing.append((code, name))
        print(f"MISSING  {code} db={name} -> 네이버 조회결과 없음(폐지/무효 코드 가능)")
        continue
    nname = info[0]
    if nname.replace(" ", "") != (name or "").replace(" ", ""):
        mismatch.append((code, name, nname, info[1], info[2]))
        print(f"MISMATCH {code} db={name} naver={nname} price={info[1]} stop={info[2]}")
    else:
        ok += 1

print(f"\n총 {len(rows)}종목: 일치 {ok} / 불일치 {len(mismatch)} / 조회불가 {len(missing)}")
