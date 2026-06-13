# 글로벌 매크로 투자심리 지수 파이프라인 — 설계 스펙

> 상태: **설계 확정 (구현 미착수)**
> 작성: 2026-06-13 / 메인 조율 세션
> 목적: 글로벌 투자심리 종합지수(8대 점수, 0~100)를 결정론 계산해 `market_compass`에 통합한다.
> 원칙: 모든 수치는 결정론 레이어가 산출, LLM은 해석만. 외부 데이터는 원천값 명시, 무데이터는 N/A.
> 이 문서는 구현 세션이 **본 대화 컨텍스트 없이** 작업할 수 있도록 입·출력과 공식을 고정한다.

---

## 0. 전체 구조

```
① 수집(global_macro_feeds.py) → ② 점수엔진(global_macro.py) → ③ 저장(models.py 신규 테이블)
   → ④ 통합(market_compass.py 확장) → ⑤ 출력(기존 LLM 5~12단계 + CompassReport)
```

신규 파일 2개(`global_macro_feeds.py`, `global_macro.py`), 기존 확장 3곳(`models.py`,
`market_compass.py`, `scripts/fundamentals_sync.py` + 예약작업).

기존 코드 검증 결과: `market_compass.py:142 _stage2_macro_map(macro)`가 이미 VIX·WTI·US10Y·
원달러·나스닥을 소비 중. 글로벌 레이어는 이 dict를 **확장**하고, regime 판정(`_stage1_market_regime`)
**직전**에 `_stage0_global_sentiment`를 삽입한다(글로벌 Risk-On/Off가 국내 판정에 선행).

---

## 1. 수집 레이어 — `backend/global_macro_feeds.py` (신규)

모든 수집 함수는 **실패 시 예외를 던지지 않고** 해당 필드를 `None`으로 반환한다(데이터 정확성 원칙:
잘못된 값보다 N/A). httpx 사용(기존 모듈과 동일), 타임아웃 10초, 캐시는 호출측(`global_macro.py`)에서 관리.

### 1.1 예측시장 (무인증 읽기)

| 소스 | 엔드포인트 | 추출 |
|------|-----------|------|
| Polymarket | `https://gamma-api.polymarket.com/markets?closed=false&...` | 대상 이벤트의 `outcomePrices` (Yes 확률) |
| Kalshi | `https://external-api.kalshi.com/trade-api/v2/markets?limit=...` | `yes_bid`/`yes_ask` 중간값 |
| Metaculus | `https://www.metaculus.com/api2/questions/{id}/` | `community_prediction.full.q2` (중앙값) |

**추적 이벤트 매핑** (`PREDICTION_TARGETS` 상수로 고정 — slug/ticker/id는 구현 시 실제 조회로 확정):
- 미국 경기침체 (2026년 내) → 경기·위험선호 점수 입력
- Fed 금리 인하/인상 (차기 FOMC) → 유동성 점수 입력
- 지정학(이란/중동 분쟁 종결·확전) → 지정학 점수 입력
- 인플레이션 임계(헤드라인 CPI > X%) → 인플레이션 점수 입력

각 타깃은 `{key, polymarket_slug, kalshi_ticker, metaculus_id, feeds_into}` 구조.
3소스 모두 조회 실패 시 해당 key는 N/A → 점수엔진이 중립(50)으로 폴백하고 `evidence`에 'N/A' 기록.

함수: `fetch_prediction_consensus() -> dict[str, {polymarket, kalshi, metaculus, consensus, n_sources}]`

### 1.2 글로벌 시장 데이터 (yfinance, 기존 의존성)

```
VIX=^VIX  DXY=DX-Y.NYB  US10Y=^TNX  US2Y=^IRX(대용, 2Y는 ZT=F/FRED DGS2)
WTI=CL=F  Brent=BZ=F  Gold=GC=F  Copper=HG=F
SP500=^GSPC  NASDAQ=^IXIC  Russell=^RUT  KOSPI=^KS11  KOSDAQ=^KQ11
BTC=BTC-USD  ETH=ETH-USD
```

함수: `fetch_market_internals() -> dict` — 각 심볼의 `last`, `chg5d_pct`, `chg20d_pct`.
US10Y-US2Y 스프레드(장단기 역전 여부)도 파생 계산. yfinance 미설치 시 전체 None + 로그.

### 1.3 경제지표 (예상 대비)

FRED API(키 선택) 또는 BLS 공개 릴리스. 최소: CPI(YoY), Core CPI, PPI, 실업률, GDP(QoQ 연율), ISM 제조업.
각 지표는 `{actual, consensus, surprise}` — surprise = sign(actual - consensus) ∈ {+1, 0, -1}.
consensus 미확보 시 surprise=0(부합 처리)·`note='no consensus'`.

함수: `fetch_econ_surprises() -> dict[str, {actual, consensus, surprise}]`

### 1.4 뉴스 감성

기존 `news_collector.py` 재사용. Reuters/Bloomberg 헤드라인을 5점 척도로 분류:
매우긍정 +2 / 긍정 +1 / 중립 0 / 부정 -1 / 매우부정 -2. 분류는 LLM이 아닌 키워드+기존 파이프라인.
함수: `fetch_news_sentiment() -> {score_avg, n, by_topic}` (topic = 경기/인플레/지정학/AI).

---

## 2. 점수 엔진 — `backend/global_macro.py` (신규)

### 2.1 진입점

```python
def compute_global_macro(force=False) -> dict
```
캐시 TTL은 market_compass와 동일 규칙(`장중 30분 / 장외 8시간`). 반환:

```json
{
  "asof": "2026-06-13T...",
  "scores": {"liquidity":33,"growth":51,"inflation":28,"ai_cycle":78,
             "geopolitics":30,"risk_appetite":52,"us_equity":..,"kr_equity":..},
  "composite": 45,
  "flow": "중립",
  "probabilities": {"1w":{"up":60,"down":40},"1m":{"up":52,"down":48},"3m":{"up":45,"down":55}},
  "kr_sectors": {"반도체":80,"AI":75,"방산":72,"조선":68,"바이오":50,"2차전지":38,"금융":35},
  "inputs": {...원천값 그대로...},
  "evidence": {"liquidity":["CPI 4.2%→Fed 동결","US10Y 4.47%"], ...}
}
```

### 2.2 점수 공식 (0~100, 결정론) — 4단계 가중

각 점수 = `clamp(50 + Σ(요소별 기여), 0, 100)`. 50=중립 기준. 기여는 아래 표의 룰로 계산하고,
사용한 모든 원천값을 `evidence[key]`에 문자열로 적재(출력에서 그대로 노출).

| 점수 | 주요 입력 | 가산(+)/감산(−) 룰 |
|------|----------|-------------------|
| 유동성 | Fed 인하확률, US10Y, DXY, 실질금리 | 인하확률↑ +, US10Y↑ −, DXY↑(달러강세=긴축) − |
| 경기 | GDP surprise, 실업률, ISM, 침체확률 | GDP 상회 +, 실업↑ −, ISM>50 +, 침체확률↑ − |
| 인플레이션 | CPI surprise, Core CPI, WTI 5d, 에너지 | **점수↑=물가안정**. CPI 상회 −, 유가↑ −, Core 가속 − |
| AI 사이클 | 빅테크 Capex 추세, 반도체 모멘텀, 나스닥 20d | Capex 가이던스↑ +, SOX/나스닥↑ +, NVIDIA 수주 + |
| 지정학 | 예측시장 분쟁확률, 뉴스(지정학), Gold | **점수↑=리스크완화**. 분쟁확률↑ −, Gold 급등 −, 휴전헤드라인 + |
| 위험선호 | VIX, 신용스프레드 대용, BTC, SP500 신고가 | VIX<20 +, BTC↑ +, SP신고가 +, VIX>25 − |
| 미국 증시 | SP500/나스닥/러셀 모멘텀, 위험선호, 유동성 | 지수 모멘텀 + 위험선호·유동성 가중 합성 |
| 한국 증시 | KOSPI/KOSDAQ 모멘텀, 원달러, 미국증시 동조, 반도체 | 미국증시×0.4 + 반도체 + 환율 효과 |

**예측시장 가중치(1단계, 고정): Polymarket 0.4 · Kalshi 0.4 · Metaculus 0.2.**
3소스 중 일부만 가용 시 가용분으로 재정규화(예: Kalshi 결측 → Poly 0.667·Meta 0.333).

### 2.3 종합(composite) · 자금흐름 · 확률

- composite = 8점수의 가중평균(가중치 상수 `COMPOSITE_WEIGHTS`, 합 1.0; 기본 균등 후 튜닝).
- flow ∈ {매우약세<20, 약세<40, 중립<60, 강세<80, 매우강세} — composite 구간 매핑.
- 확률(1w/1m/3m): 위험선호·유동성·모멘텀의 함수. **결정론 공식**으로 산출하고 표본/근거를 함께 반환
  (빈도 기반 원칙 — 향후 `macro_sentiment_daily` 축적 시 과거 유사국면 빈도로 교체).

### 2.4 한국 섹터 매핑

`kr_sectors`는 8점수 → 7섹터 영향으로 변환. 반도체·AI=AI사이클×위험선호, 방산·조선=지정학역수×경기,
2차전지=금리역수×경기, 금융=유동성×경기, 바이오=중립 기준. 룰은 `KR_SECTOR_RULES` 상수.

---

## 3. 저장 — `backend/models.py` (기존 확장)

```python
class MacroSentimentDaily(Base):       # 일별 8점수 + composite + flow + 확률 + inputs(JSON)
    trade_date (PK), liquidity, growth, inflation, ai_cycle, geopolitics,
    risk_appetite, us_equity, kr_equity, composite, flow, prob_json, inputs_json, created_at

class PredictionMarketDaily(Base):     # 이벤트별 확률 시계열
    id(PK), trade_date, target_key, polymarket, kalshi, metaculus, consensus, n_sources
    UNIQUE(trade_date, target_key)
```

`db_init.py`는 admin만 시드 — 신규 테이블은 빈 상태로 시작(real-data-only 원칙). 마이그레이션은
기존 방식대로 `Base.metadata.create_all` 경로 사용.

---

## 4. 통합 — `backend/market_compass.py` (기존 확장)

### 4.1 `_stage2_macro_map(macro)` 확장 (현재 line 142~174)

기존 5개 요소(US10Y·원달러·WTI·나스닥·VIX) 뒤에 글로벌 행 추가:
```python
g = compute_global_macro().get("scores", {})
add("글로벌 위험선호", f"{g['risk_appetite']}/100", [...], "VIX·신용·BTC 종합")
add("글로벌 유동성",   f"{g['liquidity']}/100",     [...], "Fed경로·US10Y·DXY")
add("AI 투자사이클",   f"{g['ai_cycle']}/100",      ["반도체","AI 생태계"], "빅테크 Capex·SOX")
add("지정학 리스크",   f"{g['geopolitics']}/100",   ["방산"] if low else [...], "예측시장·뉴스·Gold")
```
`favors` 매핑은 기존 함수의 패턴(점수 임계로 섹터 선택)을 그대로 따른다.

### 4.2 신규 `_stage0_global_sentiment()` 삽입

`compute_market_compass`(line 339~)의 단계 호출 순서에서 `_stage1_market_regime` **직전**에 호출.
반환 dict를 결과 페이로드의 `globalSentiment` 키로 싣고, `_stage1` 입력에 `global` 인자로 전달해
국내 regime 판정이 글로벌 Risk-On/Off를 참조하도록 한다(과긍정/과부정 보정).

### 4.3 LLM 컨텍스트(5~12단계)

`_SYSTEM_PROMPT` 변경 없음. context_json에 `globalSentiment` 블록만 추가 →
LLM은 8점수와 확률을 **근거로만** 사용(환각 수치 금지, 기존 제약 유지).

---

## 5. 스케줄 — `scripts/fundamentals_sync.py` + 예약작업 (기존 확장)

06:00 `fundamentals_sync` 체인 끝에 `compute_global_macro(force=True)` 호출 →
`MacroSentimentDaily` / `PredictionMarketDaily` upsert. 별도 예약작업 불필요(기존 06:00 체인 합류).
장중 갱신은 market_compass 캐시 호출 시 자동(30분 TTL).

---

## 6. 검증 체크리스트 (구현 세션용)

- [ ] 3개 예측시장 API 실엔드포인트 응답 확인 + `PREDICTION_TARGETS` slug/ticker/id 실조회 확정
- [ ] yfinance 16종 심볼 실데이터 수신(특히 DXY=DX-Y.NYB, US2Y 대용 확정)
- [ ] 각 점수 0~100 clamp·N/A 폴백(중립 50) 동작
- [ ] 예측시장 가중치 결측 재정규화(0.4/0.4/0.2 → 가용분)
- [ ] `_stage2_macro_map` 확장이 기존 5행을 깨지 않음(회귀)
- [ ] `_stage0` 삽입 후 market_compass 캐시/TTL 정상
- [ ] 신규 테이블 create_all + upsert UNIQUE 제약
- [ ] 모든 출력 수치에 원천값 evidence 동반(데이터 정확성 원칙)

## 7. 미결 결정사항 (구현 전 확정 필요)

1. `COMPOSITE_WEIGHTS` 8점수 가중치 — 균등 시작 vs 위험선호·유동성 가중.
2. 확률 산출 공식 — 초기 결정론 함수 → 데이터 축적 후 빈도 기반 전환 시점.
3. FRED API 키 사용 여부(경제지표 자동화 vs 수동 입력 폴백).
4. 예측시장 추적 이벤트 최종 목록(현재 4개 → 확장 여부).
