[CmdletBinding()]
param(
  [switch]$SkipWindowsUpdateScan
)

$ErrorActionPreference = 'Stop'

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "optimize-performance-$ts.txt"

function Log([string]$message) {
  $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $message
  $line | Out-File -FilePath $logPath -Append -Encoding utf8
  Write-Host $line
}

function TryRun([string]$label, [scriptblock]$action) {
  try {
    Log "RUN: $label"
    $output = & $action 2>&1 | Out-String
    if ($output.Trim().Length -gt 0) {
      Log ("OUT: {0}" -f $output.Trim())
    }
    Log "OK: $label"
  }
  catch {
    Log "WARN: $label failed: $($_.Exception.Message)"
  }
}

Log "==== Optimize Performance (AC) ===="

$isAdmin = $false
try {
  $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
  $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
}
catch { }
Log ("Admin: {0}" -f $isAdmin)

# --- Power plan ---
$powerList = (powercfg /list) 2>&1 | Out-String
Log "Power schemes:\n$powerList"

$highPerfGuid = $null
foreach ($line in ($powerList -split "`r?`n")) {
  if ($line -match '([0-9a-fA-F\-]{36}).*(\(고성능\)|\(High performance\))') {
    $highPerfGuid = $matches[1]
    break
  }
}

if (-not $highPerfGuid) {
  Log "High performance scheme not found; duplicating Balanced."
  $dup = (powercfg -duplicatescheme SCHEME_BALANCED) 2>&1 | Out-String
  Log $dup.Trim()
  if ($dup -match '([0-9a-fA-F\-]{36})') {
    $highPerfGuid = $matches[1]
    TryRun "Rename scheme" { powercfg -changename $highPerfGuid "OMEN Performance" "Performance-first AC profile" | Out-Null }
  }
}

if ($highPerfGuid) {
  TryRun "Activate power scheme $highPerfGuid" { powercfg /setactive $highPerfGuid | Out-Null }
}
else {
  Log "WARN: Could not determine a performance power scheme GUID. Using SCHEME_CURRENT only."
}

# Apply AC-focused settings to current scheme
TryRun "Processor min 100 (AC)" { powercfg -setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMIN 100 | Out-Null }
TryRun "Processor max 100 (AC)" { powercfg -setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX 100 | Out-Null }
TryRun "Cooling policy Active (AC)" { powercfg -setacvalueindex SCHEME_CURRENT SUB_PROCESSOR SYSTEMCOOLINGPOLICY 0 | Out-Null }
TryRun "Energy Performance Preference 0 (AC)" { powercfg -setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PERFEPP 0 | Out-Null }
TryRun "Boost mode Aggressive (AC)" { powercfg -setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PERFBOOSTMODE 2 | Out-Null }

TryRun "PCIe Link State Power Management Off (AC)" { powercfg -setacvalueindex SCHEME_CURRENT SUB_PCIEXPRESS ASPM 0 | Out-Null }
TryRun "USB selective suspend Disabled (AC)" { powercfg -setacvalueindex SCHEME_CURRENT SUB_USB USBSELECTIVE 0 | Out-Null }

TryRun "Commit power settings" { powercfg /setactive SCHEME_CURRENT | Out-Null }

# --- Gaming-related OS toggles (non-invasive) ---
TryRun "Enable Game Mode (HKCU)" {
  New-Item -Path 'HKCU:\Software\Microsoft\GameBar' -Force | Out-Null
  New-ItemProperty -Path 'HKCU:\Software\Microsoft\GameBar' -Name 'AutoGameModeEnabled' -PropertyType DWord -Value 1 -Force | Out-Null
  New-ItemProperty -Path 'HKCU:\Software\Microsoft\GameBar' -Name 'AllowAutoGameMode' -PropertyType DWord -Value 1 -Force | Out-Null
}

TryRun "Enable Hardware-accelerated GPU scheduling (HAGS) (HKLM)" {
  New-Item -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers' -Force | Out-Null
  New-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers' -Name 'HwSchMode' -PropertyType DWord -Value 2 -Force | Out-Null
}

# --- Windows Update readiness (for drivers/firmware stability) ---
TryRun "Set Windows Update services to Manual" {
  Set-Service -Name wuauserv -StartupType Manual
  Set-Service -Name bits -StartupType Manual
}
TryRun "Start Windows Update services" {
  Start-Service -Name wuauserv -ErrorAction SilentlyContinue
  Start-Service -Name bits -ErrorAction SilentlyContinue
}

if (-not $SkipWindowsUpdateScan) {
  TryRun "Trigger update scan (UsoClient StartScan)" {
    $uso = Get-Command UsoClient.exe -ErrorAction Stop
    & $uso.Source StartScan | Out-Null
  }
}

Log "Done. Log: $logPath"
Log "NOTE: HAGS change typically requires reboot to take effect."
