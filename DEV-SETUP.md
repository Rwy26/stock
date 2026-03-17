# 실운영/개발 환경 준비 (Windows)

이 문서는 Apollo(SongStock2) 개발을 실운영 환경에서 진행하기 위한 **필수 런타임 설치**와 **검증 절차**를 제공합니다.

## 1) 필수 런타임

### Node.js (프론트엔드)
- 권장: Node.js **LTS(20.x 이상)**

설치(Windows, winget):
```powershell
winget install -e --id OpenJS.NodeJS.LTS --source winget --accept-package-agreements --accept-source-agreements
```

검증:
```powershell
node -v
npm -v
```

### Python (백엔드)
- 요구사항 기준: Python **3.10+** (권장 3.11)

설치(Windows, winget):
```powershell
winget install -e --id Python.Python.3.11 --source winget --accept-package-agreements --accept-source-agreements
```

검증:
```powershell
py -3 --version
py -3 -m pip --version
```

### Git (권장)
```powershell
winget install -e --id Git.Git --source winget --accept-package-agreements --accept-source-agreements
```

### MySQL 8.0 (요구사항)
- 실운영 DB가 이미 있다면 설치 생략 가능
- 로컬 설치(옵션):
```powershell
winget install -e --id Oracle.MySQL --source winget --accept-package-agreements --accept-source-agreements
```

로컬 운영환경(DB `apollo_db`) 초기화/생성(관리자 권한 없이 로컬 인스턴스 실행):
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-mysql.ps1
```

- 위 명령은 비밀번호를 **SecureString 프롬프트**로 받습니다.
- 비대화식 실행이 필요하면(프롬프트 없이) 아래 중 하나를 사용하세요:

SecureString 전달(권장):
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-mysql.ps1 `
	-RootPassword (ConvertTo-SecureString "<root비번>" -AsPlainText -Force) `
	-AppPassword (ConvertTo-SecureString "<apollo비번>" -AsPlainText -Force) `
	-NoPrompt
```

Plaintext escape hatch(자동화 용도, 주의):
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-mysql.ps1 `
	-RootPasswordText "<root비번>" -AppPasswordText "<apollo비번>" -NoPrompt
```

Dry-run(변경 없이 계획만 출력):
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-mysql.ps1 -WhatIf -NoPrompt
```

- 운영 서버처럼 Windows 서비스로 상시 실행하려면 관리자 권한(관리자 터미널/VS Code)이 필요합니다.

Windows 서비스로 MySQL 상시 실행 + `apollo_db`/계정 생성(관리자 권한 필요):
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-mysql-service.ps1
```

- 이미 MySQL 서비스가 실행 중인데(예: `MySQL84`가 Running) **관리자 권한이 없는 경우**, DB/계정 생성 + `backend/.env` 작성만 수행할 수 있습니다:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-mysql-service.ps1 -DbOnly
```

- 만약 서비스 시작 실패가 발생하면(초기화/설정 오류 등) 다음처럼 **데이터 디렉터리 재초기화**로 복구합니다(관리자 권한 필요):

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-mysql-service.ps1 -ReinitDataDir
```

- 위 스크립트는 **관리자 권한**이 필요합니다(관리자 PowerShell/관리자 VS Code에서 실행).
- 비대화식 실행(프롬프트 없이 비번 전달)도 지원합니다:

```powershell
.\scripts\setup-mysql-service.ps1 -RootPassword (ConvertTo-SecureString "<root비번>" -AsPlainText -Force) -AppPassword (ConvertTo-SecureString "<apollo비번>" -AsPlainText -Force) -NoPrompt
```

Dry-run(변경 없이 계획만 출력):
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-mysql-service.ps1 -WhatIf
```

또는 (권장) 서비스 설치 + 스키마 생성까지 한 번에(관리자 권한 필요):

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\provision-mysql-service-and-schema.ps1
```

DB 스키마(테이블) 생성/검증:

1) `backend/.env` 준비
	- 권장: 위 `setup-mysql-service.ps1`가 자동으로 `backend/.env`를 작성합니다.
	- 수동: [backend/.env.example](backend/.env.example) 를 복사해 `backend/.env`로 만들고 값을 채웁니다.

2) 테이블 생성:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\init-db.ps1
```

3) 연결 확인(백엔드 실행 후):

- `http://127.0.0.1:5001/api/db/health`

## 2) 한번에 점검 (스크립트)

아래 스크립트가 런타임 설치 여부/버전을 출력합니다.

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-env.ps1
```

- 만약 `pwsh`가 인식되지 않으면: 새 터미널을 열어 PATH를 갱신하거나 `C:\Program Files\PowerShell\7\pwsh.exe`로 실행하세요.
- 만약 `python`이 Microsoft Store로 연결되면(WindowsApps 별칭): Windows 설정에서 App Execution Alias를 끄거나, `py -3`를 사용하세요.

## (선택) PowerShell 프로필로 AI 캐시 환경변수 자동 적용

AI 개발용 캐시/임시폴더를 D:로 쓰기 위해 User 환경변수를 설정했다면, 새 PowerShell 세션 시작 시 자동으로 반영되도록 프로필에 동기화 블록을 설치할 수 있습니다:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-pwsh-profile-ai-cache.ps1
```

- 이 설정은 새로 여는 PowerShell/VS Code 터미널에 자동 적용됩니다.
- `-NoProfile`로 시작한 세션에는 적용되지 않습니다.

## 3) 프로젝트 부트스트랩 (런타임 설치 후)

런타임 설치가 끝나면 다음 스크립트로 프론트엔드(Vite React TS)와 백엔드(FastAPI) 기본 골격을 생성합니다.

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```


## 실행 방법

## (권장) 로컬 운영형 세팅 한방에

DB(.env 포함) + 스키마 + 프론트 빌드 + 백엔드(5001) 상주까지 한 번에 수행:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-local-prod.ps1
```

이미 5001 포트에 다른 서버가 떠 있으면(예: 시스템 Python으로 띄운 uvicorn) 다음 옵션으로 강제 재시작:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-local-prod.ps1 -ForceRestartBackend
```

- `backend/.env`가 없으면 MySQL 비밀번호를 프롬프트로 받습니다.
- 이미 `backend/.env`가 있으면 `JWT_SECRET`, `JWT_EXPIRE_MINUTES`가 없을 때만 자동으로 추가합니다.
- 백엔드는 `run-backend-prod.ps1 -Detach`로 상주 실행됩니다.

### 1) 백엔드(FastAPI) 실행 (포트 5001)

Windows PowerShell에서 워크스페이스 루트(`c:\stock`) 기준:

- `powershell -ExecutionPolicy Bypass -File .\scripts\run-backend.ps1`

운영 형태(정적 서빙 포함)로 **재시작 없이 실행(--reload 없음)**:

- `powershell -ExecutionPolicy Bypass -File .\scripts\run-backend-prod.ps1`

확인:

- `http://127.0.0.1:5001/health`
- `http://127.0.0.1:5001/api/recommendations`

### 2) 프론트(React/Vite) 실행 (포트 3001)

- `powershell -ExecutionPolicy Bypass -File .\scripts\run-frontend.ps1`

프론트는 Vite 프록시로 백엔드에 연결합니다:

- `/api/*` → `http://127.0.0.1:5001`

### 3) 운영 형태(단일 서버)로 실행 (백엔드가 프론트 정적 서빙)

개발 서버(Vite)가 아니라 **빌드 산출물(frontend/dist)** 을 FastAPI가 정적으로 서빙합니다.

1) 프론트 빌드:

```powershell
Set-Location .\frontend
npm run build
Set-Location ..
```

2) 백엔드 실행:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-backend.ps1
```

3) 접속:

- `http://127.0.0.1:5001/` (프론트)
- `http://127.0.0.1:5001/health`
- `http://127.0.0.1:5001/api/recommendations`

## 4) 다음 단계

- 프론트엔드: `frontend-prototype` UI를 React 라우팅 페이지로 1:1 이식
- 백엔드: 요구사항의 엔드포인트를 mock → 실데이터(KIS/MySQL) 순으로 단계적 연결
