"""전 종목 최신 규칙 재분석 (닷컴 포지션 연결 + Volume Profile + A/B/C 레벨 등)."""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8')
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

print(f'전 종목 재분석 시작: {len(codes)}종목', flush=True)
ok = err = noai = 0
fails = []
for i, code in enumerate(codes):
    try:
        r = stock_compass.analyze_stock(code, with_ai=True)
        prov = r.get('aiProvider', '?')
        name = r.get('name', code)
        if prov.startswith('none'):
            noai += 1
        ok += 1
        print(f'[{i+1}/{len(codes)}] {code} {name} provider={prov}', flush=True)
    except Exception as e:
        err += 1
        fails.append(code)
        print(f'[{i+1}/{len(codes)}] {code} FAIL: {type(e).__name__}: {str(e)[:80]}', flush=True)
    time.sleep(90)

print(f'배치 완료: 성공={ok} (그중 AI없음={noai}), 실패={err}', flush=True)
if fails:
    print(f'실패 종목: {fails}', flush=True)
