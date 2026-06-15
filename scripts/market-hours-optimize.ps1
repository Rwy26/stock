# 영웅문4 장중 최우선 정책 — 경쟁 프로세스 우선순위 조정
# 사용법: -Start (09:00 실행) / -Stop (15:31 실행)
param([switch]$Start, [switch]$Stop)

$procs    = @("python", "uvicorn", "node")
$logSrc   = "MOON-STOCK"

# EventLog 소스가 없으면 등록 (관리자 권한 필요, 최초 1회)
if (-not [System.Diagnostics.EventLog]::SourceExists($logSrc)) {
    try {
        New-EventLog -LogName Application -Source $logSrc -ErrorAction Stop
    } catch {
        # 권한 부족 시 무시 — 이벤트 로그 없이도 기능 동작
    }
}

if ($Start) {
    foreach ($pname in $procs) {
        Get-Process -Name $pname -ErrorAction SilentlyContinue |
            ForEach-Object {
                try { $_.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal }
                catch { }
            }
    }
    Write-EventLog -LogName Application -Source $logSrc -EventId 9001 `
        -EntryType Information `
        -Message "장중 우선순위 조정 완료 (BelowNormal) — 영웅문4 최우선 모드" `
        -ErrorAction SilentlyContinue
    Write-Host "[MOON-STOCK] 장중 모드: python/uvicorn/node → BelowNormal"
}

if ($Stop) {
    foreach ($pname in $procs) {
        Get-Process -Name $pname -ErrorAction SilentlyContinue |
            ForEach-Object {
                try { $_.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::Normal }
                catch { }
            }
    }
    Write-EventLog -LogName Application -Source $logSrc -EventId 9002 `
        -EntryType Information `
        -Message "장중 우선순위 복구 완료 (Normal)" `
        -ErrorAction SilentlyContinue
    Write-Host "[MOON-STOCK] 장후 복구: python/uvicorn/node → Normal"
}
