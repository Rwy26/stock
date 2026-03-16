$ErrorActionPreference = 'SilentlyContinue'

function Sync-ProcessPath {
  $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  $combined = @($machinePath, $userPath, $env:Path) -join ';'
  $parts = $combined -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ }

  $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
  $deduped = foreach ($p in $parts) {
    if ($seen.Add($p)) { $p }
  }

  $env:Path = ($deduped -join ';')
}

Sync-ProcessPath

function Resolve-Exe($name, $candidates) {
  $cmd = Get-Command $name -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }

  foreach ($c in $candidates) {
    if (Test-Path $c) { return $c }
  }

  return $null
}

function Print-Header($title) {
  Write-Output ""
  Write-Output "=== $title ==="
}

function Print-CmdVersion($cmd, $cmdArgs) {
  $exists = Get-Command $cmd -ErrorAction SilentlyContinue
  if (-not $exists) {
    Write-Output "[MISSING] $cmd"
    return
  }

  if ($cmd -ieq 'python' -and $exists.Source -match 'WindowsApps\\python\.exe$') {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
      Write-Output "[WARN] python resolves to Microsoft Store alias (WindowsApps\\python.exe); using 'py -3' instead"
      $out = & py -3 @cmdArgs 2>&1
      $outStr = ($out | Out-String).Trim()
      if ($outStr) {
        Write-Output "[OK] py -3 $($cmdArgs -join ' ')"
        Write-Output $outStr
      }
    } else {
      Write-Output "[WARN] python resolves to Microsoft Store alias (WindowsApps\\python.exe); install Python or disable App Execution Alias"
    }
    return
  }

  $out = & $cmd @cmdArgs 2>&1
  $outStr = ($out | Out-String).Trim()
  if ($outStr) {
    Write-Output "[OK] $cmd $($cmdArgs -join ' ')"
    Write-Output $outStr
  } else {
    Write-Output "[OK] $cmd"
  }
}

Print-Header "Workspace"
Write-Output "PWD: $PWD"

Print-Header "Node.js"
$nodeExe = Resolve-Exe 'node' @(
  "$env:ProgramFiles\nodejs\node.exe",
  "$env:ProgramFiles(x86)\nodejs\node.exe"
)

$npmExe = Resolve-Exe 'npm.cmd' @(
  "$env:ProgramFiles\nodejs\npm.cmd",
  "$env:ProgramFiles(x86)\nodejs\npm.cmd"
)
if (-not $npmExe) {
  $npmExe = Resolve-Exe 'npm' @(
    "$env:ProgramFiles\nodejs\npm.cmd",
    "$env:ProgramFiles\nodejs\npm.ps1",
    "$env:ProgramFiles(x86)\nodejs\npm.cmd",
    "$env:ProgramFiles(x86)\nodejs\npm.ps1"
  )
}

if ($nodeExe) {
  Write-Output "[OK] node => $nodeExe"
  & $nodeExe -v
} else {
  Write-Output "[MISSING] node"
}

if ($npmExe) {
  Write-Output "[OK] npm => $npmExe"
  & $npmExe -v
} else {
  Write-Output "[MISSING] npm"
}

Print-Header "Python"
$pythonExe = Resolve-Exe 'python' @(
  "$env:LocalAppData\Programs\Python\Python311\python.exe",
  "$env:LocalAppData\Programs\Python\Python312\python.exe",
  "$env:ProgramFiles\Python311\python.exe",
  "$env:ProgramFiles\Python312\python.exe"
)

if ($pythonExe) {
  Write-Output "[OK] python => $pythonExe"
  & $pythonExe --version

  $pipOut = & $pythonExe -m pip --version 2>&1
  $pipStr = ($pipOut | Out-String).Trim()
  if ($pipStr) {
    Write-Output "[OK] python -m pip --version"
    Write-Output $pipStr
  } else {
    Write-Output "[WARN] pip not available"
  }
} else {
  Write-Output "[MISSING] python"
}

Print-Header "Git"
Print-CmdVersion git @('--version')

Print-Header "MySQL"
$mysqlExe = Resolve-Exe 'mysql' @(
  "$env:ProgramFiles\MySQL\MySQL Server 8.4\bin\mysql.exe",
  "$env:ProgramFiles\MySQL\MySQL Server 8.0\bin\mysql.exe",
  "$env:ProgramFiles\MySQL\MySQL Server 8.1\bin\mysql.exe",
  "$env:ProgramFiles\MySQL\MySQL Server 8.2\bin\mysql.exe",
  "$env:ProgramFiles\MySQL\MySQL Server 8.3\bin\mysql.exe"
)

if ($mysqlExe) {
  Write-Output "[OK] mysql => $mysqlExe"
  & $mysqlExe --version
} else {
  Print-CmdVersion mysql @('--version')
}

Write-Output ""
Write-Output "Done."
