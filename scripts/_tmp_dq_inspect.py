"""daily_prices / stocks 데이터 품질 일회성 진단 (읽기 전용)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import text
from db import get_session_factory

db = get_session_factory()()

print("== 전체 최신 trading_date ==")
print(db.execute(text("SELECT MAX(trading_date), COUNT(*) FROM daily_prices")).one())

print("\n== 종목별 최신일 분포 (최신일, 종목수) ==")
for r in db.execute(text("""
    SELECT last_dt, COUNT(*) FROM (
      SELECT stock_code, MAX(trading_date) AS last_dt FROM daily_prices GROUP BY stock_code
    ) t GROUP BY last_dt ORDER BY last_dt DESC LIMIT 15""")).all():
    print(" ", r[0], r[1])

print("\n== 의심 종목 상세 ==")
for code in ["011810", "182400", "288490", "111870", "064350", "099320", "290650", "281740"]:
    name = db.execute(text("SELECT name, market FROM stocks WHERE code=:c"), {"c": code}).one_or_none()
    agg = db.execute(text("""
        SELECT MIN(trading_date), MAX(trading_date), COUNT(*),
               SUM(volume=0) FROM daily_prices WHERE stock_code=:c"""), {"c": code}).one()
    last5 = db.execute(text("""
        SELECT trading_date, close_price, volume FROM daily_prices
        WHERE stock_code=:c ORDER BY trading_date DESC LIMIT 5"""), {"c": code}).all()
    print(f"  {code} stocks={name} range={agg[0]}~{agg[1]} rows={agg[2]} vol0={agg[3]}")
    for l in last5:
        print(f"      {l[0]} close={l[1]} vol={l[2]}")

print("\n== volume=0 & 플랫(OHLC 동일) 행 통계 ==")
print(db.execute(text("""
    SELECT COUNT(*), COUNT(DISTINCT stock_code) FROM daily_prices
    WHERE volume=0 AND open_price=close_price AND high_price=close_price AND low_price=close_price""")).one())

print("\n== volume=0 (전체) ==")
print(db.execute(text("SELECT COUNT(*), COUNT(DISTINCT stock_code) FROM daily_prices WHERE volume=0")).one())

print("\n== stocks 전체 행수 / excluded_stocks ==")
print(db.execute(text("SELECT COUNT(*) FROM stocks")).one())
try:
    print(db.execute(text("SELECT COUNT(*) FROM excluded_stocks")).one())
except Exception as e:
    print("excluded_stocks:", e)

db.close()
