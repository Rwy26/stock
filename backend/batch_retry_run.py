"""AI 해석 실패 종목 재시도."""
import sys, os, time
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
os.environ['KRX_ID'] = os.getenv('KRX_ID', '')
os.environ['KRX_PW'] = os.getenv('KRX_PW', '')

import stock_compass

RETRY = [
    '009830', '195870',  # KIS 타임아웃
    '010060', '022100', '031980', '032820', '048410', '051910',
    '078930', '093320', '095340', '095910', '218410', '237690',
    '322000', '373220',  # provider=none
]

print(f'재시도: {len(RETRY)}종목', flush=True)
ok = err = 0
for i, code in enumerate(RETRY):
    try:
        r = stock_compass.analyze_stock(code, with_ai=True)
        ok += 1
        provider = r.get('aiProvider', '?')
        name = r.get('name', code)
        print(f'[{i+1}/{len(RETRY)}] {code} {name} OK provider={provider}', flush=True)
    except Exception as e:
        err += 1
        print(f'[{i+1}/{len(RETRY)}] {code} FAIL: {e}', flush=True)
    time.sleep(60)

print(f'재시도 완료: 성공={ok}, 실패={err}', flush=True)
