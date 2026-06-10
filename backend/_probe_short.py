# 임시 (완료 후 삭제): 공매도·대차 데이터 소스 탐색
import time

import httpx
import db
import models
import kis_client
from settings import settings
from sqlalchemy import select

# ── 1) KRX 공매도종합포털 (인증 불필요 추정) ──
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://short.krx.co.kr/"}
try:
    r = httpx.post(
        "https://short.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
        data={
            "bld": "srt/02/02010100/srt02010100",
            "locale": "ko_KR",
            "isuCd": "KR7005930003",  # 삼성전자 ISIN
            "strtDd": "20260601",
            "endDd": "20260610",
        },
        headers=H, timeout=12,
    )
    print("KRX 공매도포털:", r.status_code, r.text[:200].replace("\n", ""))
except Exception as e:
    print("KRX 공매도포털 ERR:", str(e)[:120])

# ── 2) KIS 공매도 일별추이 TR ──
time.sleep(65)
s = db.get_session_factory()()
prof = s.execute(select(models.KisProfile).where(models.KisProfile.user_id == 1)).scalar_one_or_none()
s.close()
token, _ = kis_client.get_access_token(
    app_key=str(prof.app_key), app_secret=str(prof.app_secret), is_paper=bool(prof.is_paper),
    live_base_url=settings.kis_live_base_url, paper_base_url=settings.kis_paper_base_url,
)
url = settings.kis_live_base_url + "/uapi/domestic-stock/v1/quotations/daily-short-sale"
headers = {
    "authorization": "Bearer " + token,
    "appkey": str(prof.app_key), "appsecret": str(prof.app_secret),
    "tr_id": "FHPST04830000", "custtype": "P",
}
params = {
    "FID_COND_MRKT_DIV_CODE": "J",
    "FID_INPUT_ISCD": "005930",
    "FID_INPUT_DATE_1": "20260601",
    "FID_INPUT_DATE_2": "20260610",
}
try:
    r = httpx.get(url, headers=headers, params=params, timeout=12)
    print("KIS 공매도 TR:", r.status_code, r.text[:250].replace("\n", ""))
except Exception as e:
    print("KIS ERR:", str(e)[:120])
