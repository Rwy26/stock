"""교체 후보 신규 코드 네이버 검증 + stocks 참조 테이블 확인 (읽기 전용)."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import httpx
from sqlalchemy import text
from db import get_session_factory

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

CANDIDATES = [
    ("064350", "현대로템"), ("131970", "두산테스나"), ("043100", "성호전자"),
    ("064760", "티씨케이"), ("010120", "LS ELECTRIC"), ("099320", "쎄트렉아이"),
]
for code, intended in CANDIDATES:
    r = httpx.get(f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}",
                  headers=HEADERS, timeout=10)
    datas = r.json().get("datas", [])
    name = str(datas[0].get("stockName") or "").strip() if datas else None
    price = datas[0].get("closePrice") if datas else None
    print(f"{code} intended={intended} naver={name} price={price}")
    time.sleep(0.2)

print("\n== stocks.code 를 참조하는 테이블/행수 ==")
db = get_session_factory()()
fks = db.execute(text("""
    SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE
    WHERE REFERENCED_TABLE_SCHEMA='apollo_db' AND REFERENCED_TABLE_NAME='stocks'""")).all()
print("FKs:", fks)
DEAD = ["036490", "111870", "288490", "314760", "384490", "477010"]
SWAP_OLD = ["011810", "033160", "040610", "104480", "267260"]
for tbl, col in fks:
    for code in DEAD + SWAP_OLD:
        n = db.execute(text(f"SELECT COUNT(*) FROM {tbl} WHERE {col}=:c"), {"c": code}).scalar()
        if n:
            print(f"  {tbl}.{col} {code}: {n}행")
db.close()
