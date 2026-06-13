[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [switch]$Uninstall = $false
)

$ErrorActionPreference = 'Stop'

$ingestTask    = 'MOON-STOCK-Gap-Signals-Ingest'
$reconcileTask = 'MOON-STOCK-Gap-Signals-Reconcile'

Set-Location (Split-Path $PSScriptRoot -Parent)
$repoRoot = $PWD.Path

$pyExe  = Join-Path $repoRoot 'backend\.venv\Scripts\python.exe'
$script = Join-Path $repoRoot 'scripts\ingest_gap_signals.py'

if ($Uninstall) {
  if ($PSCmdlet.ShouldProcess("$ingestTask, $reconcileTask", 'Unregister scheduled tasks')) {
    Unregister-ScheduledTask -TaskName $ingestTask    -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $reconcileTask -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output ("Unregistered tasks: {0}, {1}" -f $ingestTask, $reconcileTask)
  }
  return
}

if (-not (Test-Path $pyExe))  { throw "venv python not found: $pyExe (run scripts/bootstrap.ps1 first)" }
if (-not (Test-Path $script)) { throw "ingest script not found: $script" }

$settings = New-ScheduledTaskSettingsSet `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
  -UserId ([Environment]::UserName) `
  -LogonType Interactive `
  -RunLevel Limited

# 1) 적재: 매일 09:05 KST (장 시작 09:00 직후 — 시초가 갭 확정)
if ($PSCmdlet.ShouldProcess($ingestTask, 'Register scheduled task')) {
  Register-ScheduledTask `
    -TaskName $ingestTask `
    -Trigger (New-ScheduledTaskTrigger -Daily -At '09:05') `
    -Action  (New-ScheduledTaskAction -Execute $pyExe -Argument ('"{0}"' -f $script) -WorkingDirectory $repoRoot) `
    -Settings $settings -Principal $principal `
    -Description '매일 09:05 KST 시초가 갭 신호 적재 — premarket-scanner JSON → 네이버 siseJson 재확인 후 DB. 제외는 exclusion_engine 경유. 로그: logs/ingest_gap_signals.log' `
    -Force | Out-Null
  Write-Output ("Registered task: {0} (daily 09:05)" -f $ingestTask)
}

# 2) 재확인: 매일 16:15 KST (daily_prices 16:10 이후 — 확정 일봉 기준 갭/가격 재확인)
if ($PSCmdlet.ShouldProcess($reconcileTask, 'Register scheduled task')) {
  Register-ScheduledTask `
    -TaskName $reconcileTask `
    -Trigger (New-ScheduledTaskTrigger -Daily -At '16:15') `
    -Action  (New-ScheduledTaskAction -Execute $pyExe -Argument ('"{0}" --reconcile' -f $script) -WorkingDirectory $repoRoot) `
    -Settings $settings -Principal $principal `
    -Description '매일 16:15 KST 시초가 갭 신호 재확인 — 확정 daily_prices(siseJson) 기준 갭/가격 재확인·등급 갱신. 로그: logs/ingest_gap_signals.log' `
    -Force | Out-Null
  Write-Output ("Registered task: {0} (daily 16:15)" -f $reconcileTask)
}
