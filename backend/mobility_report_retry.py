"""모빌리티 6종목 AI 리포트 재시도 (직전 LLM 동시 장애로 실패분)."""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
os.environ['KRX_ID'] = os.getenv('KRX_ID', '')
os.environ['KRX_PW'] = os.getenv('KRX_PW', '')

import stock_compass

# LLM 3사 동시 과부하 회복 대기 (30분)
print('LLM 회복 대기 1800초…', flush=True)
time.sleep(1800)

CODES = [
    ('003620', 'KG모빌리티'), ('011210', '현대위아'), ('454910', '두산로보틱스'),
    ('319400', '현대무벡스'), ('457190', '이수스페셜티케미컬'), ('222080', '씨아이에스'),
]
ok = 0
for i, (code, name) in enumerate(CODES):
    try:
        r = stock_compass.analyze_stock(code, with_ai=True)
        prov = r.get('aiProvider', '?')
        if not prov.startswith('none'):
            ok += 1
        print(f'[{i+1}/{len(CODES)}] {code} {name} provider={prov}', flush=True)
    except Exception as e:
        print(f'[{i+1}/{len(CODES)}] {code} {name} FAIL: {e}', flush=True)
    time.sleep(60)

import graph_engine
graph_engine.build_graph(force=True)
print(f'재시도 완료: AI리포트 성공 {ok}/{len(CODES)}', flush=True)
