# Backend 8000 Startup Automation

## 1) KRX_ID/KRX_PW 자동 반영

스크립트: `scripts/set-krx-env.ps1`

기본 동작:
- 기본은 `backend/.env`만 갱신
- `KRX_ID`, `KRX_PW`를 upsert

예시:

```powershell
cd c:\stock
.\scripts\set-krx-env.ps1
```

참고: 기본 Target은 `BackendEnv`이며, 사용자 환경변수까지 같이 쓰려면 `-Target Both`를 지정한다.

비대화형(파라미터 전달) 예시:

```powershell
cd c:\stock
.\scripts\set-krx-env.ps1 -KrxId "your_krx_id" -KrxPw "your_krx_pw" -Target Both
```

표준입력(STDIN) 기반 비대화형 예시(JSON):

```powershell
cd c:\stock
'{"KRX_ID":"your_krx_id","KRX_PW":"your_krx_pw"}' | .\scripts\set-krx-env.ps1 -FromStdin -NoPrompt -Target Both
```

표준입력(STDIN) 기반 비대화형 예시(env 라인):

```powershell
cd c:\stock
@"
KRX_ID=your_krx_id
KRX_PW=your_krx_pw
"@ | .\scripts\set-krx-env.ps1 -FromStdin -NoPrompt -Target BackendEnv
```

타겟 옵션:
- `BackendEnv`: backend/.env만 갱신
- `UserEnv`: 사용자 환경변수만 갱신
- `Both`: 둘 다 갱신 (기본값)

검증:

```powershell
cd c:\stock
.\scripts\check-krx-env.ps1
```

## 2) 시작프로그램(shell:startup) 자동 등록

설치 스크립트: `scripts/install-backend-8000-startup.ps1`
삭제 스크립트: `scripts/uninstall-backend-8000-startup.ps1`

설치:

```powershell
cd c:\stock
.\scripts\install-backend-8000-startup.ps1
```

설치(부팅 실행 로그 파일 저장):

```powershell
cd c:\stock
.\scripts\install-backend-8000-startup.ps1 -EnableLog
```

로그는 일자별 파일로 저장된다.
- 예: `logs/startup-backend-8000-20260605.log`

로그 경로 사용자 지정:

```powershell
cd c:\stock
.\scripts\install-backend-8000-startup.ps1 -EnableLog -LogDir "D:\AI\logs"
```

삭제:

```powershell
cd c:\stock
.\scripts\uninstall-backend-8000-startup.ps1
```

생성되는 파일:
- `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\MOON-STOCK-Backend-8000.cmd`

이 파일은 로그인 시 `scripts/start-backend-8000.bat`를 호출해 백엔드를 자동 실행한다.

## 3) 수동 기동/종료

기동:

```powershell
cd c:\stock
.\scripts\start-backend-8000.bat
```

종료:

```powershell
cd c:\stock
.\scripts\stop-backend-8000.ps1
```
