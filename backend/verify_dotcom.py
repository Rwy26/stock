import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
os.environ['KRX_ID'] = os.getenv('KRX_ID', '')
os.environ['KRX_PW'] = os.getenv('KRX_PW', '')

import stock_compass
r = stock_compass.analyze_stock('012450', with_ai=True)
ai = r.get('aiReport', '')
print('provider:', r.get('aiProvider'))
print('dotcomCasebook in result:', 'dotcomCasebook' in r)
idx = ai.find('닷컴')
if idx >= 0:
    end = ai.find('# 종목 평가', idx)
    print(ai[idx-10:end if end > 0 else idx+800])
