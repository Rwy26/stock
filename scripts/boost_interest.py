"""최신 이슈 + 주도 섹터 종목 → 가중치 최대값(5.0 / depth 3) 강제 설정."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import text
from db import get_session_factory

# 이미지(주도섹터 표) 전체 종목 코드
MAX_CODES: list[tuple[str, str]] = [
    # 젠슨황 방한 / 로봇·AI
    ("003550", "로봇·AI수혜"),
    ("064260", "로봇·AI수혜|시스템통합"),
    ("066570", "로봇·AI수혜"),
    ("011070", "로봇·AI수혜|MLCC"),
    ("307950", "로봇·AI수혜|시스템통합"),
    ("012330", "로봇·AI수혜"),
    ("005380", "로봇·AI수혜"),
    ("108490", "로봇·AI수혜"),
    ("090360", "로봇·AI수혜"),
    ("035420", "로봇·AI수혜"),
    # SI 시스템통합
    ("018260", "시스템통합"),
    ("181710", "시스템통합"),
    # MLCC / 반도체기판
    ("009150", "MLCC·반도체기판"),
    ("001820", "MLCC·반도체기판"),
    ("052710", "MLCC·반도체기판"),
    ("036490", "MLCC·반도체기판"),
    ("195870", "MLCC·반도체기판"),
    ("353200", "MLCC·반도체기판"),
    ("007810", "MLCC·반도체기판"),
    ("314760", "MLCC·반도체기판"),
    ("007660", "MLCC·반도체기판"),
    ("222800", "MLCC·반도체기판"),
    # 2차전지 / ESS
    ("373220", "2차전지·ESS"),
    ("006400", "2차전지·ESS"),
    ("066970", "2차전지·ESS"),
    ("096770", "2차전지·ESS"),
    ("393890", "2차전지·ESS"),
    ("091580", "2차전지·ESS"),
    # 반도체 대형주
    ("000660", "반도체"),
    ("005930", "반도체"),
    ("042700", "반도체"),
    # 바이오
    ("347850", "바이오"),
    ("009420", "바이오"),
    ("226950", "바이오"),
    ("048410", "바이오"),
    ("397030", "바이오"),
    ("196170", "바이오"),
    ("141080", "바이오"),
    ("207940", "바이오"),
    ("068270", "바이오"),
    # 우주항공 / 태양광
    ("274090", "우주항공"),
    ("010060", "우주항공·태양광"),
    ("095910", "태양광"),
    ("322000", "태양광"),
    ("009830", "태양광"),
    ("012450", "우주항공"),
]

TAGS_NOTE = "최신이슈,주도섹터"

def run() -> None:
    db = get_session_factory()()
    try:
        boosted = []
        inserted = []
        for code, tag in MAX_CODES:
            r = db.execute(
                text(
                    "UPDATE stock_interest "
                    "SET mention_count=99, interest_weight=5.0, analysis_depth=3, "
                    "last_mentioned_at=NOW() "
                    "WHERE user_id=1 AND stock_code=:code"
                ),
                {"code": code},
            )
            if r.rowcount:
                boosted.append(code)
            else:
                db.execute(
                    text(
                        "INSERT IGNORE INTO stock_interest "
                        "(user_id, stock_code, mention_count, interest_weight, analysis_depth, tags) "
                        "VALUES (1, :code, 99, 5.0, 3, :tags)"
                    ),
                    {"code": code, "tags": f'["{TAGS_NOTE}","{tag}"]'},
                )
                inserted.append(code)

        db.commit()

        rows = db.execute(
            text(
                "SELECT si.stock_code, s.name, si.interest_weight, si.analysis_depth "
                "FROM stock_interest si "
                "JOIN stocks s ON s.code = si.stock_code "
                "WHERE si.user_id=1 "
                "ORDER BY si.interest_weight DESC, si.stock_code"
            )
        ).all()

        depth_label = {1: "기본", 2: "심화", 3: "전문"}
        d5 = [(c, n, w, d) for c, n, w, d in rows if w >= 5.0]
        d_other = [(c, n, w, d) for c, n, w, d in rows if w < 5.0]

        print(f"\n★ 최대 가중치(5.0/전문) 설정 완료: {len(d5)}종목 "
              f"(갱신 {len(boosted)}개 / 신규 {len(inserted)}개)\n")
        print(f"{'코드':<8} {'종목명':<22} {'가중치':>6} {'분석':>4}")
        print("─" * 48)
        for code, name, w, d in d5:
            print(f"  {code:<8} {name:<22} {w:>6.1f} {depth_label.get(d,'?'):>4}")

        if d_other:
            print(f"\n  ─ 나머지 {len(d_other)}종목은 기본/심화 유지 ─")

    finally:
        db.close()


if __name__ == "__main__":
    run()
