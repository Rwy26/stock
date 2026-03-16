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
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-mysql.ps1 -RootPassword "<root비번>" -AppPassword "<apollo비번>"
```

- 운영 서버처럼 Windows 서비스로 상시 실행하려면 관리자 권한(관리자 터미널/VS Code)이 필요합니다.

Windows 서비스로 MySQL 상시 실행 + `apollo_db`/계정 생성(관리자 권한 필요):
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-mysql-service.ps1
```

## 2) 한번에 점검 (스크립트)

아래 스크립트가 런타임 설치 여부/버전을 출력합니다.

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-env.ps1
```

- 만약 `pwsh`가 인식되지 않으면: 새 터미널을 열어 PATH를 갱신하거나 `C:\Program Files\PowerShell\7\pwsh.exe`로 실행하세요.
- 만약 `python`이 Microsoft Store로 연결되면(WindowsApps 별칭): Windows 설정에서 App Execution Alias를 끄거나, `py -3`를 사용하세요.

## 3) 프로젝트 부트스트랩 (런타임 설치 후)

런타임 설치가 끝나면 다음 스크립트로 프론트엔드(Vite React TS)와 백엔드(FastAPI) 기본 골격을 생성합니다.

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```


## 실행 방법

### 1) 백엔드(FastAPI) 실행 (포트 5001)

Windows PowerShell에서 워크스페이스 루트(`c:\stock`) 기준:

- `powershell -ExecutionPolicy Bypass -File .\scripts\run-backend.ps1`

확인:

- `http://127.0.0.1:5001/health`
- `http://127.0.0.1:5001/api/recommendations`

### 2) 프론트(React/Vite) 실행 (포트 3001)

- `powershell -ExecutionPolicy Bypass -File .\scripts\run-frontend.ps1`

프론트는 Vite 프록시로 백엔드에 연결합니다:

- `/api/*` → `http://127.0.0.1:5001`

## 4) 다음 단계

- 프론트엔드: `frontend-prototype` UI를 React 라우팅 페이지로 1:1 이식
- 백엔드: 요구사항의 엔드포인트를 mock → 실데이터(KIS/MySQL) 순으로 단계적 연결
