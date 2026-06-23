# 대시보드 정적 스냅샷 전환 계획 (Phase: 대시보드 한정)

> 근거: MoneyLand 역설계 효율설계(`D:\MOON\역설계\moneyland.co.kr\moonstock-comparison.md` 8절),
> 표준 지침 메모리 `moonstock-read-layer-efficiency`.
> 작성: 2026-06-23. 범위: **대시보드 읽기 계층만**. 리포트/공유 계층은 후속.

## 비협상 제약 (이 계획이 반드시 지키는 선)
1. **매매·예측 실행 경로 라이브 유지** — 정적화는 읽기/공유 계층에만.
2. **네이버 교차검증 통과분만 노출** — 미검증 외부값 금지, 무데이터는 N/A. 돈 다루는 시스템.
3. 종목명은 네이버 코드-이름 검증 기준 표기(ticker-name-display).

---

## 1. 현황 인벤토리 — 대시보드가 읽는 데이터 소스

대시보드(`frontend/src/pages/DashboardPage.tsx`)와 자식 컴포넌트가 호출하는 엔드포인트 전수:

| # | 엔드포인트 | 호출 위치 | 현재 폴링 | 데이터 소스 | 성격 |
|---|---|---|---|---|---|
| 1 | `GET /api/dashboard` | DashboardPage | **30초** | KIS 잔고(라이브, timeout 5s) + 자동매매 config/로그 DB + 추천 DB | **혼합**: 계좌+엔진(라이브) / 추천(배치) |
| 2 | `GET /api/kis/token-status` | DashboardPage | 30초 | DB KisProfile + 토큰 만료 | 라이브(인증 상태) |
| 3 | `GET /api/portfolio` | DashboardPage | 30초 | KIS 잔고 라이브(8s) + **종목별 실시간가** + DB 포지션 | 라이브(계좌·체결) |
| 4 | `GET /api/macro/us-bonds` | `UsBondsChart` | **5분** | **yfinance 매 요청 다운로드**(^TNX/^TYX), 무인증·무캐시 | **읽기전용 외부 매크로** |
| 5 | `GET /api/macro/dxy` | `DxyChart` | **5분** | **yfinance 매 요청 다운로드**(DX-Y.NYB), 무인증·무캐시 | **읽기전용 외부 매크로** |
| 6 | `/api/admin/{system-status,pending-items,engine-logs,users}` | `DevMonitor`(admin) | 수동/마운트시 | 운영 진단 DB | 라이브(운영 상태) |

### 핵심 관찰
- **#4, #5(매크로 차트)**: 매 요청마다 yfinance를 외부 호출. 캐시·인증 없음. 모든 클라이언트가 5분마다 외부 API를 때림 → **정적화 최우선 후보, 매매 경로 무관, 위험 0**.
- **#1의 `topRecommendations`**: 일배치(`recommendations-refresh` 스레드)가 채우는 DB 테이블에서 읽음. 일 1회 변동 → 저빈도 읽기 데이터, 스냅샷 가능.
- **#1의 KPI(KIS 잔고), #3(포트폴리오·실시간가), #2(토큰), 자동매매 on/off·체결 건수, #6**: 모두 **계좌·체결·엔진 라이브 상태**. 비협상 제약 ①에 의해 **라이브 유지** — 정적화 대상 아님.

> **결론**: 대시보드는 본질적으로 "계좌·자동매매 모니터링 뷰"라 대부분이 라이브다.
> 정적화 가능한 읽기 계층 슬라이스는 **(A) 매크로 차트 2종, (B) Top 추천**뿐이다. 이 둘만 전환한다.

---

## 2. 변동성 분류 → 폴링·생성 주기 매핑

| 데이터 | 분류 | 실제 변동 빈도 | 생성(배치) 주기 | 프론트 폴링 |
|---|---|---|---|---|
| us-bonds, dxy (매크로) | 저빈도 | 일봉(미 증시 마감 후 1회 갱신) | 30분 배치(여유) | **30분** (현 5분→완화) |
| top recommendations | 저빈도 | 일 1회(추천 리프레시) | 추천 리프레시 직후 + 30분 배치 | **30분** |
| (계좌·포트폴리오·토큰·엔진) | 라이브 | 실시간 | — (배치 안 함) | 30초 유지(라이브) |

라이브성(2분)에 해당하는 *읽기-계층* 항목은 대시보드에 없음(실시간은 전부 계좌/KIS → 라이브 유지).

---

## 3. 스냅샷 산출물 설계

### 디렉터리 & 서빙 경로
- 산출 위치: `backend/static/snapshots/` (기존 `backend/static/logos`와 동일 패턴, `.gitignore` 추가)
- 마운트: `app.mount("/static/snapshots", StaticFiles(directory=...), name="dashboard_snapshots")`
  (기존 `/static/logos` 마운트(`main.py:1562`) 바로 옆에 1줄 추가)
- 외부(ngrok/Cloudflare)는 이 정적 경로를 그대로 캐싱 → **서빙 시 DB 세션·yfinance·KIS 호출 0**.

### 파일 목록 (샤딩: 항목별 분리, 모놀리식 회피)
| 파일 | 내용 | 메타 |
|---|---|---|
| `dashboard-macro-us-bonds.json` | #4 응답 그대로 | `updated_at`, `count`(행수), `source:"yfinance:^TNX,^TYX"`, `stale:false` |
| `dashboard-macro-dxy.json` | #5 응답 그대로 | 동일 |
| `dashboard-top-recommendations.json` | Top5 추천(name=네이버검증명·code·score) | `updated_at`, `count`, `source:"recommendations_db"` |
| `version.json` | `{build_hash, generated_at}` 빌드/배포 신선도 게이트 | 프론트가 가장 싸게 폴링 |

각 JSON 표준 형태:
```json
{ "updated_at": "2026-06-23T18:40:00+09:00", "count": 72, "source": "...",
  "stale": false, "data": { /* 기존 엔드포인트 응답 본문 */ } }
```

### 데이터 정확성 게이트 (비협상 제약 ②)
- 매크로: yfinance 실패/NaN/플랫이면 **새 파일을 쓰지 않고 직전 정상본 유지 + `stale:true`**. 절대 깨진 값 미발행. (US 국채·DXY는 네이버 미취급 → 교차검증 N/A이나 "미검증값 미노출" 원칙은 동일 적용.)
- 추천: 종목명은 DB의 네이버 검증명(`fundamentals_sync` 전수 대조 통과분) 그대로 사용.

---

## 4. 배치 생성기

신규 `scripts/build_dashboard_snapshots.py`:
- `/api/macro/us-bonds`·`/api/macro/dxy`의 계산 로직 재사용(또는 in-process 호출)해 JSON 파일로 떨굼.
- 추천 Top5는 `/api/dashboard`의 추천 쿼리 부분만 분리 호출.
- 원자적 쓰기(tmp→rename), 메타·`stale` 플래그 기록, `version.json` 갱신.

스케줄(기존 작업 스케줄러 패턴 따름):
- 신규 `MOON-STOCK-DashboardSnapshots` — **30분 간격**(06:00~24:00).
- `morning_prep.py` 캐시 워밍 단계 끝에 1회 호출 추가(장전 준비).
- 추천 리프레시 스레드가 갱신 직후 추천 스냅샷 1회 트리거(선택).

---

## 5. 프론트 변경

- `UsBondsChart.tsx`: `fetchJson('/api/macro/us-bonds')` → `fetch('/static/snapshots/dashboard-macro-us-bonds.json?t='+Date.now())`, 폴링 5분→**30분**. 200/`stale` 처리. (스냅샷 404/stale 시 기존 API로 폴백 옵션.)
- `DxyChart.tsx`: 동일.
- `DashboardPage.tsx`: Top 추천 패널만 분리해 `/static/snapshots/dashboard-top-recommendations.json?t=` 폴링(30분). **KPI·자동매매·KIS 상태·포트폴리오는 라이브 호출 그대로 유지**.

---

## 6. 부하 격리 효과
- 매크로/추천 읽기 트래픽이 **정적 파일 서빙**으로 빠져 매매·예측 DB와 KIS/yfinance를 건드리지 않음.
- yfinance 외부 호출이 "클라이언트수 × (5분)" → "배치 1회 × 30분"으로 급감(레이트리밋·차단 위험 ↓).
- CDN/ngrok 캐싱으로 무중단·저지연.

---

## 7. 단계적 실행 (위험 낮은 순)
1. **Phase 1 [위험 0]**: 매크로 2종(us-bonds, dxy) 정적 스냅샷 — 무인증·무DB·매매무관. 가장 큰 효율 이득.
2. **Phase 2 [낮음]**: Top 추천 스냅샷 분리.
3. **Phase 3 [선택]**: 잔여 라이브 호출의 차등 폴링 재조정(계좌는 라이브 유지하되 cadence 튜닝).
4. **범위 외(라이브 유지)**: KPI/포트폴리오/토큰/자동매매/DevMonitor.

각 Phase는 기존 API를 폴백으로 남긴 채 점진 전환(롤백 용이).

---

## 구현 현황 (2026-06-23)

### Phase 1 — 매크로 차트 정적화 ✅ 코드 완료
- 마운트 `/static/snapshots` ([backend/main.py:1564](../backend/main.py))
- 빌더 [scripts/build_dashboard_snapshots.py](../scripts/build_dashboard_snapshots.py) — 메타·`stale`·원자적 쓰기·정확성 게이트(실패/빈데이터 시 직전본 유지·미발행). 실행 검증 OK.
- 30분 스케줄 설치본 [scripts/install-dashboard-snapshots-task.ps1](../scripts/install-dashboard-snapshots-task.ps1) — **미등록(운영 보류)**
- 장전 워밍 훅 [scripts/morning_prep.py](../scripts/morning_prep.py)
- 프론트 [UsBondsChart.tsx](../frontend/src/components/UsBondsChart.tsx)·[DxyChart.tsx](../frontend/src/components/DxyChart.tsx) → `fetchSnapshot`(폴백 내장), 5분→30분
- 공통 로더 `fetchSnapshot` ([frontend/src/lib/api.ts](../frontend/src/lib/api.ts))

### Phase 2 — Top 추천 정적화 ✅ 코드 완료
- 소스: `/api/public/recommendations`(무인증·DB·네이버 검증명·실시간가 없음, 동일 쿼리/폴백)
- 빌더에 `dashboard-top-recommendations.json` 추가(min_rows=0 — 빈 추천도 오늘 날짜와 정직 발행)
- 프론트 [DashboardPage.tsx](../frontend/src/pages/DashboardPage.tsx): Top 추천 패널만 분리해 스냅샷 30분 폴링. **KPI·자동매매·KIS·포트폴리오는 라이브 30초 유지.**
- 검증: 빌더 3/3 OK, 추천 14행 검증명 정상, 프론트 빌드 타입체크 통과.

### 운영 배포 (보류 중 — 사용자 지시로 정지)
1. `.\scripts\install-dashboard-snapshots-task.ps1` (30분 스케줄 등록)
2. 8000 백엔드 재시작 → `/static/snapshots` 마운트 활성 (재시작 전에도 프론트는 라이브 API 폴백으로 정상)

### 후속 범위
- 잔여 라이브 호출 차등 폴링 재조정(계좌는 라이브 유지)

---

## 리포트/공유 계층 (후속 진행 — 2026-06-23)

게스트 공개 페이지(이름+전화 게이트)의 읽기 경로. **CompassReport는 `result_json`을 props로 받는
표현 컴포넌트** → 데이터는 `ai_analysis_cache`(21:00 batch_analyze 산출). 경로: PublicAiHistoryPage(그래프)
→ 노드 클릭 → StockReportModal → `/api/public/ai-history/{code}` → CompassReport.

| 엔드포인트 | 소스 | 분류 | 처리 |
|---|---|---|---|
| `/api/public/watchlist`, `/api/public/etf-quotes` | 네이버 실시간 | 시세=라이브 | 유지(60/90s 캐시) |
| `/api/public/stock-graph` | graph_engine(30분 캐시) | 저빈도 | **Phase A 스냅샷** |
| `/api/public/ai-history` (인덱스) | ai_analysis_cache 최근50 | 저빈도 | Phase B |
| `/api/public/ai-history/{code}` (상세) | ai_analysis_cache + 제외 게이트 | 저빈도 | Phase C(샤딩) |
| `/api/public/recommendations` | DB 일배치 | 저빈도 | Phase 2에서 완료 |
| LLM(이미지/대화), 리드캡처, admin | LLM/쓰기/인증 | 라이브 | 유지 |

### Phase A — AI 그래프 정적화 ✅ 코드 완료
- 빌더 [scripts/build_public_snapshots.py](../scripts/build_public_snapshots.py) → `public-stock-graph.json`(무인증, graph_engine). 검증: 123 노드·369 엣지, 검증명 정상.
- 30분 스케줄 [scripts/install-public-snapshots-task.ps1](../scripts/install-public-snapshots-task.ps1) — **미등록(운영 보류)**
- 공통 로더 `fetchPublicSnapshot` ([frontend/src/lib/publicApi.ts](../frontend/src/lib/publicApi.ts)) — 폴백 내장
- 프론트 [PublicAiHistoryPage.tsx](../frontend/src/pages/public/PublicAiHistoryPage.tsx): 그래프 로드 → 스냅샷(폴백)

### Phase B — ai-history 인덱스 스냅샷 ❌ 불필요(취소)
프론트는 인덱스(`/api/public/ai-history`)를 호출하지 않음. 그래프 노드의 `hasReport` 플래그가
인덱스 역할을 하고, 상세만 `/api/public/ai-history/{code}`로 조회 → 인덱스 스냅샷 소비처 없음.

### Phase C — 종목별 리포트 상세 ✅ 라이브 유지 결정(2026-06-23, 사용자)
정적화하지 않고 `/api/public/ai-history/{code}` 라이브 유지. 근거:
(1) **제외 게이트 신선도** — 스냅샷 후 제외되는 종목의 "투자 주의" 태그 누락 위험이
사용자 제1원칙([[data-accuracy-over-availability]])에 저촉, (2) 상세는 모달 1회 로드(폴링 아님)라
오프로드 이득이 작고 쿼리가 가벼움. 정확성 > 오프로드.

### 공유 계층 운영 배포 (보류)
1. `.\scripts\install-public-snapshots-task.ps1`
2. morning_prep 에 build_public_snapshots 워밍 훅 추가(선택)
3. 8000 백엔드 재시작(마운트는 Phase 1에서 이미 추가됨 — 동일 재시작으로 활성)
