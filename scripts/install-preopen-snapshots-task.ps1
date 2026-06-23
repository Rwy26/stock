[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [switch]$Uninstall = $false
)

$ErrorActionPreference = 'Stop'

$taskName = 'MOON-STOCK-PreopenSnapshots'

Set-Location (Split-Path $PSScriptRoot -Parent)
$repoRoot = $PWD.Path

$pyExe  = Join-Path $repoRoot 'backend\.venv\Scripts\python.exe'
$script = Join-Path $repoRoot 'scripts\build_preopen_snapshots.py'

if ($Uninstall) {
  if ($PSCmdlet.ShouldProcess($taskName, 'Unregister scheduled task')) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output ("Unregistered task: {0}" -f $taskName)
  }
  return
}

if (-not (Test-Path $pyExe)) { throw "venv python not found: $pyExe (run scripts/bootstrap.ps1 first)" }
if (-not (Test-Path $script)) { throw "build script not found: $script" }

# 06:10 KST — US 선행 동기화(MOON-STOCK-US-Leaders-Sync 06:05) 직후·KR 개장(09:00) 전.
# us_lead(DB만 읽음, KIS/LLM 미호출)로 개장 전 선행 스냅샷을 가장 이른 시점에 떨군다.
$trigger = New-ScheduledTaskTrigger -Daily -At '06:10'

$action = New-ScheduledTaskAction `
  -Execute $pyExe `
  -Argument ('"{0}"' -f $script) `
  -WorkingDirectory $repoRoot

$settings = New-ScheduledTaskSettingsSet `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
  -UserId ([Environment]::UserName) `
  -LogonType Interactive `
  -RunLevel Limited

if ($PSCmdlet.ShouldProcess($taskName, 'Register scheduled task')) {
  Register-ScheduledTask `
    -TaskName $taskName `
    -Trigger $trigger `
    -Action $action `
    -Settings $settings `
    -Principal $principal `
    -Description '매일 06:10 KST(US 동기화 직후·KR 개장 전) 개장 전 선행 스냅샷 생성 — US 야간→KR 익일 선행(반도체/AI)+현재 장세. 산출: backend/static/snapshots/preopen-lead.json. 로그: logs/preopen-snapshots.log' `
    -Force | Out-Null

  Write-Output ("Registered task: {0}" -f $taskName)
  Write-Output 'Schedule: daily 06:10 KST (after US sync 06:05, before KR open 09:00)'
  $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  if ($task) { Write-Output ("State   : {0}" -f $task.State) }
}
