[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [switch]$Uninstall = $false
)

$ErrorActionPreference = 'Stop'

$taskName = 'MOON-STOCK-PublicSnapshots'

Set-Location (Split-Path $PSScriptRoot -Parent)
$repoRoot = $PWD.Path

$pyExe  = Join-Path $repoRoot 'backend\.venv\Scripts\python.exe'
$script = Join-Path $repoRoot 'scripts\build_public_snapshots.py'

if ($Uninstall) {
  if ($PSCmdlet.ShouldProcess($taskName, 'Unregister scheduled task')) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output ("Unregistered task: {0}" -f $taskName)
  }
  return
}

if (-not (Test-Path $pyExe)) { throw "venv python not found: $pyExe (run scripts/bootstrap.ps1 first)" }
if (-not (Test-Path $script)) { throw "build script not found: $script" }

# 30분 간격, 06:00~24:00. 공유(게스트) 읽기 계층 정적 스냅샷 — AI 그래프 등.
$trigger = New-ScheduledTaskTrigger -Once -At '06:00' `
  -RepetitionInterval (New-TimeSpan -Minutes 30) `
  -RepetitionDuration (New-TimeSpan -Hours 18)

$action = New-ScheduledTaskAction `
  -Execute $pyExe `
  -Argument ('"{0}"' -f $script) `
  -WorkingDirectory $repoRoot

$settings = New-ScheduledTaskSettingsSet `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
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
    -Description '30분 간격(06:00~24:00) 공유 계층 정적 스냅샷 생성 — AI 그래프 등 게스트 읽기 전용. 산출: backend/static/snapshots/public-*.json. 로그: logs/public-snapshots.log' `
    -Force | Out-Null

  Write-Output ("Registered task: {0}" -f $taskName)
  Write-Output 'Schedule: every 30 min, 06:00-24:00 KST'
  $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  if ($task) { Write-Output ("State   : {0}" -f $task.State) }
}
