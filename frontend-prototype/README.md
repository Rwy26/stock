# frontend-prototype

요구사항 문서(시스템 매뉴얼)를 기준으로 재미나이 UI 톤앤매너를 적용한 정적 UI 프로토타입입니다.

## 열어보기

- 시작 화면(대시보드): `frontend-prototype/index.html`
- 로그인 화면: `frontend-prototype/login.html`

브라우저에서 파일을 직접 열면 됩니다(서버 없이 동작).

## 화면 목록

- 대시보드: `index.html`
- 포트폴리오: `portfolio.html`
- 종목 탐색: `stock-search.html`
- 추천 종목: `recommendations.html`
- 관심 종목: `watchlist.html`
- 일반 자동매매: `auto-basic.html`
- SA 자동매매: `auto-sa.html`
- Plus 자동매매: `auto-plus.html`
- SV Agent: `sv-agent.html`
- 관리자: `admin.html`

## 제약

현재 작업 환경에 Node/npm, Python/pip 런타임이 없어 실제 API 서버(FastAPI) 구동과 React 빌드는 진행하지 못했습니다.
(런타임이 준비되면, mock JSON → API 연동 → React 컴포넌트화 순서로 이식 가능합니다.)
