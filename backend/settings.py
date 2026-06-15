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

    # OpenAI (AI chart analysis)
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"

    # Google Gemini (무료 티어 – aistudio.google.com에서 발급)
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip() or "gemini-3.5-flash"

    # Groq (무료 티어 – console.groq.com에서 발급)
    groq_api_key: str = os.getenv("GROQ_API_KEY", "").strip()
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip() or "llama-3.3-70b-versatile"

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
