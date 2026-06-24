"""run_scoring.py — 3-Tier 스코어링(IndicatorScore) 일일 자동 실행.

배경: IndicatorScore(scoring_engine 3-tier 점수)는 추천종목(recommendations)·주도주
(market_leaders)의 근거 데이터인데, 수동 엔드포인트(POST /api/admin/scoring/run)로만
생성돼 자동 스케줄이 없으면 정체된다. 이 스크립트를 매일 장 마감 후 1회 실행해
IndicatorScore 를 신선하게 유지한다(install-scoring-task.ps1, 16:40 KST).

동작:
  1. backend 모듈로 관리자 JWT 를 직접 발급(로그인 비밀번호 불필요).
  2. 가동 중인 백엔드(기본 :8000)의 POST /api/admin/scoring/run 호출
     — 전 종목(제외종목 필터는 엔드포인트가 적용) 결정론 스코어링 + IndicatorScore upsert
     + recommendations 갱신까지 엔드포인트 로직을 그대로 재사용(단일 소스).
  3. 이어서 POST /api/admin/leaders/refresh 로 주도주(market_leaders) 재산출
     → claude T0 우선순위가 매일 최신 주도주로 동작.

결정론 점수 산출만 — 주문/LLM 무관(킬스위치 무관). 무거운 작업(KIS+DART+yfinance 전 종목)
이라 장중 피하고 장 마감·일봉 적재(16:10) 이후 실행한다. 국제망(yfinance) 의존 항목은
혼잡 시 부분 실패를 허용하고 가용 데이터로 점수를 낸다.

로그: logs/scoring.log

사용법:
  python scripts/run_scoring.py                 # :8000 백엔드 대상 전 종목 스코어링 + 주도주 갱신
  python scripts/run_scoring.py --base http://127.0.0.1:5001
  python scripts/run_scoring.py --no-leaders    # 주도주 갱신 생략(스코어링만)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402

LOG = REPO / "logs" / "scoring.log"
DEFAULT_BASE = "http://127.0.0.1:8000"


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def mint_admin_token() -> str:
    """가동 중인 백엔드를 재기동하지 않고 관리자 JWT 를 직접 발급.

    로그인(이메일/비밀번호) 대신 backend 모듈로 토큰을 서명한다 — login 엔드포인트가
    반환하는 accessToken 과 동일한 형식(HS256, sub=user.id). require_admin 통과를 위해
    role=='admin' 사용자(없으면 id=1)를 주체로 한다.
    """
    import db as apollo_db
    import models
    import auth
    from settings import settings
    from sqlalchemy import select

    s = apollo_db.get_session_factory()()
    try:
        admin = s.execute(
            select(models.User).where(models.User.role == "admin").order_by(models.User.id)
        ).scalars().first()
        if admin is None:
            admin = s.get(models.User, 1)
        if admin is None:
            raise RuntimeError("관리자 사용자 없음 — db_init.py 로 admin 시드 필요")
        return auth.create_access_token(
            subject=str(admin.id),
            secret=settings.jwt_secret,
            expires_minutes=int(settings.jwt_expire_minutes),
        )
    finally:
        s.close()


def wait_for_backend(base: str, max_wait: int = 300) -> bool:
    """백엔드 /health 가 200 OK 될 때까지 최대 max_wait초 대기. 성공 True."""
    import time

    deadline = time.time() + max_wait
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            r = httpx.get(base + "/health", timeout=10)
            if r.status_code == 200 and r.json().get("ok"):
                if attempt > 1:
                    log(f"백엔드 준비됨 (시도 {attempt}회)")
                return True
        except Exception:
            pass
        log(f"백엔드 대기 중... ({attempt}회, /health 무응답)")
        time.sleep(15)
    return False


def run_scoring(base: str, token: str) -> dict:
    """POST /api/admin/scoring/run — 전 종목 결정론 스코어링 + IndicatorScore upsert + 추천 갱신."""
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        # codes 미지정 → DB 전체 종목(엔드포인트가 exclusion_engine.filter_codes 적용)
        "fetch_supply_demand": True,    # KIS+DART 수급/실적 자동 수집
        "prefetch_fundamentals": True,  # yfinance EPS 사전 조회
    }
    # 전 종목 스코어링(KIS+DART+yfinance)은 수 분~수십 분 소요 가능 — 넉넉한 read 타임아웃.
    timeout = httpx.Timeout(connect=15.0, read=1800.0, write=30.0, pool=30.0)
    r = httpx.post(base + "/api/admin/scoring/run", json=payload, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def refresh_leaders(base: str, token: str) -> dict:
    """POST /api/admin/leaders/refresh — 최신 IndicatorScore 기준으로 주도주 재산출."""
    headers = {"Authorization": f"Bearer {token}"}
    timeout = httpx.Timeout(connect=15.0, read=600.0, write=30.0, pool=30.0)
    r = httpx.post(base + "/api/admin/leaders/refresh", json={}, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="3-Tier 스코어링(IndicatorScore) 일일 자동 실행")
    ap.add_argument("--base", default=DEFAULT_BASE, help=f"백엔드 베이스 URL(기본 {DEFAULT_BASE})")
    ap.add_argument("--no-leaders", action="store_true", help="주도주(market_leaders) 갱신 생략")
    return ap.parse_args()


def main() -> int:
    args = _parse_args()
    base = args.base.rstrip("/")

    log(f"=== 스코어링 시작 (base={base}) ===")
    if not wait_for_backend(base, max_wait=300):
        log("=== 스코어링 중단: 백엔드 5분 내 미기동 — 백엔드 기동 후 재실행 필요 ===")
        return 2

    try:
        token = mint_admin_token()
    except Exception as exc:  # noqa: BLE001
        log(f"=== 스코어링 중단: 관리자 토큰 발급 실패 — {type(exc).__name__}: {exc} ===")
        return 1

    # 1) 3-Tier 스코어링 + IndicatorScore upsert + 추천 갱신
    res = run_scoring(base, token)
    log(
        f"스코어링 완료: date={res.get('date')} total_scored={res.get('total_scored')} "
        f"upserted={res.get('upserted')} eligible={res.get('eligible_count')}"
    )
    top10 = res.get("top10") or []
    if top10:
        head = ", ".join(f"{t.get('code')}={t.get('score')}" for t in top10[:5])
        log(f"  Top5: {head}")

    # 2) 최신 점수로 주도주 재산출 (claude T0 우선순위 최신화)
    if args.no_leaders:
        log("주도주 갱신 생략(--no-leaders)")
    else:
        try:
            lead = refresh_leaders(base, token)
            # compute_market_leaders 반환: leaders=주도주 수(int), king_computed=yfinance 알파 성공 여부
            log(
                f"주도주 갱신 완료: leaders={lead.get('leaders')} manual={lead.get('manual')} "
                f"king_computed={lead.get('king_computed')} "
                f"sectorTopN={lead.get('sector_top_n')}/perSector={lead.get('leaders_per_sector')}"
            )
        except Exception as exc:  # noqa: BLE001 — 주도주 갱신 실패는 스코어링 성공을 무효화하지 않음
            log(f"주도주 갱신 실패(스코어링은 성공): {type(exc).__name__}: {str(exc)[:160]}")

    log("=== 스코어링 종료 ===")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 — 미처리 예외도 로그에 남겨 0x1 원인 추적
        import traceback

        log(f"=== 스코어링 비정상 종료: {type(exc).__name__}: {exc} ===")
        log(traceback.format_exc())
        raise SystemExit(1)
    raise SystemExit(rc)
