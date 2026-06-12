"""일회성 배치 분석 실행 스크립트."""
import sys, os, time
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
os.environ['KRX_ID'] = os.getenv('KRX_ID', '')
os.environ['KRX_PW'] = os.getenv('KRX_PW', '')

import db, models
from sqlalchemy import select
import stock_compass

s = db.get_session_factory()()
codes = s.execute(select(models.Watchlist.stock_code).distinct()).scalars().all()
s.close()

print(f'배치 분석 시작: {len(codes)}종목', flush=True)
ok = err = 0
for i, code in enumerate(codes):
    try:
        r = stock_compass.analyze_stock(code, with_ai=True)
        ok += 1
        provider = r.get('aiProvider', '?')
        name = r.get('name', code)
        print(f'[{i+1}/{len(codes)}] {code} {name} OK provider={provider}', flush=True)
    except Exception as e:
        err += 1
        print(f'[{i+1}/{len(codes)}] {code} FAIL: {e}', flush=True)
    time.sleep(90)

print(f'배치 완료: 성공={ok}, 실패={err}', flush=True)
