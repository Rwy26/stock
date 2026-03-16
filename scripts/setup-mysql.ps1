[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPlainTextForPassword', 'RootPasswordText', Justification = 'Optional automation escape hatch; prefer SecureString params.')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPlainTextForPassword', 'AppPasswordText', Justification = 'Optional automation escape hatch; prefer SecureString params.')]
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
  [string]$DbName = 'apollo_db',
  [string]$AppUser = 'apollo',

  # Preferred: pass SecureString (or omit to prompt).
  [SecureString]$RootPassword,
  [SecureString]$AppPassword,

  # Optional: automation escape hatch (discouraged).
  [string]$RootPasswordText,
  [string]$AppPasswordText,

  [int]$Port = 3306,
  [string]$InstanceDir = (Join-Path (Get-Location) '.mysql'),
  [switch]$NoPrompt = $false
)

$ErrorActionPreference = 'Stop'

function ConvertFrom-SecureStringPlain([SecureString]$sec) {
  if (-not $sec) { return '' }
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
  try {
    return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  } finally {
    if ($bstr -ne [IntPtr]::Zero) {
      [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
  }
}

function Resolve-Exe($name, $candidates) {
  $cmd = Get-Command $name -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  foreach ($c in $candidates) {
    if (Test-Path $c) { return $c }
  }
  return $null
}

$mysqlExe = Resolve-Exe 'mysql' @(
  "$env:ProgramFiles\MySQL\MySQL Server 8.4\bin\mysql.exe",
  "$env:ProgramFiles\MySQL\MySQL Server 8.0\bin\mysql.exe",
  "$env:ProgramFiles\MySQL\MySQL Server 8.1\bin\mysql.exe",
  "$env:ProgramFiles\MySQL\MySQL Server 8.2\bin\mysql.exe",
  "$env:ProgramFiles\MySQL\MySQL Server 8.3\bin\mysql.exe"
)

$mysqldExe = Resolve-Exe 'mysqld' @(
  "$env:ProgramFiles\MySQL\MySQL Server 8.4\bin\mysqld.exe",
  "$env:ProgramFiles\MySQL\MySQL Server 8.0\bin\mysqld.exe",
  "$env:ProgramFiles\MySQL\MySQL Server 8.1\bin\mysqld.exe",
  "$env:ProgramFiles\MySQL\MySQL Server 8.2\bin\mysqld.exe",
  "$env:ProgramFiles\MySQL\MySQL Server 8.3\bin\mysqld.exe"
)

if (-not $mysqlExe -or -not $mysqldExe) {
  throw "MySQL binaries not found. Install MySQL first: winget install -e --id Oracle.MySQL --source winget"
}

$instanceDirResolved = Resolve-Path -LiteralPath $InstanceDir -ErrorAction SilentlyContinue
$instanceDirPath = if ($instanceDirResolved) { $instanceDirResolved.Path } else { $InstanceDir }
$dataDir = Join-Path $instanceDirPath 'data'
$logDir = Join-Path $instanceDirPath 'logs'

Write-Output "Using mysqld: $mysqldExe"
Write-Output "Using mysql:  $mysqlExe"
Write-Output "InstanceDir:  $instanceDirPath"
Write-Output "DataDir:      $dataDir"
Write-Output "Port:         $Port"

if ($WhatIfPreference) {
  Write-Output ''
  Write-Output 'WhatIf mode: no changes will be made.'
  Write-Output "Would create instance dir (if missing): $instanceDirPath"
  Write-Output "Would ensure data dir: $dataDir"
  Write-Output "Would ensure log dir:  $logDir"
  Write-Output 'Would initialize data directory if missing (insecure)'
  Write-Output "Would start mysqld (non-service) on port $Port"
  Write-Output "Would create DB: $DbName"
  Write-Output "Would create app user: $AppUser"
  Write-Output 'Would apply DB/user setup via mysql.exe (passwords not shown)'
  return
}

if (-not $instanceDirResolved) {
  if (-not $PSCmdlet.ShouldProcess($instanceDirPath, 'Create instance directory')) {
    Write-Output 'Cancelled.'
    return
  }
  New-Item -ItemType Directory -Path $instanceDirPath | Out-Null
  $instanceDirResolved = Resolve-Path -LiteralPath $instanceDirPath
  $instanceDirPath = $instanceDirResolved.Path
  $dataDir = Join-Path $instanceDirPath 'data'
  $logDir = Join-Path $instanceDirPath 'logs'
}

if (-not $PSCmdlet.ShouldProcess($dataDir, 'Create/ensure data directory')) {
  Write-Output 'Cancelled.'
  return
}
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

if (-not $PSCmdlet.ShouldProcess($logDir, 'Create/ensure log directory')) {
  Write-Output 'Cancelled.'
  return
}
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$mysqldLog = Join-Path $logDir 'mysqld.log'

if (-not $RootPassword) {
  if ($RootPasswordText) {
    $RootPassword = ConvertTo-SecureString -String $RootPasswordText -AsPlainText -Force
  } elseif ($NoPrompt) {
    throw 'RootPassword is required when -NoPrompt is specified (use -RootPassword or -RootPasswordText).'
  } else {
    $RootPassword = Read-Host -AsSecureString 'MySQL root password'
  }
}

if (-not $AppPassword) {
  if ($AppPasswordText) {
    $AppPassword = ConvertTo-SecureString -String $AppPasswordText -AsPlainText -Force
  } elseif ($NoPrompt) {
    throw 'AppPassword is required when -NoPrompt is specified (use -AppPassword or -AppPasswordText).'
  } else {
    $AppPassword = Read-Host -AsSecureString "MySQL app user password ($AppUser)"
  }
}

# Initialize (insecure, then we set passwords immediately)
if (-not (Test-Path (Join-Path $dataDir 'mysql'))) {
  Write-Output "Initializing data directory (insecure)..."
  if (-not $PSCmdlet.ShouldProcess($dataDir, 'mysqld --initialize-insecure')) {
    Write-Output 'Cancelled.'
    return
  }
  & $mysqldExe --initialize-insecure --datadir="$dataDir" --console 2>&1 | Tee-Object -FilePath $mysqldLog | Out-Null
}

# Start mysqld in the background (non-service) for local production-like dev
Write-Output "Starting MySQL server (non-service)..."
if (-not $PSCmdlet.ShouldProcess('mysqld', "Start mysqld on port $Port")) {
  Write-Output 'Cancelled.'
  return
}
$proc = Start-Process -FilePath $mysqldExe -ArgumentList @(
  "--datadir=$dataDir",
  "--port=$Port",
  "--bind-address=127.0.0.1",
  "--console"
) -NoNewWindow -PassThru -RedirectStandardError $mysqldLog -RedirectStandardOutput $mysqldLog

try {
  $deadline = (Get-Date).AddSeconds(60)
  do {
    Start-Sleep -Milliseconds 500
    $null = & $mysqlExe -u root --protocol=tcp -h 127.0.0.1 -P $Port -e "SELECT 1;" 2>$null
    if ($LASTEXITCODE -eq 0) { break }
  } while ((Get-Date) -lt $deadline)

  if ($LASTEXITCODE -ne 0) {
    throw "MySQL did not become ready on port $Port within 60s. See log: $mysqldLog"
  }

  Write-Output "Configuring users and database..."

  $rootPasswordPlain = ConvertFrom-SecureStringPlain $RootPassword
  $appPasswordPlain = ConvertFrom-SecureStringPlain $AppPassword

  $rootPasswordSql = $rootPasswordPlain -replace "'", "''"
  $appPasswordSql = $appPasswordPlain -replace "'", "''"
  $appUserSql = $AppUser -replace "'", "''"
  if ($DbName -notmatch '^[A-Za-z0-9_]+$') {
    throw "DbName must match ^[A-Za-z0-9_]+$ (got: $DbName)"
  }
  $dbNameSql = $DbName

  $sql = (
    @(
      "ALTER USER 'root'@'localhost' IDENTIFIED BY '$rootPasswordSql';",
      "CREATE DATABASE IF NOT EXISTS $dbNameSql CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
      "CREATE USER IF NOT EXISTS '$appUserSql'@'127.0.0.1' IDENTIFIED BY '$appPasswordSql';",
      "GRANT ALL PRIVILEGES ON $dbNameSql.* TO '$appUserSql'@'127.0.0.1';",
      "FLUSH PRIVILEGES;"
    ) -join "`n"
  )

  if ($PSCmdlet.ShouldProcess('mysql.exe', 'Apply DB/user setup SQL')) {
    & $mysqlExe -u root --protocol=tcp -h 127.0.0.1 -P $Port -e $sql
    if ($LASTEXITCODE -ne 0) {
      throw "Failed to apply SQL setup. Check log: $mysqldLog"
    }
  } else {
    Write-Output 'Skipped applying SQL setup; stopping server.'
    if ($proc -and -not $proc.HasExited) {
      Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    return
  }

  # Best-effort: clear plaintext copies.
  $rootPasswordPlain = $null
  $appPasswordPlain = $null

  Write-Output "Done. MySQL is running under PID $($proc.Id)."
  Write-Output "Connection (app): mysql://${AppUser}:<password>@127.0.0.1:${Port}/${DbName}"
  Write-Output "To stop: Stop-Process -Id $($proc.Id)"
} catch {
  if ($proc -and -not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  }
  throw
}
