# 임시 (완료 후 삭제): 결과 시연용
import time

time.sleep(65)  # KIS 토큰 발급 1분 제한

import stock_compass  # noqa: E402

r = stock_compass.analyze_stock("012450", with_ai=True)
st, comp = r["stock"], r["composite"]
print(f"{'='*60}")
print(f" {st['name']} ({st['code']}) — {r['asOf']}")
print(f" 섹터: {st['sector']} (나침반 {st['sectorRank']}위 {st['sectorScore']}점) | 현재가 {st['currentPrice']:,.0f}")
print(f" 종합: {comp['score']}점 / 등급 {comp['grade']} / 손익비 {comp['riskReward']}")
print(f" 구성: {comp['parts']}")
print(f"{'='*60}")
print()
print("[목표가]", {k: v.get("price") for k, v in r["targets"]["list"].items()},
      "→ 평균", r["targets"]["avgTarget"], f"(+{r['targets']['avgTargetUpside']}%)")
print("[손절가]", {k: v.get("price") for k, v in r["stops"].items()})
p = r["probability"]
print(f"[확률] 상승지속 {p.get('continueUpPct')}% / 목표도달 {p.get('reachTargetPct')}% / "
      f"손절이탈 {p.get('hitStopPct')}% (표본 {p.get('sample')}건)")
print()
print(f"--- AI 리포트 ({r['aiProvider']}) ---")
print(r["aiReport"] or "(없음)")
