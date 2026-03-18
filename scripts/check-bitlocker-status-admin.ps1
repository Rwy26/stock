[CmdletBinding()]
param(
    [string]$DriveLetter = 'D',
    [string]$OutPath = 'C:\stock\logs\bitlocker-status.txt'
)

$ErrorActionPreference = 'Continue'

try { Set-Location C:\ } catch { }

$vol = "${DriveLetter}:"

try {
    $outDir = Split-Path -Parent $OutPath
    if ($outDir -and -not (Test-Path $outDir)) {
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    }
}
catch { }

function Write-Section([string]$title) {
    "`n===== $title =====" | Out-File -FilePath $OutPath -Append -Encoding utf8
}

"BitLocker status dump for $vol" | Out-File -FilePath $OutPath -Encoding utf8
("Generated: {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) | Out-File -FilePath $OutPath -Append -Encoding utf8

Write-Section "manage-bde -status $vol"
try {
    & manage-bde -status $vol 2>&1 | Out-File -FilePath $OutPath -Append -Encoding utf8
}
catch {
    ("ERROR: {0}" -f $_) | Out-File -FilePath $OutPath -Append -Encoding utf8
}

Write-Section "manage-bde -protectors -get $vol"
try {
    & manage-bde -protectors -get $vol 2>&1 | Out-File -FilePath $OutPath -Append -Encoding utf8
}
catch {
    ("ERROR: {0}" -f $_) | Out-File -FilePath $OutPath -Append -Encoding utf8
}

Write-Section "Get-BitLockerVolume -MountPoint $vol"
try {
    Get-BitLockerVolume -MountPoint $vol | Format-List * | Out-File -FilePath $OutPath -Append -Encoding utf8
}
catch {
    ("ERROR: {0}" -f $_) | Out-File -FilePath $OutPath -Append -Encoding utf8
}

Write-Section "BitLocker policy (HKLM\\SOFTWARE\\Policies\\Microsoft\\FVE)"
try {
    if (Test-Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\FVE') {
        Get-ItemProperty 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\FVE' | Format-List * | Out-File -FilePath $OutPath -Append -Encoding utf8
    }
    else {
        'No FVE policy key found.' | Out-File -FilePath $OutPath -Append -Encoding utf8
    }
}
catch {
    ("ERROR: {0}" -f $_) | Out-File -FilePath $OutPath -Append -Encoding utf8
}

Write-Section "Done"
'OK' | Out-File -FilePath $OutPath -Append -Encoding utf8
