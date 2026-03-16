[CmdletBinding()]
param(
    [string]$DriveLetter = 'D',
    [switch]$FullScan
)

$ErrorActionPreference = 'Continue'

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$out = Join-Path $logDir "find-bitlocker-keys-$ts.txt"

function W([string]$title, [scriptblock]$action) {
    "" | Out-File -Append -Encoding utf8 $out
    ("==== {0} ====" -f $title) | Out-File -Append -Encoding utf8 $out
    try { (& $action 2>&1 | Out-String) | Out-File -Append -Encoding utf8 $out } catch { $_ | Out-String | Out-File -Append -Encoding utf8 $out }
}

function Is-Admin {
    try {
        $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
        return $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
    }
    catch { return $false }
}

"==== Find BitLocker Keys ($ts) ====" | Out-File -Encoding utf8 $out
"Admin: $(Is-Admin)" | Out-File -Append -Encoding utf8 $out

W "Mounted filesystem drives" {
    Get-PSDrive -PSProvider FileSystem | Select-Object Name, Root, Free, Used, Description | Format-Table -AutoSize
}

W "Volumes (summary)" {
    try {
        Get-Volume | Select-Object DriveLetter, FileSystemLabel, FileSystemType, DriveType, Size, SizeRemaining, OperationalStatus, HealthStatus |
        Sort-Object DriveLetter | Format-Table -AutoSize
    }
    catch { $_ | Out-String }
}

W "Drive status (manage-bde, best effort)" {
    $mount = "${DriveLetter}:"
    manage-bde -status $mount
    manage-bde -protectors -get $mount
}

# Likely locations for recovery key text files
$userProfile = $env:USERPROFILE
$candidates = @(
    (Join-Path $userProfile 'Desktop'),
    (Join-Path $userProfile 'Documents'),
    (Join-Path $userProfile 'Downloads'),
    (Join-Path $userProfile 'OneDrive'),
    (Join-Path $userProfile 'OneDrive\Documents'),
    (Join-Path $userProfile 'OneDrive\Desktop'),
    'C:\Users\Public\Documents',
    'C:\'
) | Where-Object { Test-Path $_ }

$patterns = @(
    '*BitLocker*Recovery*Key*.txt',
    '*BitLocker*복구*키*.txt',
    '*RecoveryKey*.txt',
    '*.bek'
)

W "Candidate roots" { $candidates | ForEach-Object { $_ } }

function Find-Matches([string]$rootPath) {
    foreach ($pat in $patterns) {
        try {
            Get-ChildItem -Path $rootPath -Filter $pat -File -Recurse -ErrorAction SilentlyContinue |
            Select-Object FullName, Length, LastWriteTime
        }
        catch { }
    }
}

# Quick scan: only common folders
W "Quick scan (common folders)" {
    $roots = $candidates | Where-Object { $_ -ne 'C:\' }
    $results = foreach ($r in $roots) { Find-Matches $r }
    $results | Sort-Object FullName -Unique | Format-Table -AutoSize
}

W "Quick scan (other mounted drives roots)" {
    $driveRoots = (Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Root -match '^[A-Z]:\\$' } | Select-Object -ExpandProperty Root)
    $driveRoots = $driveRoots | Where-Object { $_ -ne 'C:\' }
    $results = foreach ($r in $driveRoots) {
        # Only scan one level deep quickly to avoid huge recursion on data drives
        foreach ($pat in $patterns) {
            Get-ChildItem -Path $r -Filter $pat -File -Recurse -Depth 3 -ErrorAction SilentlyContinue | Select-Object FullName, Length, LastWriteTime
        }
    }
    $results | Sort-Object FullName -Unique | Format-Table -AutoSize
}

if ($FullScan) {
    W "Full scan (C:\ - can be slow)" {
        $results = Find-Matches 'C:\'
        $results | Sort-Object FullName -Unique | Format-Table -AutoSize
    }
}

W "Search inside text files (common folders)" {
    $roots = $candidates | Where-Object { $_ -ne 'C:\' }
    $txts = foreach ($r in $roots) {
        Get-ChildItem -Path $r -Filter '*.txt' -File -Recurse -ErrorAction SilentlyContinue
    }
    $hits = $txts | Select-String -Pattern 'BitLocker', 'Recovery Key', '복구 키', '복구키', '48자리', '숫자 암호' -SimpleMatch -ErrorAction SilentlyContinue
    $hits | Select-Object Path, LineNumber, Line | Format-Table -AutoSize
}

"Wrote: $out" | Write-Host
