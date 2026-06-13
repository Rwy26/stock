"""ETF 재저장 — etfHoldings를 캐시에 주입 (AI 생략, 빠름) 후 그래프 재생성."""
import sys, os
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
os.environ['KRX_ID'] = os.getenv('KRX_ID', '')
os.environ['KRX_PW'] = os.getenv('KRX_PW', '')

import stock_compass

ETFS = ['069500', '471990', '487240', '0080G0', '305720', '445290', '0098F0', '117700']
for i, code in enumerate(ETFS):
    try:
        r = stock_compass.analyze_stock(code, with_ai=False)
        print(f'[{i+1}/{len(ETFS)}] {code} OK holdings={len(r.get("etfHoldings", []))}', flush=True)
    except Exception as e:
        print(f'[{i+1}/{len(ETFS)}] {code} FAIL: {e}', flush=True)

# 캐시 검증
import db, models
from sqlalchemy import select
s = db.get_session_factory()()
saved = 0
for code in ETFS:
    row = s.execute(select(models.AiAnalysisCache).where(models.AiAnalysisCache.stock_code == code)).scalar_one_or_none()
    pj = row.result_json if row and isinstance(row.result_json, dict) else {}
    if pj.get('etfHoldings'):
        saved += 1
s.close()
print(f'캐시에 etfHoldings 저장된 ETF: {saved}/{len(ETFS)}', flush=True)

import graph_engine
g = graph_engine.build_graph(force=True)
etf_nodes = [n for n in g['nodes'] if n.get('isEtf')]
print(f'그래프: 노드={len(g["nodes"])}, 엣지={len(g["edges"])}, isEtf={len(etf_nodes)}', flush=True)
