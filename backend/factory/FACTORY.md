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
