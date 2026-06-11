# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Korean-stock (KOSPI/KOSDAQ) trading, recommendation, and auto-trading platform.
The FastAPI app title is **"MOON STOCK"**; the internal codename is **"Apollo"** (the MySQL
database is `apollo_db`, scripts refer to the "Apollo workspace"). It is a **real-data-only,
live-trading** system — there is no demo seed data, and the engine can place real-money orders
through the KIS brokerage API when the safety gates are open.

Windows-only. All operational tooling is PowerShell (`scripts/*.ps1`). Documentation and many
code comments are in Korean.

## Architecture

**Backend** (`backend/`) — FastAPI monolith. `main.py` (~200KB, ~64 routes) holds *all* HTTP
endpoints directly on a single `app` object (no `APIRouter` split). Supporting modules:

- `settings.py` — single `settings` dataclass loaded from `backend/.env` (falls back to repo-root `.env`). Source of truth for DB URL, JWT, KIS/DART/AI keys, and the safety gates.
- `db.py` — SQLAlchemy engine/session factory (`get_db`, `session_scope`); `settings`/`db`/`models` are imported as **top-level modules**, so the backend must run with `--app-dir backend` (cwd-sensitive).
- `models.py` — ~25 ORM tables (users, stocks, daily_prices, recommendations, portfolio, watchlist, KIS profiles, plus per-tier auto-trading config/position/log tables, AI cache, investor flow).
- `auth.py` — JWT (PyJWT) + `pbkdf2_sha256` password hashing. Bearer-token auth; `get_current_user` / `require_admin` dependencies in `main.py`.
- **Engines** (called from routes and background threads):
  - `scoring_engine.py` — 3-tier stock recommendation scoring (sector leadership → breakout → negative filter).
  - `sector_rotation.py` — 7-layer KOSPI sector-rotation scoring (macro/foreign/institutional/momentum/news/volume/smart-money).
  - `supply_demand.py` — foreign/institutional flow + DART financials aggregation feeding the scoring engine.
  - `short_selling.py` — daily short-selling volume (KIS, T+1) / balance (KRX login required, T+2) ingestion into `short_selling_daily` + 3-day surge flag (`short_sell_surge_3d`) for the scoring engine's negative filter. Daily sync: `scripts/short_selling_sync.py` (scheduled task, 18:40 KST).
  - `chart_analysis.py` — AI chart analysis (OpenAI Vision / Gemini / Groq) from ticker, CSV, JSON, or screenshot.
- **External clients**: `kis_client.py` (Korea Investment & Securities OpenAPI — quotes, balances, orders; live + paper base URLs), `dart_client.py` (DART financial statements via OpenDartReader). Market data also comes from yfinance / pykrx / FinanceDataReader.
- **Background threads** started in `@app.on_event("startup")`: `kis-token-refresh`, `autotrade-tick`, `recommendations-refresh` (all daemon threads, stopped via `threading.Event`s on shutdown).

**Frontend** (`frontend/`) — React 19 + TypeScript + Vite, `react-router-dom` v7, `lightweight-charts`.
Pages in `src/pages/`, one per route (see `src/App.tsx`); auth-gated by `layout/RequireAuth.tsx`
inside `layout/AppShell.tsx`. `src/lib/api.ts` is the fetch wrapper with automatic JWT refresh
(`/api/auth/refresh`) and redirect-to-login on 401.

**Auto-trading tiers** — three independent engines, each with its own config/position/log tables
and `/api/automation/*` endpoints: **SA** (basic), **Plus**, and **SV** (agent). Frontend pages:
`AutoSaPage`, `AutoPlusPage`, `SvAgentPage`, `AutoBasicPage`.

**`scripts/reverse_engine/`** — standalone library for reverse-engineering indicator columns
(Wilder RSI, Bollinger bands, buy/sell signal bands) from observed series; used by the
`scripts/infer_*.py` / `analyze_*.py` / `verify_indicators.py` analysis scripts.

**Pipeline outputs** — `pipeline_paths.py` resolves a `PIPELINE_ROOT` (default `D:\AI\pipeline`
if `D:` exists, else `C:\AI\pipeline`) for datasets/artifacts/runs; **outside** the repo.

## Commands

Run all PowerShell scripts from the repo root (`C:\stock`). First-time setup:

```powershell
.\scripts\bootstrap.ps1            # create backend\.venv + install core backend deps + node check
.\scripts\setup-mysql-service.ps1  # provision local MySQL + (with -WriteBackendEnv) write backend\.env
.\scripts\init-db.ps1              # create tables + seed admin (backend\db_init.py)
```

Day-to-day:

```powershell
.\scripts\run-backend.ps1          # uvicorn main:app --reload --app-dir backend  → http://127.0.0.1:5001
.\scripts\run-frontend.ps1         # vite dev (strictPort)                         → http://127.0.0.1:3001
```

Frontend (from `frontend/`):

```powershell
npm run dev      # vite dev server (port 3001)
npm run build    # tsc -b && vite build
npm run lint     # eslint .
npm run preview  # preview production build
```

- The Vite dev server proxies `/api` and `/health` to `http://127.0.0.1:5001` (the dev backend port).
- `scripts/start-backend-8000.ps1` / `install-backend-8000-startup.ps1` run a **detached production
  backend on port 8000** as a boot task — a separate path from the port-5001 dev server.
- There is no test suite. Verification is via `scripts/verify-*.ps1`, `scripts/smoke-*.ps1`, and the
  Python `analyze_*` / `verify_indicators.py` scripts.

## Key constraints & gotchas

- **Dependencies are installed imperatively, not from a manifest.** There is no `requirements.txt`
  or `pyproject.toml`. `bootstrap.ps1` pip-installs the core set (fastapi, uvicorn[standard],
  sqlalchemy, pymysql, python-dotenv, cryptography, passlib, PyJWT, httpx). Heavier runtime deps
  (yfinance, pandas, numpy, pykrx, FinanceDataReader, OpenDartReader, AI SDKs) are imported lazily
  and may need `pip install` into `backend\.venv` if a feature errors on import. When adding a new
  import, also add it to `bootstrap.ps1`.
- **Live-money safety gates** (in `backend/.env`, read by `settings.py`):
  `AUTOTRADING_KILL_SWITCH=1` disables all engine ticks/orders; `AUTOTRADING_LIVE_ORDERS=1` enables
  real (non-paper) order placement. There is also a runtime admin kill-switch override
  (`POST /api/admin/engine/kill-switch`). Treat any change touching order placement as high-risk.
- **Real-data-only**: `db_init.py` seeds *only* the admin user (id=1) — no demo stocks/prices.
  Empty tables are expected on a fresh DB until ingestion scripts (`fetch_daily_prices.py`,
  `seed_stocks.py`, etc.) and the engines populate them.
- **Secrets**: `backend/.env` holds DB password, JWT secret, KIS app key/secret, DART/AI keys.
  It is git-ignored — never commit it. KIS profiles are stored in the DB and the secret is never
  returned by GET APIs.
- **Hourly git auto-save**: a Windows scheduled task (`install-git-auto-save-task.ps1`) runs
  `git-auto-save.ps1` to commit+push every hour (log: `logs/git-auto-save.log`). Expect frequent
  automated commits; `logs/` is git-ignored.
- Backend modules use top-level (not package-relative) imports, so always run with `--app-dir backend`
  / cwd at `backend` — running `python main.py` from the repo root will fail to import `settings`/`db`.
