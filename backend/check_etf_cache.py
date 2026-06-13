import sys
sys.path.insert(0, '.')
import db, models
from sqlalchemy import select

s = db.get_session_factory()()
ETFS = ['069500', '471990', '487240', '0080G0', '305720', '445290', '0098F0', '117700']
for code in ETFS:
    r = s.execute(select(models.AiAnalysisCache).where(models.AiAnalysisCache.stock_code == code)).scalar_one_or_none()
    if not r:
        print(f'{code}: 캐시 없음')
        continue
    pj = r.result_json if isinstance(r.result_json, dict) else {}
    eh = pj.get('etfHoldings')
    if eh:
        print(f'{code}: etfHoldings={len(eh)}개, 샘플={eh[0]}')
    else:
        print(f'{code}: etfHoldings 키 없음. 최상위 키들={list(pj.keys())[:15]}')
s.close()
