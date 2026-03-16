param(
  [string]$DbName = 'apollo_db',
  [string]$AppUser = 'apollo',
  [Parameter(Mandatory = $true)][string]$RootPassword,
  [Parameter(Mandatory = $true)][string]$AppPassword,
  [int]$Port = 3306,
  [string]$InstanceDir = (Join-Path (Get-Location) '.mysql')
)

$ErrorActionPreference = 'Stop'

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

$instanceDir = Resolve-Path -LiteralPath $InstanceDir -ErrorAction SilentlyContinue
if (-not $instanceDir) {
  New-Item -ItemType Directory -Path $InstanceDir | Out-Null
  $instanceDir = Resolve-Path -LiteralPath $InstanceDir
}

$dataDir = Join-Path $instanceDir 'data'
$logDir = Join-Path $instanceDir 'logs'
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$mysqldLog = Join-Path $logDir 'mysqld.log'

Write-Output "Using mysqld: $mysqldExe"
Write-Output "Using mysql:  $mysqlExe"
Write-Output "InstanceDir:  $instanceDir"
Write-Output "DataDir:      $dataDir"
Write-Output "Port:         $Port"

# Initialize (insecure, then we set passwords immediately)
if (-not (Test-Path (Join-Path $dataDir 'mysql'))) {
  Write-Output "Initializing data directory (insecure)..."
  & $mysqldExe --initialize-insecure --datadir="$dataDir" --console 2>&1 | Tee-Object -FilePath $mysqldLog | Out-Null
}

# Start mysqld in the background (non-service) for local production-like dev
Write-Output "Starting MySQL server (non-service)..."
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
    $ok = & $mysqlExe -u root --protocol=tcp -h 127.0.0.1 -P $Port -e "SELECT 1;" 2>$null
    if ($LASTEXITCODE -eq 0) { break }
  } while ((Get-Date) -lt $deadline)

  if ($LASTEXITCODE -ne 0) {
    throw "MySQL did not become ready on port $Port within 60s. See log: $mysqldLog"
  }

  Write-Output "Configuring users and database..."

  $rootPasswordSql = $RootPassword -replace "'", "''"
  $appPasswordSql = $AppPassword -replace "'", "''"
  $appUserSql = $AppUser -replace "'", "''"
  $dbNameSql = $DbName -replace "`"", "``""  # escape backticks for identifier usage

  $sql = @"
ALTER USER 'root'@'localhost' IDENTIFIED BY '$rootPasswordSql';
CREATE DATABASE IF NOT EXISTS `$dbNameSql` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$appUserSql'@'127.0.0.1' IDENTIFIED BY '$appPasswordSql';
GRANT ALL PRIVILEGES ON `$dbNameSql`.* TO '$appUserSql'@'127.0.0.1';
FLUSH PRIVILEGES;
"@

  & $mysqlExe -u root --protocol=tcp -h 127.0.0.1 -P $Port -e $sql
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to apply SQL setup. Check log: $mysqldLog"
  }

  Write-Output "Done. MySQL is running under PID $($proc.Id)."
  Write-Output "Connection (app): mysql://$AppUser:<password>@127.0.0.1:$Port/$DbName"
  Write-Output "To stop: Stop-Process -Id $($proc.Id)"
} catch {
  if ($proc -and -not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  }
  throw
}
