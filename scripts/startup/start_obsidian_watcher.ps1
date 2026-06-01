$ErrorActionPreference = "SilentlyContinue"

$pythonPath = "C:\Users\MOON\ai 프로젝트\.venv\Scripts\python.exe"
$scriptPath = "C:\Users\MOON\ai 프로젝트\scripts\obsidian_watcher.py"
$logPath = "C:\stock\logs\watcher-autostart.log"

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logPath -Value "$timestamp`t$Message"
}

# Exit quietly if dependencies are missing.
if (-not (Test-Path $pythonPath)) {
    Write-Log "python not found: $pythonPath"
    exit 0
}
if (-not (Test-Path $scriptPath)) {
    Write-Log "script not found: $scriptPath"
    exit 0
}

# Prevent duplicate watcher processes.
$alreadyRunning = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -ieq "python.exe" -and $_.CommandLine -match [regex]::Escape($scriptPath)
}
if ($alreadyRunning) {
    exit 0
}

$arg = '"' + $scriptPath + '"'
$proc = Start-Process -FilePath $pythonPath -ArgumentList $arg -WindowStyle Hidden -WorkingDirectory (Split-Path -Parent $scriptPath) -PassThru
Start-Sleep -Seconds 2

if ($proc.HasExited) {
    Write-Log "watcher failed, exit code: $($proc.ExitCode)"
    exit 0
}

Write-Log "watcher started"
