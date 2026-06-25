import json, urllib.request, urllib.error, time
BASE='http://127.0.0.1:8000'
r=urllib.request.urlopen(urllib.request.Request(BASE+'/api/auth/login',data=json.dumps({'email':'administrator','password':'ChangeMe!'}).encode(),headers={'Content-Type':'application/json'}),timeout=10)
tok=json.loads(r.read()).get('accessToken')
print(f'[{time.strftime("%H:%M:%S")}] login OK')
# 전 종목 경량(무거운 국제 fetch 끔 — 500 회피). 기술점수+캐시 펀더멘털로 IndicatorScore 갱신
req=urllib.request.Request(BASE+'/api/admin/scoring/run',data=json.dumps({'fetch_supply_demand':False,'prefetch_fundamentals':False}).encode(),headers={'Content-Type':'application/json','Authorization':f'Bearer {tok}'})
t0=time.time()
try:
    r=urllib.request.urlopen(req,timeout=1800)
    d=json.loads(r.read())
    print(f'[{time.strftime("%H:%M:%S")}] 완료 ({time.time()-t0:.0f}s): scored={d.get("total_scored")} upserted={d.get("upserted")}')
except urllib.error.HTTPError as e:
    print(f'[{time.strftime("%H:%M:%S")}] HTTP {e.code}: {e.read().decode()[:300]}')
except Exception as e:
    print(f'[{time.strftime("%H:%M:%S")}] {type(e).__name__}: {str(e)[:150]}')
