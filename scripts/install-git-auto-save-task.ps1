[CmdletBinding()]
param(
  [string]$RepoPath = 'C:\stock',
  [string]$TaskName = 'stock-git-auto-save',
  [int]$EveryMinutes = 60,
  [switch]$Push = $true
)

$ErrorActionPreference = 'Stop'

# Ensure TEMP/TMP point to an existing directory (scheduled tasks and some tooling can fail otherwise).
try {
  $fallbackTemp = Join-Path $env:LOCALAPPDATA 'Temp'
  if (-not (Test-Path $fallbackTemp)) {
    New-Item -ItemType Directory -Force -Path $fallbackTemp | Out-Null
  }
  if (-not $env:TEMP -or -not (Test-Path $env:TEMP)) { $env:TEMP = $fallbackTemp }
  if (-not $env:TMP -or -not (Test-Path $env:TMP)) { $env:TMP = $fallbackTemp }
}
catch { }

if (-not (Test-Path $RepoPath)) {
  throw "RepoPath not found: $RepoPath"
}

$scriptPath = Join-Path $RepoPath 'scripts\git-auto-save.ps1'
if (-not (Test-Path $scriptPath)) {
  throw "Missing script: $scriptPath"
}

$pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source

$taskArgumentList = @(
  '-NoProfile',
  '-ExecutionPolicy', 'Bypass',
  '-File', "`"$scriptPath`"",
  '-RepoPath', "`"$RepoPath`"",
  '-MessagePrefix', 'auto-save'
)
if ($Push) { $taskArgumentList += '-Push' }

$action = New-ScheduledTaskAction -Execute $pwsh -Argument ($taskArgumentList -join ' ') -WorkingDirectory $RepoPath

# Start 1 minute from now, then repeat every N minutes for a long duration.
# Note: The ScheduledTasks cmdlet only supports repetition with the -Once trigger parameter set.
$start = (Get-Date).AddMinutes(1)
$trigger = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew

# Run as current user (no password prompt), only when logged on
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal

# Replace if exists
try {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
}
catch { }

Register-ScheduledTask -TaskName $TaskName -InputObject $task | Out-Null

Write-Host "Installed Scheduled Task: $TaskName"
Write-Host "- RepoPath: $RepoPath"
Write-Host "- Interval: every $EveryMinutes minutes"
Write-Host "- Push: $Push"
Write-Host 'Tip: use Task Scheduler UI to view last run result/output.'
