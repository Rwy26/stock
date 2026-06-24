import json, urllib.request, urllib.error, time
BASE='http://127.0.0.1:8000'
r=urllib.request.urlopen(urllib.request.Request(BASE+'/api/auth/login',data=json.dumps({'email':'administrator','password':'ChangeMe!'}).encode(),headers={'Content-Type':'application/json'}),timeout=10)
d=json.loads(r.read())
tok=d.get('accessToken') or d.get('access_token')
print(f'[{time.strftime("%H:%M:%S")}] login OK role={d.get("role")} tok={"yes" if tok else "NO"}')
req=urllib.request.Request(BASE+'/api/admin/scoring/run',data=json.dumps({}).encode(),headers={'Content-Type':'application/json','Authorization':f'Bearer {tok}'})
t0=time.time()
try:
    r=urllib.request.urlopen(req,timeout=3600)
    d=json.loads(r.read())
    print(f'[{time.strftime("%H:%M:%S")}] scoring 완료 ({time.time()-t0:.0f}s): upserted={d.get("upserted")}')
except urllib.error.HTTPError as e:
    print(f'[{time.strftime("%H:%M:%S")}] HTTP {e.code}: {e.read().decode()[:150]}')
except Exception as e:
    print(f'[{time.strftime("%H:%M:%S")}] {type(e).__name__}: {str(e)[:120]}')
