# 관심종목 알고리즘 구현 지시서

이 문서는 현재 `c:\stock` 프로젝트의 관심종목 알고리즘을 다른 VS Code 작업공간에서 재구현하기 위한 작업 지시서다.

목표는 "현재와 동일한 방식으로 관심종목을 생성, 검증, 자동 갱신, 조회, 화면 표시"하는 것이다.

## 1. 구현 목표

다음 4가지를 동일하게 재현해야 한다.

1. 사용자가 종목명 또는 종목코드를 입력해 관심종목을 수동 추가할 수 있어야 한다.
2. 사전에 정의된 테마 규칙으로 관심종목을 자동 갱신할 수 있어야 한다.
3. 종목명과 종목코드는 DB만 믿지 말고 KIS와 Google Finance로 검증해야 한다.
4. 관심종목 조회 시 가격, 등락률, 점수, 섹터, 아이콘까지 포함한 응답을 내려야 한다.

## 2. 현재 기준 소스

아래 파일들의 동작을 기준으로 구현한다.

1. `backend/main.py`
2. `backend/models.py`
3. `backend/watchlist_icon_map.json`
4. `frontend/src/pages/WatchlistPage.tsx`

핵심 구현 구간은 아래와 같다.

1. 종목 검증 해석기: `backend/main.py::_resolve_stock_input_via_kis`
2. 관심종목 조회 API: `backend/main.py::get_watchlist`
3. 테마 자동 갱신 API: `backend/main.py::apply_watchlist_theme_update`
4. 수동 추가 API: `backend/main.py::add_watchlist_item`
5. 테마 별칭 표: `backend/main.py::_THEME_WATCHLIST_NAME_ALIASES`
6. 아이콘 설정: `backend/watchlist_icon_map.json`

## 3. 반드시 지켜야 하는 운영 원칙

이 부분은 구현 세부사항보다 더 중요하다.

1. `stocks` 테이블의 이름만 믿고 종목을 확정하면 안 된다.
2. 코드 입력은 KIS로 먼저 확인하고, 가능하면 Google Finance로 교차검증해야 한다.
3. 이름 입력은 DB 후보를 찾은 뒤 KIS와 Google Finance로 다시 검증해야 한다.
4. KIS와 Google Finance 이름이 다르면 자동 확정하면 안 된다.
5. 테마 자동 갱신에서만 수동 별칭을 허용한다.
6. 수동 별칭은 신뢰 가능한 사용자 제공 코드-이름 목록일 때만 사용한다.
7. 수동 추가와 자동 추가는 둘 다 최종적으로 `watchlist`와 `stock_interest`에 반영돼야 한다.

## 4. 필요한 데이터 모델

최소한 아래 테이블이 있어야 한다.

### 4.1 `stocks`

필드

1. `code`: 종목코드, PK
2. `name`: 종목명
3. `market`: 시장 구분

역할

1. 종목 마스터
2. 관심종목 및 가격/점수 데이터의 기준 키

### 4.2 `watchlist`

필드

1. `user_id`
2. `stock_code`
3. `created_at`

역할

1. 사용자별 관심종목 목록 저장
2. 동일 사용자-동일 종목 중복 금지

### 4.3 `stock_interest`

필드

1. `user_id`
2. `stock_code`
3. `mention_count`
4. `interest_weight`
5. `analysis_depth`
6. `tags` JSON 배열

역할

1. 관심종목의 이유와 메타데이터 저장
2. 섹터, 아이콘, 자동관리 여부, 수급 분류를 태그로 저장

### 4.4 `kis_profiles`

필드

1. `user_id`
2. `app_key`
3. `app_secret`
4. `account_prefix`

역할

1. 사용자별 KIS 인증 정보 저장
2. 종목 검증 및 실시간 가격 조회에 사용

### 4.5 `indicator_scores`

필드

1. `stock_code`
2. `scoring_date`
3. `score_total`

역할

1. 관심종목 조회 시 최신 점수 제공

## 5. 외부 의존성

### 5.1 KIS

필수 용도

1. 종목코드 유효성 검증
2. 종목명 확인
3. 시장 정보 확인
4. 실시간 가격/등락률 조회

### 5.2 Google Finance

필수 용도

1. KIS 보조 검증
2. KIS 이름이 비어 있거나 의심스러울 때 교차확인

구현 방식

1. `https://www.google.com/finance/quote/{code}:{exchange}?hl=ko` 요청
2. HTML `<title>`에서 `종목명(종목코드) 주가 및 뉴스 - Google Finance` 패턴 파싱
3. `KRX`와 `KOSDAQ` 두 거래소 후보를 순차 시도

## 6. 관심종목 알고리즘 전체 흐름

관심종목은 아래 순서로 관리한다.

1. 수동 추가
2. 테마 자동 갱신
3. 실시간 조회 응답 생성
4. 프론트엔드 히트맵 렌더링

### 6.1 수동 추가 흐름

입력

1. `code`
2. `query`
3. `input`

세 값 중 먼저 들어온 문자열을 사용한다.

처리 순서

1. 입력 문자열 공백 제거
2. `_resolve_stock_input_via_kis` 호출
3. 결과에서 `code`, `name`, `market` 확보
4. `stocks` 테이블 upsert
5. `watchlist`에 사용자-종목 쌍 삽입

중요 규칙

1. 기존 `stocks.name`이 코드 placeholder이거나 KIS 이름과 다르면 KIS 이름으로 교정한다.
2. 기존 `stocks.market`이 비어 있으면 KIS market 값으로 채운다.
3. 중복 watchlist 삽입은 막는다.

### 6.2 종목 검증기 `_resolve_stock_input_via_kis`

이 함수는 구현의 핵심이다.

#### A. 코드 입력인 경우

판별 규칙

1. 길이 6의 영숫자

처리 순서

1. KIS `inquire_price(code)` 호출
2. KIS에서 `name`, `market_name` 확보
3. Google Finance에서 같은 코드 조회
4. 둘 다 이름이 없으면 실패
5. KIS 이름과 Google 이름이 모두 있는데 서로 다르면 실패
6. 하나 또는 둘 다 성공하면 검증 성공으로 반환

반환값 예시

```json
{
  "code": "001440",
  "name": "대한전선",
  "market": "전기·전자",
  "verified": true,
  "inputType": "code",
  "verificationSources": ["KIS", "GoogleFinance"],
  "verificationMessage": "KIS/Google Finance 교차검증 완료"
}
```

#### B. 종목명 입력인 경우

처리 순서

1. 종목명 정규화
2. DB 후보군 검색 `_select_stock_name_candidates`
3. 후보마다 KIS 조회
4. 후보마다 Google Finance 조회
5. 이름 유사도 계산
6. 아래 조건 중 하나를 만족하는 후보만 검증 통과

통과 조건

1. KIS와 Google 이름이 정규화 기준으로 동일
2. KIS 이름이 없고 Google 이름 유사도 >= 0.96
3. Google 이름이 없고 KIS 이름 유사도 >= 0.96
4. KIS 유사도 >= 0.92 이고 Google 유사도 >= 0.92

최종 판단

1. 검증 통과 후보가 1개면 성공
2. 검증 통과 후보가 2개 이상이면 409 충돌
3. 검증 통과 후보는 없지만 라이브 후보가 여러 개면 409 충돌
4. 아무 후보도 확정 못 하면 404 실패

## 7. 테마 자동 갱신 알고리즘

### 7.1 입력 데이터

정적 규칙 세트가 필요하다.

각 규칙은 아래 구조를 가진다.

```json
{
  "sector": "외국인 코스닥",
  "flow": "외국인",
  "market": "코스닥",
  "names": ["제주반도체", "원익IPS"]
}
```

### 7.2 수동 별칭 테이블

테마 자동 갱신에 한해 아래 같은 이름-코드 별칭 테이블을 둔다.

```json
{
  "제주반도체": "080220",
  "원익IPS": "240810",
  "하나머티리얼즈": "166090"
}
```

규칙

1. 이름을 정규화한 key를 사용한다.
2. 먼저 별칭을 확인한다.
3. 별칭이 있으면 그 코드를 KIS 검증에 넣는다.
4. KIS 검증이 실패하면 테마 자동 갱신에 한해 `ManualThemeAlias`로 반영한다.
5. 수동 추가 API에서는 이 fallback을 쓰면 안 된다.

### 7.3 자동 갱신 처리 순서

API

1. `POST /api/watchlist/theme-update`

입력

1. `replace`: 기본값 `true`

처리 순서

1. 모든 테마 규칙을 순회한다.
2. 각 종목명을 `_resolve_stock_input_for_theme_update`로 해석한다.
3. 해석 실패 시 `unresolved` 배열에 넣는다.
4. 해석 성공 시 `stocks` upsert
5. `watchlist`에 없으면 추가
6. `stock_interest` upsert
7. 태그를 병합한다.
8. `replace=true`면 이번 실행에서 관리되지 않은 `테마자동` 종목은 삭제한다.

### 7.4 자동 갱신 시 저장해야 하는 태그

정확히 아래 패턴을 유지한다.

1. `{sector}|테마`
2. `아이콘|{icon}`
3. `테마자동`
4. `{flow}수급`
5. `{market}시장`

예시

```json
[
  "외국인 코스닥|테마",
  "아이콘|🌍",
  "테마자동",
  "외국인수급",
  "코스닥시장"
]
```

### 7.5 `stock_interest` 갱신 규칙

신규 생성 시

1. `mention_count = 1`
2. `interest_weight = 1.2`
3. `analysis_depth = 2`
4. `tags = new_tags`

기존 row 갱신 시

1. 새 태그를 앞에 두고 기존 태그 중 중복되지 않는 것만 뒤에 붙인다.
2. `mention_count += 1`
3. `analysis_depth = max(existing, 2)`
4. `interest_weight = min(5.0, max(existing, 1.0 + 0.18 * mention_count))`

## 8. 관심종목 조회 응답 알고리즘

API

1. `GET /api/watchlist`

처리 순서

1. `watchlist` + `stocks` + `stock_interest` 조인
2. 종목별 실시간 가격과 등락률 조회
3. 종목별 최신 `score_total` 조회
4. 태그에서 섹터 추출
5. 태그 또는 아이콘맵에서 아이콘 추출
6. 배열 응답 생성

응답 형태

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

### 8.1 섹터 추출 규칙

태그 배열에서 아래 항목은 섹터로 취급하지 않는다.

1. `외국인수급`
2. `기관수급`
3. `아이콘|...`
4. `테마자동`
5. `...시장`

남는 첫 번째 태그 head를 섹터로 사용한다.

### 8.2 아이콘 추출 규칙

우선순위는 아래와 같다.

1. 태그 내부 `아이콘|...`
2. 종목명 기준 아이콘맵
3. 섹터 기준 아이콘맵
4. fallback 아이콘

## 9. 프론트엔드 표시 규칙

관심종목 화면은 단순 표가 아니라 히트맵이다.

필수 규칙

1. `GET /api/watchlist` 응답을 사용한다.
2. 각 종목은 타일 1개로 표시한다.
3. 타일 색은 `changeRate` 기반 빨강/초록 계열로 계산한다.
4. 타일 크기는 점수/강도 기반으로 배분한다.
5. 큰 타일은 긴 이름을, 작은 타일은 축약 이름을 사용한다.
6. 섹터별 그룹 배치와 아이콘 표시를 지원한다.

프론트 구현을 꼭 동일하게 복제할 필요는 없지만, 아래 출력 값은 유지해야 한다.

1. 이름
2. 코드
3. 가격
4. 등락률
5. 점수
6. 섹터
7. 아이콘

## 10. 다른 VS Code에서 구현할 때의 권장 순서

1. 데이터 모델 생성
2. KIS 프로필 저장 기능 준비
3. `stocks`, `watchlist`, `stock_interest` CRUD 생성
4. 종목 검증기 `_resolve_stock_input_via_kis` 구현
5. 수동 추가 API 구현
6. 아이콘 맵 파일 로더 구현
7. 테마 규칙 + 테마 별칭 표 구현
8. 자동 갱신 API 구현
9. 관심종목 조회 API 구현
10. 프론트 히트맵 화면 구현
11. 검증 스크립트 작성

## 11. 구현 체크리스트

아래 항목이 모두 통과해야 현재 구현과 같다고 본다.

### 11.1 수동 추가

1. 코드 입력 시 잘못된 코드면 400 실패
2. 코드 입력 시 KIS와 Google 이름이 다르면 409 또는 실패
3. 이름 입력 시 후보가 여러 개면 409 실패
4. 정상 종목은 `watchlist`에 1회만 저장

### 11.2 자동 갱신

1. 정적 테마 규칙이 관심종목으로 반영됨
2. 별칭 표에 있는 종목은 KIS 미응답이어도 `ManualThemeAlias`로 반영 가능
3. `replace=true`일 때 이번 실행에서 제외된 `테마자동` 종목은 제거됨
4. `unresolved` 배열이 반환됨

### 11.3 조회 응답

1. `items` 배열에 가격, 등락률, 점수, 섹터, 아이콘 포함
2. 태그 기반 섹터 추출이 동작함
3. 아이콘 태그가 없으면 아이콘맵 fallback 동작함

## 12. 구현 시 금지사항

1. 종목명을 DB 문자열 일치만으로 확정하지 말 것
2. 테마 수동 별칭을 수동 추가 API까지 확장하지 말 것
3. `watchlist`만 넣고 `stock_interest` 태그를 생략하지 말 것
4. 프론트에서 섹터와 아이콘을 하드코딩만 하지 말 것
5. Google Finance 파싱 실패를 성공으로 간주하지 말 것

## 13. 최소 구현용 의사코드

```text
manual_add(input):
  resolved = resolve_via_kis(input)
  upsert stock master
  insert watchlist if absent

theme_update(replace=true):
  managed_codes = []
  unresolved = []
  for rule in THEME_RULES:
    for raw_name in rule.names:
      resolved = resolve_for_theme_update(raw_name)
      if not resolved:
        unresolved.append(raw_name)
        continue
      upsert stock master
      upsert watchlist
      upsert stock_interest tags
      managed_codes.append(code)
  if replace:
    remove old auto-managed watchlist items not in managed_codes
  return stats + unresolved

get_watchlist(user):
  rows = join watchlist + stocks + stock_interest
  for row in rows:
    price, change = realtime price lookup
    score = latest indicator score
    sector = extract sector from tags
    icon = extract icon from tags or icon map
    emit item
  return { items }
```

## 14. 완료 기준

다른 VS Code에서 아래가 재현되면 완료다.

1. 사용자가 종목명/코드로 관심종목을 추가할 수 있다.
2. 테마 자동 갱신이 동일한 종목 묶음을 관리한다.
3. 잘못된 종목명-코드 매칭은 자동 차단된다.
4. 관심종목 조회 응답 구조가 동일하다.
5. 프론트 화면에서 섹터와 아이콘이 일관되게 보인다.
