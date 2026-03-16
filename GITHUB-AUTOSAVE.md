# GitHub 저장 + 1시간 자동 저장(Windows)

이 저장소(c:\stock)를 GitHub에 올리고, 이후 로컬 변경사항을 **1시간마다 자동으로 commit+push** 하도록 설정합니다.

## 0) 보안 주의

- `backend/.env` 같은 **비밀값 파일은 절대 커밋하지 마세요**.
- 이 repo는 기본적으로 `.env`, `logs/` 등을 `.gitignore`로 제외합니다.

## 1) GitHub CLI 로그인(최초 1회)

```powershell
Set-Location c:\stock
gh auth login -h github.com -p https -w
```

브라우저 인증이 끝나면:

```powershell
gh auth status
```

## 2) GitHub에 repo 생성 + 첫 push

아래 스크립트는 현재 폴더를 GitHub repo로 만들고(`origin` remote 생성), 현재 브랜치를 push 합니다.

```powershell
Set-Location c:\stock
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\publish-to-github.ps1 -Repo "OWNER/REPO"  # 예: moon/stock
```

- 공개 repo로 만들려면 `-Public` 옵션을 추가합니다.

## 3) 1시간마다 자동 commit(+push) 설정

### 3-1) 자동 commit만 (push는 수동)

```powershell
Set-Location c:\stock
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-git-auto-save-task.ps1
```

### 3-2) 자동 commit + 자동 push

GitHub remote 설정이 완료된 뒤 실행하세요:

```powershell
Set-Location c:\stock
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-git-auto-save-task.ps1 -Push
```

작업 스케줄러(Task Scheduler)에 `stock-git-auto-save`가 등록되고, 1시간마다 실행됩니다.

## 4) 수동 실행 / 제거

- 즉시 한 번 실행:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\git-auto-save.ps1 -RepoPath c:\stock -Push
```

- 자동 저장 작업 제거:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\uninstall-git-auto-save-task.ps1
```

## 5) 주의사항

- PC가 꺼져있거나 절전이면 해당 시간에 실행되지 않습니다(다음 부팅 후 `StartWhenAvailable`로 따라잡을 수 있음).
- 네트워크/인증 문제로 push가 실패하면 작업이 실패로 남습니다(작업 스케줄러 기록 확인).
- 같은 파일을 여러 PC에서 동시에 작업하면 충돌(conflict)이 날 수 있으니 주의하세요.
