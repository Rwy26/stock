[CmdletBinding()]
param(
  [string]$TaskName = 'stock-git-auto-save'
)

$ErrorActionPreference = 'Stop'

try {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
  Write-Host "Removed Scheduled Task: $TaskName"
}
catch {
  if ($_.Exception.Message -match 'cannot find the file specified|No mapping between account names|The system cannot find the file specified') {
    Write-Host "Scheduled Task not found (nothing to remove): $TaskName"
    exit 0
  }
  throw
}
