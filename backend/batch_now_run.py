"""전 종목 즉시 재분석 (사용자 강행 — 장중 가드 없음). 최신 10섹터 분류·모빌리티 통합 반영."""
import sys
import os
import time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
os.environ['KRX_ID'] = os.getenv('KRX_ID', '')
os.environ['KRX_PW'] = os.getenv('KRX_PW', '')

import db
import models
from sqlalchemy import select
import stock_compass

s = db.get_session_factory()()
codes = s.execute(select(models.Watchlist.stock_code).distinct()).scalars().all()
s.close()

print(f'전 종목 즉시 재분석: {len(codes)}종목', flush=True)
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
        print(f'[{i+1}/{len(codes)}] {code} FAIL: {type(e).__name__}: {str(e)[:70]}', flush=True)
    time.sleep(90)

try:
    import graph_engine
    graph_engine.build_graph(force=True)
except Exception:
    pass

print(f'재분석 완료: 성공={ok} (AI없음={noai}), 실패={err}', flush=True)
if fails:
    print(f'실패: {fails}', flush=True)
