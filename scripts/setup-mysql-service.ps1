[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPlainTextForPassword', 'RootPasswordText', Justification = 'Optional automation escape hatch; prefer SecureString params.')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPlainTextForPassword', 'AppPasswordText', Justification = 'Optional automation escape hatch; prefer SecureString params.')]
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
  [string]$ServiceName = 'MySQL84',
  [int]$Port = 3306,
  [string]$DbName = 'apollo_db',
  [string]$AppUser = 'apollo',
  [SecureString]$RootPassword,
  [SecureString]$AppPassword,
  [string]$RootPasswordText,
  [string]$AppPasswordText,
  [switch]$AddBinToPath = $true,
  [switch]$WriteBackendEnv = $true,
  [switch]$NoPrompt = $false,
  [switch]$ReinitDataDir = $false,
  # When set, skips config/service installation/start; only applies DB/user setup and writes backend/.env.
  # Useful when the MySQL Windows service is already running and you are not elevated.
  [switch]$DbOnly = $false
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
  if (-not $secure) { return '' }
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try {
    return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  }
}

function Ensure-SecurePassword([SecureString]$secure, [string]$plainText) {
  if ($secure) { return $secure }
  if ($plainText) {
    return (ConvertTo-SecureString -String $plainText -AsPlainText -Force)
  }
  return $null
}

function Get-PasswordOrPrompt([string]$label, [SecureString]$value, [switch]$noPrompt) {
  if ($value) {
    return (Get-PlainText $value)
  }
  if ($noPrompt) {
    throw "$label is required when -NoPrompt is specified"
  }
  $secure = Read-Host -AsSecureString "$label"
  return (Get-PlainText $secure)
}

function Escape-SqlString([string]$s) {
  return ($s -replace "'", "''")
}

function Invoke-MySqlQuery {
  param(
    [Parameter(Mandatory = $true)][string]$MySqlExe,
    [Parameter(Mandatory = $true)][string]$Query,
    [ValidateSet('none', 'password')][string]$AuthMode = 'none',
    [string]$Password,
    [switch]$Quiet = $false
  )

  if ($AuthMode -eq 'password') {
    if (-not $Password) { throw 'Password auth selected but no password provided.' }
    $prev = $env:MYSQL_PWD
    try {
      $env:MYSQL_PWD = $Password
      if ($Quiet) {
        & $MySqlExe -u root --protocol=pipe --socket=MySQL -e $Query *> $null
      } else {
        & $MySqlExe -u root --protocol=pipe --socket=MySQL -e $Query
      }
      return $LASTEXITCODE
    } finally {
      $env:MYSQL_PWD = $prev
    }
  }

  if ($Quiet) {
    & $MySqlExe -u root --protocol=pipe --socket=MySQL -e $Query *> $null
  } else {
    & $MySqlExe -u root --protocol=pipe --socket=MySQL -e $Query
  }
  return $LASTEXITCODE
}

if (-not $DbOnly) {
  Assert-Admin
}

$repoRoot = Split-Path $PSScriptRoot -Parent
$logDir = Join-Path $repoRoot 'logs'
$transcriptStarted = $false
if ($PSCmdlet.ShouldProcess($logDir, 'Create logs directory')) {
  New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$logPath = Join-Path $logDir 'mysql-service-setup.log'

if ($PSCmdlet.ShouldProcess($logPath, 'Start transcript')) {
  Start-Transcript -Path $logPath -Append | Out-Null
  $transcriptStarted = $true
}

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

  if ($DbOnly) {
    if (-not $mysqlExe) {
      throw 'MySQL client (mysql.exe) not found. Install MySQL first (winget id: Oracle.MySQL).'
    }
  } else {
    if (-not $mysqldExe -or -not $mysqlExe) {
      throw 'MySQL Server binaries not found. Install MySQL first (winget id: Oracle.MySQL).'
    }
  }

  Write-Output "mysqld: $mysqldExe"
  Write-Output "mysql:  $mysqlExe"

  if ($WhatIfPreference) {
    Write-Output ''
    Write-Output 'WhatIf mode: no changes will be made.'
    Write-Output "Would configure/start service: $ServiceName" 
    Write-Output "Would use port: $Port"
    Write-Output "Would create DB: $DbName"
    Write-Output "Would create app user: $AppUser"
    if (-not $DbOnly) {
      $configDirPreview = Join-Path $env:ProgramData 'MySQL\MySQL Server 8.4'
      $dataDirPreview = Join-Path $configDirPreview 'Data'
      $iniPathPreview = Join-Path $configDirPreview 'my.ini'
      Write-Output "Would write config: $iniPathPreview"
      if ($ReinitDataDir) { Write-Output "Would reinitialize data dir: $dataDirPreview" }
      Write-Output "Would ensure data dir: $dataDirPreview"
      Write-Output 'Would initialize data directory if missing'
      Write-Output 'Would install Windows service if missing'
      Write-Output 'Would set StartupType=Automatic and start service'
      if ($AddBinToPath) { Write-Output "Would add MySQL bin to Machine PATH: $binDir" }
    } else {
      Write-Output 'DbOnly mode: would skip service install/start.'
    }
    Write-Output 'Would apply DB/user setup via mysql.exe (passwords not shown)'
    if ($WriteBackendEnv) {
      $backendEnvPathPreview = Join-Path $repoRoot 'backend\.env'
      Write-Output "Would write backend env: $backendEnvPathPreview (MYSQL_PASSWORD redacted)"
    }
    return
  }

  if (-not $DbOnly) {
    $configDir = Join-Path $env:ProgramData 'MySQL\MySQL Server 8.4'
    $dataDir = Join-Path $configDir 'Data'
    if ($PSCmdlet.ShouldProcess($configDir, 'Create MySQL config directory')) {
      New-Item -ItemType Directory -Path $configDir -Force | Out-Null
    }
    if ($PSCmdlet.ShouldProcess($dataDir, 'Create MySQL data directory')) {
      New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
    }

    $iniPath = Join-Path $configDir 'my.ini'
    $ini = @(
      '[mysqld]',
      "basedir=$baseDir",
      "datadir=$dataDir",
      "port=$Port",
      'bind-address=127.0.0.1',
      'named_pipe=ON',
      'socket=MySQL',
      'skip-name-resolve=1',
      'character-set-server=utf8mb4',
      'collation-server=utf8mb4_unicode_ci',
      '',
      '[client]',
      "port=$Port",
      'host=127.0.0.1',
      'default-character-set=utf8mb4'
    )
    if ($PSCmdlet.ShouldProcess($iniPath, 'Write my.ini')) {
      $ini | Set-Content -Path $iniPath -Encoding ASCII
      Write-Output "Wrote config: $iniPath"
    }

    if ($ReinitDataDir) {
      Write-Output 'Reinitializing MySQL data directory (forced)...'
      $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
      if ($svc -and $svc.Status -ne 'Stopped') {
        if ($PSCmdlet.ShouldProcess($ServiceName, 'Stop Windows service')) {
          Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
          Start-Sleep -Seconds 2
        }
      }

      if (Test-Path $dataDir) {
        if ($PSCmdlet.ShouldProcess($dataDir, 'Remove data directory')) {
          Remove-Item -LiteralPath $dataDir -Recurse -Force
        }
      }
      if ($PSCmdlet.ShouldProcess($dataDir, 'Create data directory')) {
        New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
      }
    }

    $systemDbDir = Join-Path $dataDir 'mysql'
    if (-not (Test-Path $systemDbDir)) {
      Write-Output 'Initializing data directory...'
      if ($PSCmdlet.ShouldProcess($dataDir, 'mysqld --initialize-insecure')) {
        & $mysqldExe --defaults-file="$iniPath" --initialize-insecure
        if ($LASTEXITCODE -ne 0) { throw "mysqld initialize failed (exit code $LASTEXITCODE)" }
      }
    } else {
      Write-Output 'Data directory already initialized.'
    }

    $existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $existing) {
      Write-Output "Installing Windows service '$ServiceName'..."
      if ($PSCmdlet.ShouldProcess($ServiceName, 'mysqld --install')) {
        & $mysqldExe --install $ServiceName --defaults-file="$iniPath"
        if ($LASTEXITCODE -ne 0) { throw "mysqld --install failed (exit code $LASTEXITCODE)" }
      }
    } else {
      Write-Output "Service '$ServiceName' already exists."
    }

    if ($PSCmdlet.ShouldProcess($ServiceName, 'Set service StartupType=Automatic')) {
      Set-Service -Name $ServiceName -StartupType Automatic
    }
    if ($PSCmdlet.ShouldProcess($ServiceName, 'Start Windows service')) {
      Start-Service -Name $ServiceName
    }
  } else {
    Write-Output 'DbOnly mode: skipping config/service installation/start.'
  }

  Write-Output 'Waiting for MySQL to accept connections...'
  $deadline = (Get-Date).AddSeconds(90)
  $authMode = 'none'
  $connected = $false

  # Ensure we have password material available for NoPrompt/automation.
  $RootPassword = Ensure-SecurePassword $RootPassword $RootPasswordText
  $AppPassword = Ensure-SecurePassword $AppPassword $AppPasswordText

  do {
    Start-Sleep -Milliseconds 500
    $code = (Invoke-MySqlQuery -MySqlExe $mysqlExe -Query 'SELECT 1;' -AuthMode 'none' -Quiet)
    if ($code -eq 0) {
      $authMode = 'none'
      $connected = $true
      break
    }

    # If root already has a password set, the unauthenticated probe will fail.
    # In that case, try again with a provided (or prompted) root password.
    if (-not $RootPassword -and -not $NoPrompt) {
      $RootPassword = Read-Host -AsSecureString 'Enter current MySQL root password (needed if root already has one set)'
    }
    if ($RootPassword) {
      $probePw = Get-PlainText $RootPassword
      $code2 = (Invoke-MySqlQuery -MySqlExe $mysqlExe -Query 'SELECT 1;' -AuthMode 'password' -Password $probePw -Quiet)
      if ($code2 -eq 0) {
        $authMode = 'password'
        $connected = $true
        break
      }
    }
  } while ((Get-Date) -lt $deadline)

  if (-not $connected) {
    throw "MySQL service did not become ready within 90s."
  }

  $rootPw = Get-PasswordOrPrompt 'Enter MySQL root password (existing or new)' $RootPassword -noPrompt:$NoPrompt
  $appPw = Get-PasswordOrPrompt "Enter password for MySQL app user '$AppUser'" $AppPassword -noPrompt:$NoPrompt

  $rootPwSql = Escape-SqlString $rootPw
  $appPwSql = Escape-SqlString $appPw
  $appUserSql = Escape-SqlString $AppUser
  if ($DbName -notmatch '^[A-Za-z0-9_]+$') {
    throw "DbName must match ^[A-Za-z0-9_]+$ (got: $DbName)"
  }
  $dbNameSql = $DbName

  Write-Output 'Applying DB/user setup...'
  $sql = (
    @(
      "ALTER USER IF EXISTS 'root'@'localhost' IDENTIFIED BY '$rootPwSql';",
      "CREATE USER IF NOT EXISTS 'root'@'127.0.0.1' IDENTIFIED BY '$rootPwSql';",
      "CREATE DATABASE IF NOT EXISTS $dbNameSql CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
      "CREATE USER IF NOT EXISTS '$appUserSql'@'127.0.0.1' IDENTIFIED BY '$appPwSql';",
      "CREATE USER IF NOT EXISTS '$appUserSql'@'localhost' IDENTIFIED BY '$appPwSql';",
      "GRANT ALL PRIVILEGES ON $dbNameSql.* TO '$appUserSql'@'127.0.0.1';",
      "GRANT ALL PRIVILEGES ON $dbNameSql.* TO '$appUserSql'@'localhost';",
      "FLUSH PRIVILEGES;"
    ) -join "`n"
  )

  # Apply setup using whichever auth mode worked for readiness.
  if ($PSCmdlet.ShouldProcess("mysql.exe", 'Apply DB/user setup SQL')) {
    $applyCode = (Invoke-MySqlQuery -MySqlExe $mysqlExe -Query $sql -AuthMode $authMode -Password $rootPw)
    if ($applyCode -ne 0) { throw "Failed to apply SQL setup (exit code $applyCode)" }
  }

  if (-not $DbOnly -and $AddBinToPath) {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    if ($machinePath -notmatch [Regex]::Escape($binDir)) {
      if ($PSCmdlet.ShouldProcess('Machine Path', "Add $binDir")) {
        [Environment]::SetEnvironmentVariable('Path', ($machinePath.TrimEnd(';') + ';' + $binDir), 'Machine')
        Write-Output "Added to Machine PATH: $binDir"
      }
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
    if ($PSCmdlet.ShouldProcess($backendEnvPath, 'Write backend .env (contains password)')) {
      $envLines | Set-Content -Path $backendEnvPath -Encoding UTF8
      Write-Output "Wrote backend env: $backendEnvPath"
    }
  }

  # Best-effort: clear plaintext password variables.
  $rootPw = $null
  $appPw = $null

  Write-Output ''
  Write-Output 'MySQL service setup complete.'
  Write-Output "Service: $ServiceName (Auto)"
  Write-Output "DB: $DbName"
  Write-Output "User: $AppUser"
  Write-Output "Port: $Port"
  Write-Output "Log: $logPath"

} finally {
  if ($transcriptStarted) {
    Stop-Transcript | Out-Null
  }
}
