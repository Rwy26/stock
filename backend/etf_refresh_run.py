"""ETF 재분석 — etfHoldings 캐시 주입 후 그래프 재생성."""
import sys, os, time
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
os.environ['KRX_ID'] = os.getenv('KRX_ID', '')
os.environ['KRX_PW'] = os.getenv('KRX_PW', '')

import stock_compass

ETFS = ['069500', '471990', '487240', '0080G0', '305720', '445290', '0098F0', '117700']

ok = err = 0
for i, code in enumerate(ETFS):
    try:
        r = stock_compass.analyze_stock(code, with_ai=True)
        n_hold = len(r.get('etfHoldings', []))
        ok += 1
        print(f'[{i+1}/{len(ETFS)}] {code} OK holdings={n_hold} provider={r.get("aiProvider")}', flush=True)
    except Exception as e:
        err += 1
        print(f'[{i+1}/{len(ETFS)}] {code} FAIL: {e}', flush=True)
    time.sleep(60)

print(f'ETF 재분석 완료: 성공={ok}, 실패={err}', flush=True)

import graph_engine
g = graph_engine.build_graph(force=True)
print(f'그래프 재생성: 노드={len(g["nodes"])}, 엣지={len(g["edges"])}', flush=True)
