$ErrorActionPreference = "SilentlyContinue"

$pythonPath = "C:\Users\MOON\ai 프로젝트\.venv\Scripts\python.exe"
$scriptPath = "C:\Users\MOON\ai 프로젝트\scripts\obsidian_watcher.py"
$logPath = "C:\stock\logs\watcher-autostart.log"
$maxLogBytes = 1048576

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logPath -Value "$timestamp`t$Message"
}

function Rotate-LogIfNeeded {
    if (Test-Path $logPath) {
        $size = (Get-Item $logPath).Length
        if ($size -ge $maxLogBytes) {
            $archive = "{0}.{1}.bak" -f $logPath, (Get-Date -Format "yyyyMMdd-HHmmss")
            Move-Item -Path $logPath -Destination $archive -Force
        }
    }
}

if (-not (Test-Path (Split-Path -Parent $logPath))) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $logPath) -Force | Out-Null
}

Rotate-LogIfNeeded

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
    $_.Name -ieq "python.exe" -and $_.CommandLine -match "obsidian_watcher\.py"
}
if ($alreadyRunning) {
    $pids = ($alreadyRunning | Select-Object -ExpandProperty ProcessId) -join ","
    Write-Log "watcher already running, skip start, pids=$pids"
    exit 0
}

try {
    $arg = '"' + $scriptPath + '"'
    $proc = Start-Process -FilePath $pythonPath -ArgumentList $arg -WindowStyle Hidden -WorkingDirectory (Split-Path -Parent $scriptPath) -PassThru
    Start-Sleep -Seconds 2

    if ($proc.HasExited) {
        Write-Log "watcher failed, exit code=$($proc.ExitCode), python=$pythonPath"
        exit 0
    }

    Write-Log "watcher started, pid=$($proc.Id), python=$pythonPath"
} catch {
    Write-Log "watcher start exception: $($_.Exception.Message)"
    exit 0
}
