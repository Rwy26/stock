# 자율 진화형 예측 팩토리 (Prediction Factory)

> 단일 예측 모델이 아니라, **경쟁하며 협력하는 다중 에이전트 시스템**.
> 모듈이 붙었다 떨어졌다 하며 지속적으로 진화한다.
> 라이브 매매/추천 경로는 **불가침** — 팩토리는 섀도(병렬)로 시작해 검증된 뒤에만 영향력을 갖는다.

## 북극성 아키텍처

```
[Orchestrator 관제]            ← 전체 사이클 통제. 결정론 우선, LLM 최소
        ↓
[Dispatcher 자원배분/패킷]      ← 학습/추론 잡 큐 + claude-usage.json 예산 게이트
        ↓
[Explorer 발굴] ↔ [연구/기획]   ← 신규 피처·모델 변형 후보 제안 (LLM 그라운딩)
        ↓
[모듈 에이전트 풀]
  ├ Data Agent        ← 기존: daily_prices · supply_demand · us_lead · news_collector (네이버 교차검증)
  ├ Feature Agent     ← 기존+확장: scoring/sector/mtf/target 산출물을 표준 피처로
  ├ Model Agent       ← 신규: LSTM · Transformer · XGBoost · Diffusion (다양성=경쟁의 원천)
  ├ Ensemble Agent    ← 신규: retrain_weights 일반화 → per-agent 가중 합성
  ├ Risk&Backtest     ← 기존+확장: regime_analogs(닷컴) · target_engine · PIT 백테스트
  └ Evaluation Agent  ← 기존 씨앗: signal_outcomes → per-agent 실현알파 채점
        ↓
[Arena 통합평가/경쟁]           ← 적자생존 진화 루프의 심장
        ↓
[지식공유 DB + Schema]          ← apollo_db 의 factory_* 테이블
```

## 계층 ↔ MOON STOCK 자산 매핑

| 계층 | 상태 | 재사용 자산 |
|------|------|-------------|
| Data Agent | 기존 | `daily_prices`, `supply_demand.py`, `us_lead.py`, `news_collector.py` |
| Feature Agent | 기존+확장 | `scoring_engine`, `sector_rotation`, `mtf_analysis`, `target_engine` 산출물 |
| Model Agent | **신규** | (없음) — LSTM/XGBoost부터 |
| Ensemble | **신규** | `retrain_weights.py`(로지스틱 회귀)를 per-agent로 일반화 |
| Risk&Backtest | 기존+확장 | `regime_analogs.py`, `target_engine.py` |
| Evaluation | 씨앗 존재 | `signal_outcomes` 테이블 |
| Arena/Orchestrator/Dispatcher/Explorer | **신규** | — |

## 불가침 원칙 (메모리 규칙 준수)

1. **라이브 무수정**: 매매·추천·네이버 교차검증 경로 그대로. 팩토리는 `factory_*` 테이블에만 쓴다.
2. **데이터 정확성 우선**: 외부 데이터는 네이버 교차검증 통과분만. 무데이터는 N/A.
3. **예산 규율**: LLM은 Orchestrator/Dispatcher/Explorer에서만. 결정론으로 가능한 건 결정론.
4. **결정론 재현성**: 모든 예측은 입력 피처 스냅샷(`features` JSON)과 함께 저장 → 재현·진화 가능.

## 설계 원칙 (헌법 — 2026-06 합의)

자기수정 자율 시스템이 돈을 다루므로 원칙=헌법. *어기면 팩토리가 자신 있게 틀리게 되는* 것만 담음.

### 잠금 원칙 (비협상)
1. **PIT 무결성이 신성하다** — 모든 예측은 `as_of`+피처 스냅샷과 저장, 채점은 `as_of` 시점 데이터만. 누설=진화가 허구를 최적화.
2. **섀도 우선, 영향력은 획득** — 라이브 권한 0 출발, 아웃오브샘플 실적으로만 승급.
3. **결정론 코어, LLM은 가장자리** — 채점 수치는 결정론·재현. LLM은 추론·발굴·서술만.
4. **출처·재현성** — 예측은 (에이전트버전+config+피처스냅샷)으로 재구성 가능.
5. **기권은 1급 행동** — 결측·정체·NaN이면 조작 대신 기권(FLAT/무예측). 지어내지 않음.
6. **격리·실패 무관통** — 에이전트 크래시/타임아웃은 그 사이클 기권·감점, 아레나는 안 멈춤.
7. **감사가능성** — 모든 승급/강등/은퇴/스폰은 근거 증거와 함께 로깅.
8. **계약만이 결합** — 모듈 탈착은 코어 무수정.

### 결정된 갈림길
- **B1 적합도 = 리스크조정 실현 알파(비용 차감).** IR형 `mean(alpha)/std(alpha)` (recency 반감기 가중), 연산/LLM/회전 비용 차감. **캘리브레이션(Brier)은 2차 게이트**(미달 시 가중치 캡, 1차 선택자는 아님).
- **B2 선택 압력 = 적응적.** 표본 충분성/국면 전환에 cadence 연동.
  - **단서(소데이터 가드, 비협상)**: `N_eff`(반감기 가중 실현표본) < 임계 → **보수 모드 강제**(은퇴 없음·가중치 준균등·누적만). `N_eff` 충족 후에만 승급/강등 활성, 국면 전환·추정 분산 낮을 때 스폰/도태 가속. **즉사 없음**(은퇴는 가능하면 ≥1개 국면 걸친 지속 관찰 후).
- **B3 협력 = 탈상관 적극 보상.** 합성 가중 = f(적합도) × 탈상관 조정. 고적합 에이전트와 예측이 강상관인 에이전트는 가중 축소(그리디 탈상관 선택). 상관만 높은 에이전트는 가치 0.

### 가드레일
- **국면 맹목 방지** — 적합도는 국면 조건부 채점(`market_compass`/`regime_analogs` 태그를 `as_of`에 저장). "최근 상승장 행운" 에이전트의 패권 차단. B1·B2 위에 얹히는 가드.

## 기술 스택 (확정 — 윈도우 단일머신)

> 배포 지평 = 현 윈도우 노트북 유지(2026-06 결정). 엔터프라이즈/클라우드 스택은 시기상조 —
> 라이트사이즈로 가고, 아래 "졸업 트리거" 충족 시에만 중량급 도구를 켠다.

| 레이어 | 채택 | 비고 |
|--------|------|------|
| 에이전트 FW | 자작 `contracts`+`registry` + 평범한 Python | AutoGen/CrewAI 드롭(예산). LangGraph는 Orchestrator/Explorer LLM부에 한해 후순위 |
| 병렬 | `joblib` / `concurrent.futures` | Ray/Dask 보류(단일노드·윈도우 베타) |
| 실험·튜닝 | **MLflow(로컬 sqlite+파일) + Optuna** | 유일한 신규 키퍼. Phase 3에서 도입 |
| 백테스트 | 누설통제 경량 PIT 자작 + 필요시 vectorbt(OSS) | VectorBT Pro 라이선스 보류 |
| 파이프라인 | Windows Task Scheduler(기존) | Airflow 드롭(윈도우 비공식). 복잡 DAG시 Dagster |
| 저장소 | MySQL `apollo_db`(기존) + 로컬 FS `D:\AI\pipeline`(기존) | Postgres/ClickHouse/S3 보류 |
| 배포 | 프로세스 + Task Scheduler | K8s/Argo 드롭 |

신규 의존성(MLflow/Optuna/joblib)은 도입 시 CLAUDE.md 규칙대로 `bootstrap.ps1`에 추가.

**졸업 트리거**: Ray/Dask←2번째 머신+학습 병목 / ClickHouse←분·틱 수천심볼 / Dagster←DAG 의존성 Task Scheduler 한계 / K8s+Postgres+S3←리눅스 서버·클라우드 이전(한 묶음).

## 빌드 로드맵

- **Phase 0 — 기반 (현재)**: Agent 계약(`contracts.py`) + 레지스트리(`registry.py`) + 지식 스키마(`models.py`).
- **Phase 1 — Arena 섀도**: 기존 엔진을 계약으로 래핑 → `factory_predictions` 적재 시작. per-agent 성과 누적.
- **Phase 2 — Ensemble/Evaluation**: 실현알파로 채점 → 가중 합성. retrain_weights 일반화.
- **Phase 3 — Model Agent**: XGBoost/LSTM → Transformer/Diffusion. Explorer가 변형 스폰.
- **Phase 4 — 진화 루프**: 적자생존(강등/은퇴/자손) + Orchestrator/Dispatcher 자동 관제.

## 핵심 데이터 계약

모든 에이전트는 동일한 `Prediction`을 emit한다(아래 필드). 이것이 경쟁(같은 잣대로 비교)과
탈착(계약만 지키면 합류)의 전제다.

```
agent_name, agent_version, stock_code, as_of(예측 시점),
horizon_days(1/5/20...), direction(UP/DOWN/FLAT),
expected_return, confidence(0~1), rationale, features(재현용 스냅샷)
```

진화 연료: `factory_outcomes` 가 horizon 도래 후 실현 수익률/알파/적중을 채점 →
`factory_agents.weight` 가 시간에 따라 적자생존으로 갱신된다.
