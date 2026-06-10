# 임시 (완료 후 삭제): 한화에어로스페이스 분석 → AI 이력 저장
import time

time.sleep(65)  # KIS 토큰 발급 1분 제한

import stock_compass  # noqa: E402

r = stock_compass.analyze_stock("012450", with_ai=True)
print("분석 완료:", r["stock"]["name"], "| 점수", r["composite"]["score"], "| LLM", r["aiProvider"])

# 저장 확인
import db  # noqa: E402
import models  # noqa: E402
from sqlalchemy import select  # noqa: E402

s = db.get_session_factory()()
row = s.execute(
    select(models.AiAnalysisCache).where(models.AiAnalysisCache.stock_code == "012450")
).scalar_one_or_none()
s.close()
if row:
    print(f"이력 저장 확인: {row.stock_name} | signal={row.signal} | confidence={row.confidence} "
          f"| upside={row.upside_probability}% | analyzed_at={row.analyzed_at}")
    print("result_json keys:", list((row.result_json or {}).keys()))
else:
    print("저장 실패!")
