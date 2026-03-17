[CmdletBinding()]
param(
  [int]$Port = 5001,
  [int]$WaitMs = 3000
)

$ErrorActionPreference = 'Stop'

function Get-Listeners([int]$p) {
  Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 10
}

$listeners = @(Get-Listeners -p $Port)
if (-not $listeners -or $listeners.Count -eq 0) {
  Write-Output "No listener on :$Port"
  Write-Output 'STOPPED'
  exit 0
}

$pids = @($listeners | ForEach-Object { [int]$_.OwningProcess } | Where-Object { $_ -gt 0 } | Sort-Object -Unique)
foreach ($procId in $pids) {
  try {
    Write-Output "Stopping PID=$procId on :$Port"
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
  } catch {
    # ignore
  }
}

$sw = [System.Diagnostics.Stopwatch]::StartNew()
while ($sw.ElapsedMilliseconds -lt $WaitMs) {
  Start-Sleep -Milliseconds 200
  $left = @(Get-Listeners -p $Port)
  if (-not $left -or $left.Count -eq 0) {
    Write-Output 'STOPPED'
    exit 0
  }
}

$left = @(Get-Listeners -p $Port)
if ($left -and $left.Count -gt 0) {
  $leftPids = @($left | ForEach-Object { [int]$_.OwningProcess } | Sort-Object -Unique)
  Write-Output ("STILL_LISTENING :{0} PID={1}" -f $Port, ($leftPids -join ','))
  exit 1
}

Write-Output 'STOPPED'
exit 0
