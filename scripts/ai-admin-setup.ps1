[CmdletBinding()]
param(
  [switch]$SkipWindowsUpdateScan
)

$ErrorActionPreference = 'Stop'

function Assert-Admin {
  $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
    throw "관리자 권한이 필요합니다. PowerShell을 '관리자 권한으로 실행' 후 다시 실행하세요."
  }
}

Assert-Admin

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "ai-admin-setup-$ts.txt"

function Log([string]$message) {
  $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $message
  $line | Out-File -FilePath $logPath -Append -Encoding utf8
  Write-Host $line
}

Log "==== AI Admin Setup (Windows / Performance) ===="

# 1) Power plan (keep existing OMEN Performance if present)
try {
  $list = (powercfg /list) 2>&1 | Out-String
  Log "Power schemes:\n$list"
  if ($list -match '([0-9a-fA-F\-]{36}).*\(OMEN Performance\)') {
    $guid = $matches[1]
    Log "Activate: OMEN Performance ($guid)"
    powercfg /setactive $guid | Out-Null
  }
}
catch {
  Log "WARN: powercfg failed: $($_.Exception.Message)"
}

# 2) HAGS (Hardware-accelerated GPU scheduling) -> On
try {
  New-Item -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers' -Force | Out-Null
  New-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers' -Name 'HwSchMode' -PropertyType DWord -Value 2 -Force | Out-Null
  Log "HAGS registry set: HwSchMode=2 (On)"
}
catch {
  Log "WARN: HAGS registry set failed: $($_.Exception.Message)"
}

# 3) Windows Update services
try {
  Set-Service -Name wuauserv -StartupType Manual
  Set-Service -Name bits -StartupType Manual
  Log "Windows Update services set to Manual"
}
catch {
  Log "WARN: Set-Service failed: $($_.Exception.Message)"
}

try {
  Start-Service -Name wuauserv -ErrorAction SilentlyContinue
  Start-Service -Name bits -ErrorAction SilentlyContinue
  Log "Windows Update services started (best-effort)"
}
catch {
  Log "WARN: Start-Service failed: $($_.Exception.Message)"
}

if (-not $SkipWindowsUpdateScan) {
  try {
    & (Get-Command UsoClient.exe).Source StartScan | Out-Null
    Log "Triggered Windows Update scan (UsoClient StartScan)"
  }
  catch {
    Log "WARN: Update scan trigger failed: $($_.Exception.Message)"
  }
}

# 4) Optional: basic drive D diagnostic (read-only)
try {
  Log "Drive D quick check"
  Get-Volume -DriveLetter D | Format-List * | Out-String | Out-File -Append -Encoding utf8 $logPath
  (manage-bde -status D:) 2>&1 | Out-String | Out-File -Append -Encoding utf8 $logPath
}
catch {
  Log "WARN: Drive D check failed: $($_.Exception.Message)"
}

Log "Done. Log: $logPath"
Log "NOTE: HAGS change usually needs reboot."
