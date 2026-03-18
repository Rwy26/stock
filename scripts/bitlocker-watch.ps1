[CmdletBinding()]
param(
    [string]$RepoPath = 'C:\stock',
    [string]$DriveLetter = 'D',
    [string]$LogPath = ''
)

$ErrorActionPreference = 'Continue'

try { Set-Location C:\ } catch { }

$vol = "${DriveLetter}:"

$logDir = Join-Path $RepoPath 'logs'
if (-not $LogPath) {
    $LogPath = Join-Path $logDir 'bitlocker-watch.log'
}

try {
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    }
}
catch { }

function Log([string]$message) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $message
    try { $line | Out-File -FilePath $LogPath -Append -Encoding utf8 } catch { }
}

Log "Start (Volume=$vol, User=$env:USERNAME)"

# 1) manage-bde (best effort; available on Windows)
try {
    Log "manage-bde -status $vol"
    (& manage-bde -status $vol 2>&1) | ForEach-Object { Log "  $_" }
}
catch {
    Log "  ERROR: manage-bde failed: $_"
}

# 2) Get-BitLockerVolume (best effort)
try {
    $bl = Get-BitLockerVolume -MountPoint $vol -ErrorAction Stop
    $summary = "Summary: VolumeStatus={0}; ProtectionStatus={1}; LockStatus={2}; EncryptionMethod={3}; EncryptionPercentage={4}" -f $bl.VolumeStatus, $bl.ProtectionStatus, $bl.LockStatus, $bl.EncryptionMethod, $bl.EncryptionPercentage
    Log $summary

    if ($bl.VolumeStatus -ne 'FullyDecrypted' -or $bl.ProtectionStatus -ne 'Off') {
        Log "WARNING: BitLocker appears enabled or encrypting on $vol"
    }
}
catch {
    Log "Get-BitLockerVolume not available or denied: $_"
}

# 3) Presence of Windows BitLocker tasks (info only)
try {
    $bitlockerTasks = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.TaskPath -eq '\\Microsoft\\Windows\\BitLocker\\' } | Select-Object -First 5 TaskName, State
    foreach ($t in $bitlockerTasks) {
        Log ("BitLockerTask: {0} ({1})" -f $t.TaskName, $t.State)
    }
}
catch { }

Log 'Done'
