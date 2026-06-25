# Windows 스케줄 태스크 등록/수정 (scheduled-task)

MOON STOCK 스케줄 태스크를 등록하거나 수정할 때 따르는 체크리스트.

## 필수 체크리스트

### 등록/수정 전
- [ ] 기존 태스크 설정 백업 (`schtasks /query /tn "태스크명" /fo LIST /v`)
- [ ] 전원 설정 확인: `DisallowStartIfOnBatteries` 값

### 등록 시 반드시 포함
```powershell
$settings = New-ScheduledTaskSettingsSet `
    -DisallowStartIfOnBatteries $false `   # 반드시 False
    -StopIfGoingOnBatteries $false `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew            # 동시 인스턴스 방지
```

### 등록 후 검증
- [ ] `DisallowStartIfOnBatteries` = False 재확인
- [ ] 전원/절전 설정 변경 여부 확인
- [ ] 테스트 실행: `Start-ScheduledTask -TaskName "태스크명"`
- [ ] 로그 확인

## 스크립트 필수 패턴
```python
# 백엔드 헬스 게이트
import httpx
try:
    r = httpx.get("http://127.0.0.1:5001/health", timeout=10)
    r.raise_for_status()
except Exception as e:
    print(f"백엔드 미응답, 건너뜀: {e}")
    sys.exit(0)

# 동시 실행 방지 락 파일
import fcntl / msvcrt (Windows)
```
