[CmdletBinding()]
param(
  [switch]$IncludeLargeOutputs
)

$ErrorActionPreference = 'Continue'

# Improve Unicode output from native commands (wsl/dism/powercfg/etc.)
try {
  $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  [Console]::OutputEncoding = $utf8NoBom
  $OutputEncoding = $utf8NoBom
}
catch { }

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$out = Join-Path $logDir "ai-dev-audit-$ts.txt"

function W([string]$title, [scriptblock]$action) {
  "" | Out-File -Append -Encoding utf8 $out
  ("==== {0} ====" -f $title) | Out-File -Append -Encoding utf8 $out
  try {
    (& $action 2>&1 | Out-String) | Out-File -Append -Encoding utf8 $out
  }
  catch {
    ("ERROR: {0}" -f $_.Exception.Message) | Out-File -Append -Encoding utf8 $out
  }
}

"==== AI Dev Audit ($ts) ====" | Out-File -Encoding utf8 $out

$isAdmin = $false
try {
  $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
  $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
}
catch { }
"Admin: $isAdmin" | Out-File -Append -Encoding utf8 $out

W "System" { Get-ComputerInfo | Select-Object CsManufacturer, CsModel, OsName, OsVersion, OsBuildNumber, WindowsVersion, TimeZone | Format-List }
W "CPU/RAM" { Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed | Format-List; "RAM(GB): $([math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,2))" }
W "BIOS" { Get-CimInstance Win32_BIOS | Select-Object Manufacturer, SMBIOSBIOSVersion, ReleaseDate, SerialNumber | Format-List }
W "Disks" { Get-PhysicalDisk | Select-Object FriendlyName, MediaType, BusType, Size, HealthStatus | Format-Table -AutoSize; Get-Volume | Select-Object DriveLetter, FileSystemLabel, FileSystemType, Size, SizeRemaining, OperationalStatus, HealthStatus | Sort-Object DriveLetter | Format-Table -AutoSize }
W "Power plan" { powercfg /getactivescheme; powercfg /list }

W "GPU (WMI)" { Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, DriverDate, CurrentHorizontalResolution, CurrentVerticalResolution, CurrentRefreshRate | Format-List }
W "NVIDIA-SMI" { try { nvidia-smi } catch { "nvidia-smi not found" } }
W "DirectX (dxdiag summary)" {
  $dx = Join-Path $logDir "dxdiag-audit-$ts.txt"
  try { & "$env:WINDIR\System32\dxdiag.exe" /t $dx | Out-Null; Start-Sleep -Seconds 2 } catch { }
  if (Test-Path $dx) {
    Get-Content $dx -TotalCount 80
    "(full dxdiag): $dx"
  }
  else {
    "dxdiag output not created"
  }
}

W "HAGS (registry)" {
  try { Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers' -Name HwSchMode -ErrorAction Stop | Format-List } catch { "HwSchMode not readable (needs admin or not set)" }
}
W "Game Mode" {
  try { Get-ItemProperty -Path 'HKCU:\Software\Microsoft\GameBar' -ErrorAction Stop | Select-Object AutoGameModeEnabled, AllowAutoGameMode | Format-List } catch { "GameBar keys not found" }
}

W "WSL" { try { wsl --status; wsl -l -v } catch { "wsl not installed" } }
W "Virtualization" {
  try {
    Get-CimInstance -Namespace 'root\Microsoft\Windows\DeviceGuard' -ClassName Win32_DeviceGuard | Format-List *
  }
  catch {
    "DeviceGuard query failed: $($_.Exception.Message)"
  }
}
W "Windows optional features (WSL/VM)" {
  $names = @('Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform', 'HypervisorPlatform', 'Microsoft-Hyper-V-All')
  foreach ($n in $names) {
    try {
      $feat = Get-WindowsOptionalFeature -Online -FeatureName $n -ErrorAction Stop
      $feat | Select-Object FeatureName, State | Format-Table -AutoSize
    }
    catch {
      # Fallback to DISM, which works even when the PowerShell cmdlet is blocked
      "${n}: Get-WindowsOptionalFeature failed; trying DISM..."
      (dism /online /Get-FeatureInfo /FeatureName:$n) 2>&1 | Out-String
    }
  }
}

W "Developer tools" {
  try { "winget: " + (winget --version) } catch { "winget: not found" }
  try { "git: " + (git --version) } catch { "git: not found" }
  try { "py launcher: `n" + ((py -0p) 2>&1 | Out-String) } catch { "py launcher: not found" }
  try { "python (PATH): `n" + ((python --version) 2>&1 | Out-String) } catch { "python (PATH): not found" }
  try { "pip: `n" + ((pip --version) 2>&1 | Out-String) } catch { "pip: not found" }
}

if ($IncludeLargeOutputs) {
  W "pnputil display drivers" { pnputil /enum-drivers }
}

"Wrote: $out" | Write-Host
