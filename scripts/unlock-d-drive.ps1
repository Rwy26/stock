[CmdletBinding()]
param(
    [string]$DriveLetter = 'D',
    [string]$RecoveryPassword
)

$ErrorActionPreference = 'Stop'

function Assert-Admin {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
        throw "관리자 권한이 필요합니다. PowerShell을 '관리자 권한으로 실행' 후 다시 실행하세요."
    }
}

Assert-Admin

$mount = "${DriveLetter}:"
Write-Host "--- BitLocker status ($mount) ---"
manage-bde -status $mount

if ($RecoveryPassword) {
    Write-Host "--- Unlocking with recovery password ---"
    manage-bde -unlock $mount -RecoveryPassword $RecoveryPassword
}
else {
    Write-Host "--- Unlocking with password prompt ---"
    Write-Host "비밀번호 입력 프롬프트가 나오면 BitLocker 비밀번호를 입력하세요."
    manage-bde -unlock $mount -pw
}

Write-Host "--- Status after unlock ---"
manage-bde -status $mount

Write-Host "--- Volume info ---"
try { Get-Volume -DriveLetter $DriveLetter | Format-List DriveLetter, FileSystemType, FileSystemLabel, Size, SizeRemaining, OperationalStatus, HealthStatus } catch { }

Write-Host "--- Optional: enable auto-unlock (internal data drive only) ---"
Write-Host "원하면: manage-bde -autounlock -enable $mount"
