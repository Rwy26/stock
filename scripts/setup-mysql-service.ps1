param(
  [string]$ServiceName = 'MySQL84',
  [int]$Port = 3306,
  [string]$DbName = 'apollo_db',
  [string]$AppUser = 'apollo',
  [switch]$AddBinToPath = $true,
  [switch]$WriteBackendEnv = $true
)

$ErrorActionPreference = 'Stop'

function Assert-Admin {
  $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  if (-not $isAdmin) {
    throw 'Administrator privileges are required to install/start a Windows service.'
  }
}

function Resolve-Exe($name, $candidates) {
  $cmd = Get-Command $name -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
  return $null
}

function Get-PlainText([Security.SecureString]$secure) {
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try {
    return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  }
}

function Escape-SqlString([string]$s) {
  return ($s -replace "'", "''")
}

function Escape-MySqlIdentifier([string]$s) {
  return ($s -replace "`"", "``""")
}

Assert-Admin

$repoRoot = Split-Path $PSScriptRoot -Parent
$logDir = Join-Path $repoRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logPath = Join-Path $logDir 'mysql-service-setup.log'

Start-Transcript -Path $logPath -Append | Out-Null

try {
  $baseDir = "$env:ProgramFiles\\MySQL\\MySQL Server 8.4"
  $binDir = Join-Path $baseDir 'bin'

  $mysqldExe = Resolve-Exe 'mysqld' @(
    (Join-Path $binDir 'mysqld.exe'),
    "$env:ProgramFiles\\MySQL\\MySQL Server 8.0\\bin\\mysqld.exe",
    "$env:ProgramFiles\\MySQL\\MySQL Server 8.1\\bin\\mysqld.exe",
    "$env:ProgramFiles\\MySQL\\MySQL Server 8.2\\bin\\mysqld.exe",
    "$env:ProgramFiles\\MySQL\\MySQL Server 8.3\\bin\\mysqld.exe"
  )
  $mysqlExe = Resolve-Exe 'mysql' @(
    (Join-Path $binDir 'mysql.exe'),
    "$env:ProgramFiles\\MySQL\\MySQL Server 8.0\\bin\\mysql.exe",
    "$env:ProgramFiles\\MySQL\\MySQL Server 8.1\\bin\\mysql.exe",
    "$env:ProgramFiles\\MySQL\\MySQL Server 8.2\\bin\\mysql.exe",
    "$env:ProgramFiles\\MySQL\\MySQL Server 8.3\\bin\\mysql.exe"
  )

  if (-not $mysqldExe -or -not $mysqlExe) {
    throw 'MySQL Server binaries not found. Install MySQL first (winget id: Oracle.MySQL).'
  }

  Write-Output "mysqld: $mysqldExe"
  Write-Output "mysql:  $mysqlExe"

  $configDir = Join-Path $env:ProgramData 'MySQL\MySQL Server 8.4'
  $dataDir = Join-Path $configDir 'Data'
  New-Item -ItemType Directory -Path $configDir -Force | Out-Null
  New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

  $iniPath = Join-Path $configDir 'my.ini'
  $ini = @(
    '[mysqld]',
    "basedir=$baseDir",
    "datadir=$dataDir",
    "port=$Port",
    'bind-address=127.0.0.1',
    'skip-name-resolve=1',
    'character-set-server=utf8mb4',
    'collation-server=utf8mb4_unicode_ci',
    'default_authentication_plugin=caching_sha2_password',
    '',
    '[client]',
    "port=$Port",
    'host=127.0.0.1',
    'default-character-set=utf8mb4'
  )
  $ini | Set-Content -Path $iniPath -Encoding ASCII
  Write-Output "Wrote config: $iniPath"

  $systemDbDir = Join-Path $dataDir 'mysql'
  if (-not (Test-Path $systemDbDir)) {
    Write-Output 'Initializing data directory...'
    & $mysqldExe --defaults-file="$iniPath" --initialize-insecure
    if ($LASTEXITCODE -ne 0) { throw "mysqld initialize failed (exit code $LASTEXITCODE)" }
  } else {
    Write-Output 'Data directory already initialized.'
  }

  $existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
  if (-not $existing) {
    Write-Output "Installing Windows service '$ServiceName'..."
    & $mysqldExe --install $ServiceName --defaults-file="$iniPath"
    if ($LASTEXITCODE -ne 0) { throw "mysqld --install failed (exit code $LASTEXITCODE)" }
  } else {
    Write-Output "Service '$ServiceName' already exists."
  }

  Set-Service -Name $ServiceName -StartupType Automatic
  Start-Service -Name $ServiceName

  Write-Output 'Waiting for MySQL to accept connections...'
  $deadline = (Get-Date).AddSeconds(90)
  do {
    Start-Sleep -Milliseconds 500
    & $mysqlExe -u root --protocol=tcp -h 127.0.0.1 -P $Port -e "SELECT 1;" 2>$null
    if ($LASTEXITCODE -eq 0) { break }
  } while ((Get-Date) -lt $deadline)
  if ($LASTEXITCODE -ne 0) {
    throw "MySQL service did not become ready on port $Port within 90s."
  }

  $rootPwSecure = Read-Host -AsSecureString 'Enter MySQL root password to set (will be required going forward)'
  $appPwSecure = Read-Host -AsSecureString "Enter password for MySQL app user '$AppUser'"
  $rootPw = Get-PlainText $rootPwSecure
  $appPw = Get-PlainText $appPwSecure

  $rootPwSql = Escape-SqlString $rootPw
  $appPwSql = Escape-SqlString $appPw
  $appUserSql = Escape-SqlString $AppUser
  $dbNameSql = Escape-MySqlIdentifier $DbName

  Write-Output 'Applying DB/user setup...'
  $sql = @"
ALTER USER IF EXISTS 'root'@'localhost' IDENTIFIED BY '$rootPwSql';
CREATE USER IF NOT EXISTS 'root'@'127.0.0.1' IDENTIFIED BY '$rootPwSql';
CREATE DATABASE IF NOT EXISTS `$dbNameSql` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$appUserSql'@'127.0.0.1' IDENTIFIED BY '$appPwSql';
CREATE USER IF NOT EXISTS '$appUserSql'@'localhost' IDENTIFIED BY '$appPwSql';
GRANT ALL PRIVILEGES ON `$dbNameSql`.* TO '$appUserSql'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `$dbNameSql`.* TO '$appUserSql'@'localhost';
FLUSH PRIVILEGES;
"@

  & $mysqlExe -u root --protocol=tcp -h 127.0.0.1 -P $Port -e $sql
  if ($LASTEXITCODE -ne 0) { throw "Failed to apply SQL setup (exit code $LASTEXITCODE)" }

  if ($AddBinToPath) {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    if ($machinePath -notmatch [Regex]::Escape($binDir)) {
      [Environment]::SetEnvironmentVariable('Path', ($machinePath.TrimEnd(';') + ';' + $binDir), 'Machine')
      Write-Output "Added to Machine PATH: $binDir"
    } else {
      Write-Output 'MySQL bin already in Machine PATH.'
    }
  }

  if ($WriteBackendEnv) {
    $backendEnvPath = Join-Path $repoRoot 'backend\.env'
    $envLines = @(
      "MYSQL_HOST=127.0.0.1",
      "MYSQL_PORT=$Port",
      "MYSQL_DB=$DbName",
      "MYSQL_USER=$AppUser",
      "MYSQL_PASSWORD=$appPw"
    )
    $envLines | Set-Content -Path $backendEnvPath -Encoding UTF8
    Write-Output "Wrote backend env: $backendEnvPath"
  }

  Write-Output ''
  Write-Output 'MySQL service setup complete.'
  Write-Output "Service: $ServiceName (Auto)"
  Write-Output "DB: $DbName"
  Write-Output "User: $AppUser"
  Write-Output "Port: $Port"
  Write-Output "Log: $logPath"

} finally {
  Stop-Transcript | Out-Null
}
