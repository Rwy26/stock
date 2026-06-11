"""
scripts/seed_stocks.py
이슈 종목 stocks 테이블 UPSERT + 관심종목(watchlist) 등록 + 관심도(stock_interest) 추적.

사용법:
    python scripts/seed_stocks.py [--watchlist-user-id 1]

동작:
  - stocks 테이블: INSERT … ON DUPLICATE KEY UPDATE (코드 중복 시 이름/마켓 갱신)
  - watchlist 테이블: INSERT IGNORE (이미 등록된 종목 건너뜀)
  - stock_interest 테이블: 등장할 때마다 mention_count +1, interest_weight·analysis_depth 자동 갱신
      interest_weight = min(1.0 + ln(mention_count) * 1.5, 5.0)
      analysis_depth:  mention_count 1~2 → 1 (기본)
                       mention_count 3~5 → 2 (심화: details JSON 풀 저장)
                       mention_count 6+  → 3 (전문: DART 실적 + 60m 신호)
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text
from db import get_session_factory

# ─────────────────────────────────────────────────────────────────────────────
# 종목 리스트: (code, name, market, sector_tag)
# sector_tag는 로그 출력용; DB에 저장되지 않음
# KODEX 등 ETF, 코드 불확실 종목은 제외
# ─────────────────────────────────────────────────────────────────────────────
SEED_STOCKS: list[tuple[str, str, str, str]] = [

    # ── 젠슨황 방한 수혜 / 로봇·AI ───────────────────────────────────────────
    ("003550", "LG",               "KOSPI",  "로봇·AI수혜"),
    ("064400", "LG씨엔에스",       "KOSPI",  "로봇·AI수혜|시스템통합"),
    ("066570", "LG전자",           "KOSPI",  "로봇·AI수혜"),
    ("011070", "LG이노텍",         "KOSPI",  "로봇·AI수혜|MLCC·반도체기판"),
    ("307950", "현대오토에버",     "KOSPI",  "로봇·AI수혜|시스템통합"),
    ("012330", "현대모비스",       "KOSPI",  "로봇·AI수혜"),
    ("005380", "현대차",           "KOSPI",  "로봇·AI수혜"),
    ("108490", "로보티즈",         "KOSDAQ", "로봇·AI수혜|외국인수급"),
    ("090360", "로보스타",         "KOSDAQ", "로봇·AI수혜"),
    ("035420", "NAVER",            "KOSPI",  "로봇·AI수혜"),

    # ── 시스템 통합 (SI) ─────────────────────────────────────────────────────
    ("018260", "삼성에스디에스",   "KOSPI",  "시스템통합"),
    ("181710", "NHN",              "KOSDAQ", "시스템통합"),

    # ── MLCC / 반도체 기판 ───────────────────────────────────────────────────
    ("009150", "삼성전기",         "KOSPI",  "MLCC·반도체기판"),
    ("001820", "삼화콘덴서",       "KOSPI",  "MLCC·반도체기판"),
    ("052710", "아모텍",           "KOSDAQ", "MLCC·반도체기판"),
    ("036010", "아비코전자",       "KOSDAQ", "MLCC·반도체기판"),
    ("195870", "해성디에스",       "KOSDAQ", "MLCC·반도체기판"),
    ("353200", "대덕전자",         "KOSPI",  "MLCC·반도체기판"),
    ("007810", "코리아써키트",     "KOSPI",  "MLCC·반도체기판"),
    ("356860", "티엘비",           "KOSDAQ", "MLCC·반도체기판"),
    ("007660", "이수페타시스",     "KOSPI",  "MLCC·반도체기판|기관수급"),
    ("222800", "심텍",             "KOSDAQ", "MLCC·반도체기판"),

    # ── 2차전지 / ESS ────────────────────────────────────────────────────────
    ("373220", "LG에너지솔루션",   "KOSPI",  "2차전지·ESS"),
    ("006400", "삼성SDI",          "KOSPI",  "2차전지·ESS"),
    ("066970", "엘앤에프",         "KOSDAQ", "2차전지·ESS"),
    ("096770", "SK이노베이션",     "KOSPI",  "2차전지·ESS"),
    ("393890", "더블유씨피",       "KOSDAQ", "2차전지·ESS"),
    ("091580", "상신이디피",       "KOSDAQ", "2차전지·ESS"),

    # ── 반도체 (대형주) ──────────────────────────────────────────────────────
    ("000660", "SK하이닉스",       "KOSPI",  "반도체"),
    ("005930", "삼성전자",         "KOSPI",  "반도체"),
    ("042700", "한미반도체",       "KOSPI",  "반도체"),

    # ── 바이오 ───────────────────────────────────────────────────────────────
    ("207940", "삼성바이오로직스", "KOSPI",  "바이오"),
    ("068270", "셀트리온",         "KOSPI",  "바이오|외국인수급"),
    ("009420", "한올바이오파마",   "KOSPI",  "바이오"),
    ("226950", "올릭스",           "KOSDAQ", "바이오"),
    ("048410", "현대바이오",       "KOSDAQ", "바이오"),
    ("196170", "알테오젠",         "KOSDAQ", "바이오"),
    ("141080", "리가켐바이오",     "KOSDAQ", "바이오"),
    ("397030", "에이프릴바이오",   "KOSDAQ", "바이오"),
    ("347850", "디앤디파마텍",     "KOSDAQ", "바이오"),

    # ── 우주항공 / 태양광 ────────────────────────────────────────────────────
    ("012450", "한화에어로스페이스", "KOSPI",  "우주항공·태양광"),
    ("274090", "켄코아에어로스페이스", "KOSDAQ", "우주항공·태양광"),
    ("010060", "OCI홀딩스",           "KOSPI",  "우주항공·태양광"),
    ("095910", "에스에너지",          "KOSDAQ", "우주항공·태양광"),
    ("322000", "HD현대에너지솔루션",  "KOSPI",  "우주항공·태양광"),
    ("009830", "한화솔루션",          "KOSPI",  "우주항공·태양광"),

    # ── 외국인 수급 (1차 이미지) ─────────────────────────────────────────────
    ("001440", "국일신동",            "KOSPI",  "전력기기|외국인수급"),
    ("000400", "롯데손해보험",        "KOSPI",  "외국인수급"),   # 대한전선 그룹
    ("001120", "대한전선",            "KOSPI",  "외국인수급"),
    ("064350", "현대로템",            "KOSPI",  "외국인수급|방산"),
    ("078930", "GS",                  "KOSPI",  "외국인수급"),
    ("483650", "달바글로벌",          "KOSDAQ", "외국인수급"),
    ("000720", "현대건설",            "KOSPI",  "외국인수급"),
    ("086790", "하나금융지주",        "KOSPI",  "금융|외국인수급"),
    ("030200", "KT",                  "KOSPI",  "외국인수급"),   # 한국금융지주 대신 KT 확인 필요
    ("030610", "교보증권",            "KOSPI",  "외국인수급"),   # 한국금융지주
    # KOSDAQ 외국인
    ("039030", "이오테크닉스",        "KOSDAQ", "외국인수급|반도체"),
    ("064760", "티씨케이",            "KOSDAQ", "외국인수급|반도체"),
    ("218410", "RFHIC",               "KOSDAQ", "외국인수급"),
    ("403870", "HPSP",                "KOSDAQ", "외국인수급|반도체"),
    ("108490", "로보티즈",            "KOSDAQ", "외국인수급|로봇"),
    ("043260", "성호전자",            "KOSDAQ", "외국인수급"),
    ("084370", "유진테크",            "KOSDAQ", "외국인수급|반도체"),
    ("099320", "쎄트렉아이",          "KOSDAQ", "외국인수급|우주항공"),
    ("031980", "피에스케이홀딩스",    "KOSDAQ", "외국인수급|반도체"),
    ("101490", "에스앤에스텍",        "KOSDAQ", "외국인수급|반도체"),
    ("327260", "RF머트리얼즈",        "KOSDAQ", "외국인수급"),

    # ── 기관 수급 (1차 이미지) ───────────────────────────────────────────────
    ("000270", "기아",                "KOSPI",  "자동차·로봇|기관수급"),
    ("007660", "이수페타시스",        "KOSPI",  "MLCC·반도체기판|기관수급"),
    ("003670", "포스코퓨처엠",        "KOSPI",  "2차전지·ESS|기관수급"),
    ("017670", "SK텔레콤",            "KOSPI",  "기관수급"),
    ("047810", "KAI",                 "KOSPI",  "방산|기관수급"),
    # KOSDAQ 기관
    ("131970", "두산테스나",          "KOSDAQ", "기관수급|반도체"),
    ("237690", "에스티팜",            "KOSDAQ", "기관수급|바이오"),   # 한국피아이엠 확인
    ("247540", "에코프로비엠",        "KOSDAQ", "기관수급|2차전지"),
    ("376300", "디어유",              "KOSDAQ", "기관수급"),          # 싸이맥스 확인
    ("290650", "엘앤씨바이오",        "KOSDAQ", "기관수급|바이오"),

    # ── 기존 섹터로테이션 보완 ────────────────────────────────────────────────
    ("281740", "레이크머티리얼즈",    "KOSDAQ", "반도체"),
    ("010120", "LS ELECTRIC",         "KOSPI",  "전력기기"),
    ("103590", "일진전기",            "KOSPI",  "전력기기"),
    ("079550", "LIG디펜스앤에어로스페이스", "KOSPI", "방산"),  # 구 LIG넥스원 (사명 변경)
    ("009540", "HD한국조선해양",      "KOSPI",  "조선"),
    ("010140", "삼성중공업",          "KOSPI",  "조선"),
    ("329180", "HD현대중공업",        "KOSPI",  "조선"),
    ("105560", "KB금융",              "KOSPI",  "금융"),
    ("055550", "신한지주",            "KOSPI",  "금융"),
    ("316140", "우리금융지주",        "KOSPI",  "금융"),
    ("051910", "LG화학",              "KOSPI",  "2차전지·ESS"),
    ("267250", "HD현대",              "KOSPI",  "조선"),  # HD현대로보틱스는 비상장; 267250은 HD현대(지주)
    ("277810", "레인보우로보틱스",    "KOSDAQ", "자동차·로봇"),
    ("326030", "SK바이오팜",          "KOSPI",  "바이오"),
]

# 중복 코드 제거 (sector_tag 달라도 코드 같으면 첫 번째만)
seen: set[str] = set()
UNIQUE_STOCKS: list[tuple[str, str, str, str]] = []
for item in SEED_STOCKS:
    if item[0] not in seen:
        seen.add(item[0])
        UNIQUE_STOCKS.append(item)


def _calc_weight(mention_count: int) -> tuple[float, int]:
    """mention_count → (interest_weight, analysis_depth)"""
    weight = min(1.0 + math.log(mention_count) * 1.5, 5.0)
    weight = round(weight, 2)
    if mention_count >= 6:
        depth = 3
    elif mention_count >= 3:
        depth = 2
    else:
        depth = 1
    return weight, depth


def run(watchlist_user_id: int) -> None:
    db = get_session_factory()()
    try:
        stock_ok = stock_skip = 0
        wl_ok = wl_skip = 0
        interest_new: list[tuple[str, str, int, float, int]] = []
        interest_updated: list[tuple[str, str, int, float, int]] = []

        for code, name, market, tag in UNIQUE_STOCKS:
            # ── stocks UPSERT ─────────────────────────────────────────────
            db.execute(
                text("""
                    INSERT INTO stocks (code, name, market)
                    VALUES (:code, :name, :market)
                    ON DUPLICATE KEY UPDATE name = VALUES(name), market = VALUES(market)
                """),
                {"code": code, "name": name, "market": market},
            )
            stock_ok += 1

            # ── watchlist INSERT IGNORE ───────────────────────────────────
            result = db.execute(
                text("""
                    INSERT IGNORE INTO watchlist (user_id, stock_code)
                    VALUES (:uid, :code)
                """),
                {"uid": watchlist_user_id, "code": code},
            )
            if result.rowcount:
                wl_ok += 1
            else:
                wl_skip += 1

            # ── stock_interest: mention_count +1, 가중치 갱신 ─────────────
            existing = db.execute(
                text("SELECT mention_count FROM stock_interest WHERE user_id=:uid AND stock_code=:code"),
                {"uid": watchlist_user_id, "code": code},
            ).scalar_one_or_none()

            tags_json = f'["{tag}"]' if tag else "[]"

            if existing is None:
                new_count = 1
                weight, depth = _calc_weight(new_count)
                db.execute(
                    text("""
                        INSERT INTO stock_interest
                            (user_id, stock_code, mention_count, interest_weight, analysis_depth, tags)
                        VALUES (:uid, :code, :cnt, :w, :d, :tags)
                    """),
                    {"uid": watchlist_user_id, "code": code,
                     "cnt": new_count, "w": weight, "d": depth, "tags": tags_json},
                )
                interest_new.append((code, name, new_count, weight, depth))
            else:
                new_count = existing + 1
                weight, depth = _calc_weight(new_count)
                db.execute(
                    text("""
                        UPDATE stock_interest
                        SET mention_count=:cnt, interest_weight=:w, analysis_depth=:d,
                            last_mentioned_at=NOW()
                        WHERE user_id=:uid AND stock_code=:code
                    """),
                    {"uid": watchlist_user_id, "code": code,
                     "cnt": new_count, "w": weight, "d": depth},
                )
                interest_updated.append((code, name, new_count, weight, depth))

        db.commit()
        print(f"\nstocks  : {stock_ok}개 upsert 완료")
        print(f"watchlist: 신규 {wl_ok}개 등록 / {wl_skip}개 이미 존재")

        # ── 관심도 리포트 ─────────────────────────────────────────────────
        DEPTH_LABEL = {1: "기본", 2: "심화", 3: "전문"}
        if interest_new:
            print(f"\n[신규 등록 {len(interest_new)}종목]")
            for code, name, cnt, w, d in interest_new:
                print(f"  {code} {name:<18} 언급 {cnt}회  가중치 {w:.2f}  분석 {DEPTH_LABEL[d]}")

        if interest_updated:
            print(f"\n[가중치 갱신 {len(interest_updated)}종목]")
            for code, name, cnt, w, d in sorted(interest_updated, key=lambda x: -x[3]):
                print(f"  {code} {name:<18} 언급 {cnt}회  가중치 {w:.2f}  분석 {DEPTH_LABEL[d]}")

        # ── 분석 깊이별 요약 ──────────────────────────────────────────────
        rows = db.execute(
            text("""
                SELECT si.analysis_depth, COUNT(*) as cnt
                FROM stock_interest si
                WHERE si.user_id = :uid
                GROUP BY si.analysis_depth ORDER BY si.analysis_depth
            """),
            {"uid": watchlist_user_id},
        ).all()
        if rows:
            print("\n[분석 깊이 현황]")
            for depth, cnt in rows:
                bar = "█" * cnt
                print(f"  depth {depth} ({DEPTH_LABEL[depth]:>4}): {cnt:>3}종목  {bar}")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchlist-user-id", type=int, default=1,
                        help="관심종목 등록 대상 user_id (기본: 1 = admin)")
    args = parser.parse_args()
    run(args.watchlist_user_id)
