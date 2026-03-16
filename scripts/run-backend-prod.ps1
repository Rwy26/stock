param(
  [switch]$Detach = $false
)

$ErrorActionPreference = 'Stop'

Set-Location (Split-Path $PSScriptRoot -Parent)

$pythonExe = Join-Path $PWD 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) {
  throw "backend venv python not found: $pythonExe"
}

$args = @('-m', 'uvicorn', 'main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', '5001')

if ($Detach) {
  function Get-ListenerProcessInfo {
    $c = Get-NetTCPConnection -LocalPort 5001 -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $c) { return $null }
    $w = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" -ErrorAction SilentlyContinue
    if (-not $w) { return $null }
    return [PSCustomObject]@{ Pid = $c.OwningProcess; ParentPid = $w.ParentProcessId; CommandLine = $w.CommandLine }
  }

  function Is-DescendantProcess([int]$childPid, [int]$ancestorPid) {
    $cur = $childPid
    for ($i = 0; $i -lt 10; $i++) {
      if ($cur -eq $ancestorPid) { return $true }
      $w = Get-CimInstance Win32_Process -Filter "ProcessId=$cur" -ErrorAction SilentlyContinue
      if (-not $w) { return $false }
      $parent = [int]$w.ParentProcessId
      if ($parent -le 0 -or $parent -eq $cur) { return $false }
      $cur = $parent
    }
    return $false
  }

  for ($attempt = 1; $attempt -le 2; $attempt++) {
    $existing = Get-ListenerProcessInfo
    if ($existing) {
      throw "Port 5001 is already in use by PID $($existing.Pid). Stop it first."
    }

    $p = Start-Process -FilePath $pythonExe -ArgumentList $args -PassThru -WindowStyle Hidden

    # Wait until the listener appears and validate that it's owned by the started process.
    $ok = $false
    for ($i = 0; $i -lt 50; $i++) {
      Start-Sleep -Milliseconds 200
      $listener = Get-ListenerProcessInfo
      if ($listener) {
        if (Is-DescendantProcess -childPid ([int]$listener.Pid) -ancestorPid ([int]$p.Id)) {
          $ok = $true
        }
        break
      }
    }

    if ($ok) {
      Write-Output "Started backend (detached) PID=$($p.Id) http://127.0.0.1:5001"
      exit 0
    }

    # If something else grabbed the port, clean up and retry once.
    $listener = Get-ListenerProcessInfo
    $listener = Get-ListenerProcessInfo
    if ($listener -and (-not (Is-DescendantProcess -childPid ([int]$listener.Pid) -ancestorPid ([int]$p.Id)))) {
      Stop-Process -Id $listener.Pid -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
  }

  throw "Failed to start backend on 5001 using venv python."
}

# Production-style run: no auto-reload.
& $pythonExe @args
