[CmdletBinding()]
param(
  [switch]$Detach = $true,
  [switch]$ForceRestart = $false,
  [int]$Port = 8000,
  [int]$TimeoutSec = 20
)

$ErrorActionPreference = 'Stop'

Set-Location (Split-Path $PSScriptRoot -Parent)

$pythonExe = Join-Path $PWD 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) {
  throw "backend venv python not found: $pythonExe"
}

function Get-Listeners([int]$p) {
  @(Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

function Get-ListenerPids([int]$p) {
  @(Get-Listeners -p $p | ForEach-Object { [int]$_.OwningProcess } | Where-Object { $_ -gt 0 } | Sort-Object -Unique)
}

function Test-Health([int]$p) {
  try {
    $h = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $p) -TimeoutSec 3
    return ($h.ok -eq $true)
  } catch {
    return $false
  }
}

function Get-ProcessSummary([int]$processId) {
  try {
    $w = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
    if ($w) {
      return ("PID={0} NAME={1} CMD={2}" -f $processId, $w.Name, $w.CommandLine)
    }
  } catch {
    # ignore
  }
  return ("PID={0}" -f $processId)
}

$existingPids = Get-ListenerPids -p $Port
if ($existingPids.Count -gt 0) {
  if ($ForceRestart) {
    foreach ($processId in $existingPids) {
      try { Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue } catch {}
    }
  } else {
    if (Test-Health -p $Port) {
      Write-Output ("Already running: http://127.0.0.1:{0}" -f $Port)
      foreach ($processId in $existingPids) {
        Write-Output (Get-ProcessSummary -processId $processId)
      }
      exit 0
    }

    throw (
      "Port {0} is in use but /health check failed. Use -ForceRestart to reclaim the port. Current listeners: {1}" -f
      $Port,
      (($existingPids | ForEach-Object { Get-ProcessSummary -processId $_ }) -join '; ')
    )
  }
}

$args = @('-m', 'uvicorn', 'main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', ("{0}" -f $Port))

if ($Detach) {
  $proc = Start-Process -FilePath $pythonExe -ArgumentList $args -PassThru -WindowStyle Hidden

  $deadline = [DateTime]::UtcNow.AddSeconds([Math]::Max(1, $TimeoutSec))
  while ([DateTime]::UtcNow -lt $deadline) {
    Start-Sleep -Milliseconds 250
    if (Test-Health -p $Port) {
      Write-Output ("Started backend (detached): http://127.0.0.1:{0}" -f $Port)
      Write-Output ("Launcher PID={0}" -f $proc.Id)
      exit 0
    }

    try {
      if ($proc.HasExited) {
        throw ("Backend process exited early with code {0}" -f $proc.ExitCode)
      }
    } catch {
      throw $_
    }
  }

  try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
  throw ("Backend did not become healthy within {0}s on port {1}." -f $TimeoutSec, $Port)
}

& $pythonExe @args
