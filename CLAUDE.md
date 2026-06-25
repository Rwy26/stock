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
  - `exclusion_engine.py` — **global excluded-stock policy** (single source of truth). Excluded stocks
    (거래정지/정리매매/관리종목/스팩/우선주/리츠/비섹터 ETF/저유동성/동전주) are
    (1) skipped by every per-stock DB write pipeline, (2) answered with a tagged "투자 주의" payload
    *published as a normal HTTP 200 response* (the request is never error-rejected) on inquiry
    endpoints, (3) tracked only in the lightweight `excluded_stocks` index table. **NOT excluded**
    (store everything normally): price/overheat-driven market measures (투자주의/경고/위험, 단기과열)
    and sector-representative ETFs (`scoring_engine.SECTOR_ETF_MAP` — hard-exempt everywhere).
    Buy orders are blocked, sells allowed. Sweep: `scripts/refresh_exclusions.py` or
    `POST /api/admin/exclusions/refresh` (`{"kis": true}` adds market-action flags via KIS quotes —
    prefer the in-process endpoint to avoid KIS token churn with the running backend). Liquidity
    judgments hold off (no exclusion) on stale or zero-volume daily_prices data. Settings:
    `EXCLUSION_ENABLED`, `EXCLUSION_MIN_AVG_TRADING_VALUE`, `EXCLUSION_MIN_PRICE`, `EXCLUSION_LIQUIDITY_DAYS`.
    **Market leaders** (`market_leaders` table): leading stocks of market-leading sectors are a hard
    exemption — never excluded, never tagged with caution, and sorted to the top of the watchlist
    (`isLeader` flag). Leading sectors = `compute_king_sectors` (KOSPI-relative sector-ETF alpha);
    leaders = top IndicatorScore stocks within those sectors (`sector_classification.json`). Refresh:
    `POST /api/admin/leaders/refresh` (`manualCodes` pins leaders regardless of auto); auto path is
    preserved if yfinance alpha is unavailable. A protected stock cannot be manually excluded (409).
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

## 2026-06 additions (12단계 분석 AI · 공개 서비스)

**분석 엔진 체인** (모든 수치는 결정론 계산, LLM은 해석만 — Gemini→Groq→OpenAI 폴백):
- `market_compass.py` — 시장 나침반 1~7단계 (장세 판정·거시 매핑·순환 사다리·뉴스), 장중 30분 캐시
- `mtf_analysis.py` — 8단계 멀티 타임프레임 (월~15분, BOS/CHoCH/피보나치/매물대/ICT FVG/CDV)
- `target_engine.py` — 9~11단계 (목표가 5종+이상치 가드, 손절 3종, 빈도 기반 확률, 분할매수/매집구간, 공매도 점수(KIS), 52주 신고가)
- `stock_compass.py` — 12단계 통합 + ai_analysis_cache 자동 저장 (트레이딩 저널 스타일 프롬프트: 모멘텀=보유 이유, 소멸=매도 트리거)
- `news_collector.py` — 네이버 뉴스 → news_articles (24h/7d/30d 버킷)
- `graph_engine.py` — 관심종목 Force Directed Graph (상관·섹터·시총중력 엣지 + 거시 기후 boost)
- VKOSPI: `vkospi_history` 테이블 (TradingView VKI1! 웹소켓, scripts/vkospi_crawl.py)

**공개 페이지** (게스트, 이름+전화 게이트): 관심종목 트리맵 / 섹터 나침반 / AI 분석(그래프 뷰+대화형 검색, `PublicAiHistoryPage`). 관리자 외부 접속은 구글 OAuth(/login, GOOGLE_OAUTH_CLIENT_ID + ADMIN_GOOGLE_EMAIL in .env).

**뉴스레터 리포트** (`components/CompassReport.tsx`): 핵심 차트에 추세선 3종(장기=전120봉 회귀 / 중기=맥선[피크前60봉 최저 바닥→첫 되돌림 바닥, 신고가 갱신 시 '신고가 상승 추세선'] / 단기=피크前 마지막 두 스윙 저점), 하락 추세선(고점 앵커), 라벨 충돌회피 엔진(선·텍스트 모두 장애물), 현재가 방향 점멸(상승=위 파랑/하락=아래 빨강). 캔들 저가가 아닌 종가 기준이라 앵커 날짜가 1~3일 차이 날 수 있음.

**예약 작업**: 06:00 fundamentals_sync(이름 검증·VKOSPI·뉴스) → 06:30 morning_prep(전일 등락 스냅샷+캐시 워밍) → 06:50 morning-check → 21:00 batch_analyze(전 106종목, 90초 간격) → 20:10 저녁 sync. ngrok 워치독 5분(터널: cost-negligee-violate.ngrok-free.dev, 본체 C:\stock\tools\ngrok.exe — AppData 설치본은 샌드박스 격리 주의).

**원칙**: 잘못된 정보는 없는 것보다 위험 — 외부 데이터는 네이버 교차검증, 무데이터 항목은 N/A 명시, 확률은 표본 수와 함께 빈도 기반. 추세선 보정은 저장된 시계열로 앵커 날짜 시뮬레이션 후 배포.

## Batch Jobs & Automation

배치 작업은 명시적 요청이 없는 한 청크마다 중간 보고 없이 전체를 한 번에 완료한다.
실패한 청크는 원인 진단(cp949/UnicodeEncodeError, 0x1 태스크 킬, 동시 인스턴스 충돌, 백엔드 아웃) 후 자동 재시도.
모든 HTTP 호출 전 백엔드 헬스 게이트 확인. 전체 완료 후 성공/실패 건수 요약 1회만 보고.

## Python Conventions

모든 파일 I/O와 콘솔 출력은 `encoding='utf-8'` 사용 (cp949 UnicodeEncodeError 방지).
새 import 추가 시 `bootstrap.ps1`에도 함께 추가.

## Language / Transformation Rules

한국어→영어 변환 규칙(글로벌 CLAUDE.md)은 태스크 명령뿐 아니라 대화·감정 메시지를 포함한
**모든 메시지**에 적용한다.

## LLM Provider / Fallback

운영 LLM 프롬프트 타임아웃은 최소 300초로 설정 (실제 프롬프트가 ~191초 소요).
groq 폴백 프롬프트는 TPM 한도 이내로 슬림화 (413/429 방지).
폴백 순서: Gemini → Groq → OpenAI.

## Windows Scheduled Tasks

태스크 재등록 시 `DisallowStartIfOnBatteries=False` 반드시 보존.
등록 후 전원/절전 설정 변경 여부 사후 검증 필수.
