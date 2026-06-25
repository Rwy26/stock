from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ENV_PATH = Path(__file__).resolve().parent / ".env"

# Load backend/.env if present (written by scripts/setup-mysql-service.ps1)
if BACKEND_ENV_PATH.exists():
    load_dotenv(BACKEND_ENV_PATH)
else:
    # Also allow .env at repo root if a user prefers it.
    root_env = REPO_ROOT / ".env"
    if root_env.exists():
        load_dotenv(root_env)


def _default_pipeline_root() -> Path:
    env = os.getenv("PIPELINE_ROOT", "").strip()
    if env:
        return Path(env)

    # Windows-first default. Prefer D: (data) when present, else fall back to C:.
    # This is intentionally simple: callers can override via PIPELINE_ROOT.
    try:
        if Path("D:/").exists():
            return Path("D:/AI/pipeline")
    except Exception:
        pass
    return Path("C:/AI/pipeline")


@dataclass(frozen=True)
class Settings:
    mysql_host: str = os.getenv("MYSQL_HOST", "127.0.0.1")
    mysql_port: int = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_db: str = os.getenv("MYSQL_DB", "apollo_db")
    mysql_user: str = os.getenv("MYSQL_USER", "apollo")
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "")
    mysql_url: str = os.getenv("MYSQL_URL", "").strip()

    # Dev default only. In production, set JWT_SECRET to a long random string.
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-secret-change-me-please-change-me-32bytes")
    # Admin requirements: auto refresh uses a 20h cadence, so default to 20h expiry.
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1200"))

    # KIS OpenAPI
    kis_live_base_url: str = os.getenv("KIS_LIVE_BASE_URL", "https://openapi.koreainvestment.com:9443").rstrip("/")
    kis_paper_base_url: str = os.getenv("KIS_PAPER_BASE_URL", "https://openapivts.koreainvestment.com:29443").rstrip("/")
    # If true, price endpoints will fail when KIS quote fails (no DB fallback).
    kis_strict_price: bool = os.getenv("KIS_STRICT_PRICE", "0").strip() in {"1", "true", "True", "YES", "yes"}

    # If true, balance/KPI endpoints will fail when KIS balance inquiry fails (no sample fallback).
    kis_strict_balance: bool = os.getenv("KIS_STRICT_BALANCE", "0").strip() in {"1", "true", "True", "YES", "yes"}

    # Auto-trading engine safety kill switch (1 = disable all engine ticks/orders).
    autotrading_kill_switch: bool = os.getenv("AUTOTRADING_KILL_SWITCH", "0").strip() in {"1", "true", "True", "YES", "yes"}

    # Safety gate: allow real-money order placement.
    # This project is configured for live-only operation.
    autotrading_live_orders: bool = os.getenv("AUTOTRADING_LIVE_ORDERS", "0").strip() in {"1", "true", "True", "YES", "yes"}

    # Local-only convenience: issue an access token without password.
    # This MUST remain opt-in and restricted to loopback clients.
    allow_local_auto_login: bool = os.getenv("ALLOW_LOCAL_AUTO_LOGIN", "0").strip() in {"1", "true", "True", "YES", "yes"}
    local_auto_login_email: str = os.getenv("LOCAL_AUTO_LOGIN_EMAIL", "administrator").strip() or "administrator"

    # Pipeline output root (datasets/artifacts/runs/logs/tmp).
    # Override by setting PIPELINE_ROOT in backend/.env.
    pipeline_root: Path = _default_pipeline_root()

    # Claude CLI (Claude Code MAX 구독) — narrative LLM 1순위.
    # 개발단계 단일 사용 전제(본인+테스터 소수). claude.cmd -p 를 stdin 파이프로 호출하며
    # MAX 구독 한도(5시간/주간) 안에서 동작한다. 외부 공개 서비스 전환 시 정식 Anthropic API
    # 로 교체할 것(_call_claude_cli 의 TODO 참조). 비활성화하면 gemini/groq/openai 체인만 사용.
    claude_cli_enabled: bool = os.getenv("CLAUDE_CLI_ENABLED", "1").strip() in {"1", "true", "True", "YES", "yes"}
    claude_cli_path: str = os.getenv(
        "CLAUDE_CLI_PATH", r"C:\Users\MOON\.local\bin\claude.cmd"
    ).strip() or r"C:\Users\MOON\.local\bin\claude.cmd"
    # 풀컨텍스트 종목 리포트는 입력 ~25k자·출력 ~11k자로 실측 ~190s 소요 → 기본 300s.
    # idle 스케줄러는 유휴시간에 돌아 여유가 있고, 타임아웃 시 gemini/groq 로 자연 강등된다.
    claude_cli_timeout: int = int(os.getenv("CLAUDE_CLI_TIMEOUT", "300") or "300")

    # claude 전역 호출락 '한정 대기' 시간(초). 리포트 경로(_call_llm)는 락이 점유 중이면
    # 즉시 강등하지 않고 이 시간만큼 폴링 대기해 claude 를 실제 획득한다 — 폴백 API(gemini 등)가
    # 한도소진 상태여도 빈 narrative 로 떨어지지 않게 하는 핵심 가드. 0 이면 기존 비대기 동작.
    # 점유 콜 1건(≈190s, 최대 claude_cli_timeout) 을 넘겨받도록 timeout 보다 약간 크게 둔다.
    claude_lock_wait_sec: int = int(os.getenv("CLAUDE_LOCK_WAIT_SEC", "320") or "320")

    # MAX 구독 claude 호출 예산 — **롤링 5시간 창**(단일 소스). 배치(scripts/batch_analyze.py)·
    # idle 필러(scripts/idle_narrative_filler.ps1)·백엔드 서버가 공유 원장(logs/claude-usage.json)
    # 에 각 claude 호출의 (타임스탬프, 소요초)를 누적하고, 최근 claude_5h_window_sec(기본 5h)
    # 안에 쌓인 소요초 합이 capacity 의 use_ratio(기본 97%)에 도달하면 그 창 동안만 claude 를
    # 끈다(gemini/groq 강등). 창이 흐르며 오래된 호출이 빠지면 자동 재개. 실측: 풀리포트 1건
    # ≈ 190s. 전역 호출락(동시성 1)이 속도를, 이 게이트가 누적 한도를 통제한다.
    #
    # claude_5h_budget_sec = 5시간 창에서 claude -p 에 쓸 수 있는 누적 벽시계 초(capacity).
    #   MAX 한도를 직접 알 수 없어 **보수적 추정값**으로 시작하고, claude-usage.json 실측으로
    #   조정한다(과도 설정 시 사용자 인터랙티브 사용을 침범). 0 이면 게이트 비활성(무제한).
    #   3% 헤드룸(use_ratio=0.97)은 인터랙티브용으로 비워 둔다.
    claude_5h_budget_sec: int = int(os.getenv("CLAUDE_5H_BUDGET_SEC", "3600") or "3600")
    claude_5h_window_sec: int = int(os.getenv("CLAUDE_5H_WINDOW_SEC", "18000") or "18000")
    claude_budget_use_ratio: float = float(
        os.getenv("CLAUDE_BUDGET_USE_RATIO", "0.97") or "0.97"
    )
    # [레거시·미사용] 일/주 카운트 캡 — 롤링 5h 예산으로 대체됨. 하위 호환을 위해 필드만 유지.
    claude_daily_cap: int = int(os.getenv("CLAUDE_DAILY_CAP", "0") or "0")
    claude_weekly_cap: int = int(os.getenv("CLAUDE_WEEKLY_CAP", "0") or "0")

    # claude narrative 경로 정책 — 단일 MAX 세션의 동시 호출 충돌을 원천 차단하는 스위치.
    #   "all"(기본·2026-06 공격적 전환): 모든 경로(정규 배치·서버·idle 필러)가 claude 1순위 시도.
    #                전역 호출락(동시성 1)+롤링 5h 예산 게이트가 충돌·한도를 자동 통제하고,
    #                예산 초과분은 gemini/groq 로 자연 강등한다. 단순작업은 simple=True 로 우회.
    #   "idle_only": 정규 배치/온디맨드는 claude 미사용, idle 필러(opt-in)에서만 claude 승급.
    claude_narrative_path: str = (
        os.getenv("CLAUDE_NARRATIVE_PATH", "all").strip().lower() or "all"
    )

    # OpenAI (AI chart analysis)
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"

    # Google Gemini (무료 티어 – aistudio.google.com에서 발급)
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip() or "gemini-3.5-flash"

    # Groq (무료 티어 – console.groq.com에서 발급)
    groq_api_key: str = os.getenv("GROQ_API_KEY", "").strip()
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip() or "llama-3.3-70b-versatile"
    # Groq 폴백 전용 프롬프트 축약 — 무료 TPM(분당 토큰) 한도가 작아 큰 프롬프트가 413(Payload
    # Too Large)으로 죽는다. groq 로 보낼 때만 context 를 이 글자수 이하로 트림하고 완성 토큰을
    # 캡해 (입력+출력) 토큰이 TPM 한도 안에 들어가게 한다. gemini/openai 경로는 영향 없음.
    # 실측: 전체 context 17.3k자→413, series+닷컴 트림 9.8k자→prompt 7467토큰 정상(200).
    groq_ctx_char_budget: int = int(os.getenv("GROQ_CTX_CHAR_BUDGET", "10000") or "10000")
    groq_max_tokens: int = int(os.getenv("GROQ_MAX_TOKENS", "2048") or "2048")

    # AI provider selection: auto / openai / gemini / groq
    # auto = 설정된 키 중 Gemini > Groq > OpenAI 우선순위로 자동 선택
    ai_provider: str = os.getenv("AI_PROVIDER", "auto").strip().lower() or "auto"

    # Google OAuth 관리자 로그인 (공개 도메인에서 비밀번호 없이 관리자 진입)
    # GOOGLE_OAUTH_CLIENT_ID: Google Cloud Console > OAuth 클라이언트 ID (웹)
    # ADMIN_GOOGLE_EMAIL: 이 구글 계정만 관리자 로그인 허용 (소문자 비교)
    google_oauth_client_id: str = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    admin_google_email: str = os.getenv("ADMIN_GOOGLE_EMAIL", "").strip().lower()

    # 거래 제외 종목 엔진 (exclusion_engine) — 끄려면 EXCLUSION_ENABLED=0
    exclusion_enabled: bool = os.getenv("EXCLUSION_ENABLED", "1").strip() in {"1", "true", "True", "YES", "yes"}
    # 유동성 필터: 최근 N일 평균 거래대금(원) 미달 시 LOW_LIQUIDITY (기본 10억원)
    exclusion_min_avg_trading_value: float = float(os.getenv("EXCLUSION_MIN_AVG_TRADING_VALUE", "1000000000"))
    # 동전주 기준 종가(원) — 미만이면 PENNY (기본 1,000원)
    exclusion_min_price: float = float(os.getenv("EXCLUSION_MIN_PRICE", "1000"))
    # 유동성 판정 기간(거래일)
    exclusion_liquidity_days: int = int(os.getenv("EXCLUSION_LIQUIDITY_DAYS", "20"))

    # DART OpenAPI (공시 / 재무제표 실적)
    # 발급: https://opendart.fss.or.kr/uss/umt/EgovMberInfoEdit.do
    dart_api_key: str = os.getenv("DART_API_KEY", "").strip()

    # FRED API (선택) — 글로벌 매크로 경제지표(CPI/PPI/실업률/GDP) 조회용.
    # 발급: https://fredaccount.stlouisfed.org/apikeys
    # 키 없으면 global_macro_feeds 가 actual=None + surprise=0(부합)으로 fail-soft 폴백.
    # consensus(예상치)는 FRED 미제공 → backend/macro_consensus.json 에서 로드(스펙 §7.3).
    fred_api_key: str = os.getenv("FRED_API_KEY", "").strip()

    def database_url(self) -> str:
        if self.mysql_url:
            return self.mysql_url
        if not self.mysql_password:
            raise RuntimeError(
                "MYSQL_PASSWORD is not set. Create backend/.env with MYSQL_* variables "
                "(or run scripts/setup-mysql-service.ps1 with -WriteBackendEnv)."
            )
        # SQLAlchemy URL for PyMySQL
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}?charset=utf8mb4"
        )


settings = Settings()
