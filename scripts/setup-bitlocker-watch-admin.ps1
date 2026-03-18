[CmdletBinding()]
param(
  [string]$RepoPath = 'C:\stock',
  [string]$TaskName = 'stock-bitlocker-watch'
)

$ErrorActionPreference = 'Stop'

Set-Location C:\

Write-Host "[1/3] Installing task..."
& (Join-Path $RepoPath 'scripts\install-bitlocker-watch-task.ps1') -RepoPath $RepoPath | Out-Host

Write-Host "[2/3] Triggering task once..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 5

Write-Host "[3/3] Task info:"
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName,TaskPath,State | Format-List | Out-Host
Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object LastRunTime,LastTaskResult,NextRunTime | Format-List | Out-Host

$logPath = Join-Path $RepoPath 'logs\bitlocker-watch.log'
if (Test-Path $logPath) {
  Write-Host "Log tail: $logPath"
  Get-Content $logPath -Tail 50 | Out-Host
} else {
  Write-Host "Log file not found yet: $logPath"
}
