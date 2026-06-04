# Watchlist Algorithm Reimplementation Prompt

아래 요구사항을 만족하도록 관심종목 시스템을 재구현하라.

## 목표

현재 `c:\stock` 프로젝트의 관심종목 알고리즘을 다른 VS Code 작업공간에서도 동일하게 동작하도록 구현한다.

반드시 재현해야 하는 범위는 아래와 같다.

1. 사용자가 종목명 또는 종목코드로 관심종목을 수동 추가할 수 있어야 한다.
2. 사전 정의된 테마 규칙으로 관심종목을 자동 갱신할 수 있어야 한다.
3. 종목명/종목코드는 DB 문자열만 믿지 말고 KIS와 Google Finance로 검증해야 한다.
4. 관심종목 조회 시 `name`, `code`, `price`, `changeRate`, `score`, `sector`, `icon`을 반환해야 한다.
5. 자동 테마 항목은 `replace=true`일 때 이번 스냅샷에서 빠진 종목을 제거해야 한다.

## 구현 범위

다음 백엔드 요소를 구현하라.

1. 종목 마스터 `stocks`
2. 사용자 관심종목 `watchlist`
3. 관심 메타데이터 `stock_interest`
4. 사용자별 KIS 프로필 `kis_profiles`
5. 최신 점수 조회용 `indicator_scores`

## 필수 데이터 모델

최소 필드는 아래와 같다.

### `stocks`
- `code` PK
- `name`
- `market`

### `watchlist`
- `user_id`
- `stock_code`
- `created_at`
- unique `(user_id, stock_code)`

### `stock_interest`
- `user_id`
- `stock_code`
- `mention_count`
- `interest_weight`
- `analysis_depth`
- `tags` JSON array
- unique `(user_id, stock_code)`

### `kis_profiles`
- `user_id`
- `app_key`
- `app_secret`
- `account_prefix`

### `indicator_scores`
- `stock_code`
- `scoring_date`
- `score_total`

## 핵심 구현 규칙

### 1. 수동 추가 규칙

입력은 `code`, `query`, `input` 중 먼저 존재하는 값을 사용한다.

수동 추가 순서:

1. 입력 문자열 정리
2. 종목 검증기 호출
3. 검증 성공 시 `stocks` upsert
4. `watchlist`에 insert if absent
5. 기존 `stocks.name`이 코드 placeholder이거나 KIS 이름과 다르면 교정

중요:

1. 수동 추가에서는 테마 별칭 fallback을 사용하면 안 된다.
2. 종목 확정은 반드시 검증기 결과를 따라야 한다.

### 2. 종목 검증기 구현 규칙

`resolve_stock_input_via_kis`에 해당하는 로직을 구현하라.

#### 코드 입력인 경우

1. 길이 6 영숫자면 코드 입력으로 간주
2. KIS `inquire_price(code)` 호출
3. KIS `name`, `market_name` 확보
4. Google Finance `https://www.google.com/finance/quote/{code}:{exchange}?hl=ko` 조회
5. `<title>`에서 `종목명(종목코드) 주가 및 뉴스 - Google Finance` 패턴 파싱
6. KIS 이름과 Google 이름이 모두 비어 있으면 실패
7. KIS와 Google 이름이 모두 있고 서로 다르면 실패
8. 하나 또는 둘 다 성공하면 검증 성공

반환 필드:

- `code`
- `name`
- `market`
- `verified`
- `inputType`
- `verificationSources`
- `verificationMessage`

#### 이름 입력인 경우

1. 입력 종목명 정규화
2. DB에서 후보군 검색
3. 후보별 KIS 조회
4. 후보별 Google Finance 조회
5. 이름 유사도 계산
6. 아래 조건 중 하나를 만족한 후보만 통과

통과 조건:

1. KIS와 Google 정규화 이름이 동일
2. KIS 이름 없음 + Google 유사도 >= 0.96
3. Google 이름 없음 + KIS 유사도 >= 0.96
4. KIS 유사도 >= 0.92 그리고 Google 유사도 >= 0.92

최종 판정:

1. 통과 후보 1개면 성공
2. 통과 후보 2개 이상이면 409
3. 통과 후보는 없지만 라이브 후보 여러 개면 409
4. 아무것도 확정 못 하면 404

## 테마 자동 갱신 구현

`POST /api/watchlist/theme-update`를 구현하라.

입력:

- `replace` 기본값 `true`

정적 규칙 구조:

```json
{
  "sector": "외국인 코스닥",
  "flow": "외국인",
  "market": "코스닥",
  "names": ["제주반도체", "원익IPS"]
}
```

### 테마 별칭 규칙

테마 자동 갱신에만 아래 같은 이름-코드 별칭 테이블을 허용한다.

```json
{
  "제주반도체": "080220",
  "원익IPS": "240810",
  "하나머티리얼즈": "166090",
  "ISC": "095340",
  "에프에스티": "036810",
  "한국피아이엠": "477010",
  "한국항공우주": "047810",
  "한화시스템": "272210",
  "비나텍": "126340",
  "LS마린솔루션": "060370",
  "우리기술": "032820"
}
```

규칙:

1. 먼저 별칭을 확인
2. 별칭이 있으면 그 코드로 KIS 검증 시도
3. KIS 검증 실패 시에만 자동 갱신 경로에서 `ManualThemeAlias`로 반영
4. 수동 추가 API에는 이 fallback 금지

### 자동 갱신 처리 순서

1. 모든 규칙 순회
2. 각 종목명을 테마 전용 해석기로 resolve
3. 실패한 이름은 `unresolved` 배열에 추가
4. 성공한 종목은 `stocks` upsert
5. `watchlist` 없으면 추가
6. `stock_interest` upsert
7. `managed_codes`에 추가
8. `replace=true`면 기존 `테마자동` 항목 중 이번 `managed_codes`에 없는 항목 삭제

### 저장해야 할 태그

반드시 아래 구조 유지:

1. `{sector}|테마`
2. `아이콘|{icon}`
3. `테마자동`
4. `{flow}수급`
5. `{market}시장`

예시:

```json
[
  "외국인 코스닥|테마",
  "아이콘|🌍",
  "테마자동",
  "외국인수급",
  "코스닥시장"
]
```

### `stock_interest` 갱신 규칙

신규 생성 시:

- `mention_count = 1`
- `interest_weight = 1.2`
- `analysis_depth = 2`
- `tags = new_tags`

기존 갱신 시:

- 새 태그를 앞에 두고 기존 태그 중 중복되지 않은 것만 뒤에 병합
- `mention_count += 1`
- `analysis_depth = max(existing, 2)`
- `interest_weight = min(5.0, max(existing, 1.0 + 0.18 * mention_count))`

## 관심종목 조회 API

`GET /api/watchlist`를 구현하라.

응답:

```json
{
  "items": [
    {
      "name": "대한전선",
      "code": "001440",
      "price": 12345,
      "changeRate": 2.13,
      "score": 71,
      "sector": "기관 코스피",
      "icon": "⚡"
    }
  ]
}
```

조회 순서:

1. `watchlist + stocks + stock_interest` 조인
2. 종목별 실시간 가격과 등락률 조회
3. 종목별 최신 `score_total` 조회
4. 태그에서 섹터 추출
5. 태그 또는 아이콘맵에서 아이콘 추출
6. 응답 배열 생성

### 섹터 추출 규칙

아래 태그는 섹터로 쓰지 않는다.

- `외국인수급`
- `기관수급`
- `아이콘|...`
- `테마자동`
- `...시장`

나머지 첫 번째 태그 head를 섹터로 사용한다.

### 아이콘 추출 우선순위

1. 태그 내부 `아이콘|...`
2. 종목명 기준 아이콘맵
3. 섹터 기준 아이콘맵
4. fallback 아이콘

## 아이콘 설정 파일

별도 JSON 설정 파일을 두고 아래 구조를 사용하라.

```json
{
  "stocks": {
    "삼성전자": "📱",
    "한국항공우주": "🛰"
  },
  "sectors": {
    "반도체": "💾",
    "외국인 코스닥": "🌍",
    "기관 코스피": "🏛"
  },
  "fallback": "⬤"
}
```

## 프론트엔드 요구사항

1. `GET /api/watchlist` 응답을 사용
2. 각 종목을 타일형 히트맵으로 렌더링
3. 색상은 `changeRate` 기반
4. 크기는 점수/강도 기반
5. 작은 타일은 축약 이름 사용 가능
6. 섹터와 아이콘이 화면에 드러나야 함

## 반드시 금지할 것

1. DB 종목명만으로 종목 확정 금지
2. 테마 별칭 fallback을 수동 추가 API에 적용 금지
3. `watchlist`만 저장하고 `stock_interest.tags` 생략 금지
4. Google Finance 검증 실패를 성공으로 간주 금지
5. KIS와 Google 이름 불일치를 자동 통과시키는 것 금지

## 권장 구현 순서

1. 데이터 모델 작성
2. KIS 프로필 저장 기능 작성
3. 종목 검증기 작성
4. 수동 추가 API 작성
5. 아이콘 설정 파일 로더 작성
6. 테마 규칙 + 테마 별칭 작성
7. 자동 갱신 API 작성
8. 관심종목 조회 API 작성
9. 프론트 히트맵 작성
10. 검증 스크립트 작성

## 완료 기준

아래가 모두 되면 완료로 본다.

1. 종목명/종목코드 수동 추가 가능
2. 잘못된 이름-코드 매칭 자동 차단
3. 테마 자동 갱신 가능
4. `replace=true` 시 오래된 자동 항목 제거 가능
5. 조회 응답에 `name`, `code`, `price`, `changeRate`, `score`, `sector`, `icon` 포함
6. 프론트에서 섹터/아이콘 기반 관심종목 화면 표시 가능

## 출력 형식 요구

작업 시 아래 순서로 진행하라.

1. 필요한 데이터 모델 작성
2. 핵심 검증 함수 작성
3. 수동 추가 API 작성
4. 자동 갱신 API 작성
5. 조회 API 작성
6. 프론트 연결
7. 테스트 또는 검증 코드 작성

구현 후에는 아래를 반드시 보고하라.

1. 생성/수정한 파일 목록
2. API 계약 요약
3. 검증 결과
4. 남은 리스크
