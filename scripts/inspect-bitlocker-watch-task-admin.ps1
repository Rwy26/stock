[CmdletBinding()]
param(
  [string]$TaskName = 'stock-bitlocker-watch',
  [string]$OutPath = 'C:\stock\logs\bitlocker-watch-task-inspect.txt'
)

$ErrorActionPreference = 'Continue'

try { Set-Location C:\ } catch { }

$outDir = Split-Path -Parent $OutPath
if ($outDir -and -not (Test-Path $outDir)) {
  New-Item -ItemType Directory -Force -Path $outDir | Out-Null
}

function W([string]$s) { $s | Out-File -FilePath $OutPath -Append -Encoding utf8 }

"Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File -FilePath $OutPath -Encoding utf8
W "===== schtasks /Query ====="
try { cmd /c "schtasks /Query /TN $TaskName /V /FO LIST" 2>&1 | Out-File -FilePath $OutPath -Append -Encoding utf8 } catch { W "ERROR: $_" }

W "===== Get-ScheduledTask ====="
try {
  $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  $t | Select-Object TaskName,TaskPath,State | Format-List | Out-String | Out-File -FilePath $OutPath -Append -Encoding utf8
  W "-- Actions --"
  $t.Actions | Format-List | Out-String | Out-File -FilePath $OutPath -Append -Encoding utf8
  W "-- Triggers --"
  $t.Triggers | Format-List | Out-String | Out-File -FilePath $OutPath -Append -Encoding utf8
} catch {
  W "ERROR: $($_)"
}

W "===== Run once ====="
try {
  Start-ScheduledTask -TaskName $TaskName
  Start-Sleep -Seconds 6
  $info = Get-ScheduledTaskInfo -TaskName $TaskName
  $info | Select-Object LastRunTime,LastTaskResult,NextRunTime | Format-List | Out-String | Out-File -FilePath $OutPath -Append -Encoding utf8
} catch {
  W "ERROR: $($_)"
}

W "===== Log tail ====="
$log = 'C:\stock\logs\bitlocker-watch.log'
if (Test-Path $log) {
  Get-Content $log -Tail 80 | Out-File -FilePath $OutPath -Append -Encoding utf8
} else {
  W "Log file not found: $log"
}
