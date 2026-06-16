"""모빌리티 신규 종목 1시간 지연 편입 — DB추가 → 제외게이트 → 관심종목 편입 → LLM 리포트 → 그래프 재생성."""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
os.environ['KRX_ID'] = os.getenv('KRX_ID', '')
os.environ['KRX_PW'] = os.getenv('KRX_PW', '')

PENDING = [
    ('003620', 'KG모빌리티'), ('011210', '현대위아'), ('454910', '두산로보틱스'),
    ('319400', '현대무벡스'), ('457190', '이수스페셜티케미컬'), ('222080', '씨아이에스'),
]

DELAY = 3600
print(f'모빌리티 {len(PENDING)}종목 — {DELAY}초(1시간) 후 편입 시작', flush=True)
time.sleep(DELAY)
print('지연 종료 — 편입 시작', flush=True)

import db, models, stock_compass, exclusion_engine
from sqlalchemy import select

to_analyze = []
for code, name in PENDING:
    try:
        s = db.get_session_factory()()
        try:
            if s.execute(select(models.Stock).where(models.Stock.code == code)).scalar_one_or_none() is None:
                s.add(models.Stock(code=code, name=name))
                s.commit()
            if s.execute(select(models.Watchlist.id).where(
                    models.Watchlist.user_id == 1, models.Watchlist.stock_code == code)).first():
                print(f'{code} {name}: 이미 보유', flush=True); continue
            try:
                exclusion_engine.gate(s, code, name)
            except Exception as ex:
                print(f'{code} {name}: 제외됨 ({ex})', flush=True); continue
            s.add(models.Watchlist(user_id=1, stock_code=code)); s.commit()
            to_analyze.append((code, name))
            print(f'{code} {name}: 편입 완료', flush=True)
        finally:
            s.close()
    except Exception as e:
        print(f'{code} {name}: 편입 실패 {e}', flush=True)

for code, name in to_analyze:
    try:
        r = stock_compass.analyze_stock(code, with_ai=True)
        print(f'{code} {name}: 리포트 생성 provider={r.get("aiProvider")}', flush=True)
    except Exception as e:
        print(f'{code} {name}: 분석 실패 {e}', flush=True)
    time.sleep(60)

try:
    import graph_engine
    g = graph_engine.build_graph(force=True)
    print(f'그래프 재생성: 노드={len(g["nodes"])}', flush=True)
except Exception as e:
    print(f'그래프 재생성 실패 {e}', flush=True)

print(f'모빌리티 지연 편입 완료: {len(to_analyze)}종목', flush=True)
