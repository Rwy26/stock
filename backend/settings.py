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

    # Auto-trading engine safety kill switch (1 = disable all engine ticks/orders).
    autotrading_kill_switch: bool = os.getenv("AUTOTRADING_KILL_SWITCH", "0").strip() in {"1", "true", "True", "YES", "yes"}

    # Safety gate: allow real-money order placement when tradeType is live.
    # Paper (VTS) orders are allowed without this flag.
    autotrading_live_orders: bool = os.getenv("AUTOTRADING_LIVE_ORDERS", "0").strip() in {"1", "true", "True", "YES", "yes"}

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
