[CmdletBinding()]
param(
  [string]$RepoPath = (Get-Location).Path,
  [string]$MessagePrefix = 'auto-save',
  [switch]$Push,
  [string]$Remote = 'origin',
  [string]$Branch = ''
)

$ErrorActionPreference = 'Stop'

# Ensure TEMP/TMP point to an existing directory (scheduled tasks and some tooling can fail otherwise).
try {
  $fallbackTemp = Join-Path $env:LOCALAPPDATA 'Temp'
  if (-not (Test-Path $fallbackTemp)) {
    New-Item -ItemType Directory -Force -Path $fallbackTemp | Out-Null
  }
  if (-not $env:TEMP -or -not (Test-Path $env:TEMP)) { $env:TEMP = $fallbackTemp }
  if (-not $env:TMP -or -not (Test-Path $env:TMP)) { $env:TMP = $fallbackTemp }
} catch { }

function Exec([string]$cmd) {
  $out = & pwsh -NoProfile -Command $cmd 2>&1
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed ($LASTEXITCODE): $cmd`n$out"
  }
  return $out
}

Set-Location $RepoPath

# Ensure we are in a git work tree
$inside = (git rev-parse --is-inside-work-tree 2>$null)
if ($LASTEXITCODE -ne 0 -or $inside -ne 'true') {
  throw "Not a git repository: $RepoPath"
}

# Avoid concurrent runs (Task Scheduler overlap)
$lockPath = Join-Path $RepoPath '.git\auto-save.lock'
try {
  $lock = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
} catch {
  Write-Host 'Another auto-save is running; exiting.'
  exit 0
}

try {
  $changes = git status --porcelain=v1
  if (-not $changes) {
    Write-Host 'No changes.'
    exit 0
  }

  git add -A

  $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  $msg = "${MessagePrefix}: $ts"

  # Commit can fail if nothing staged (race) or user.name not set
  $commitOut = git commit -m $msg 2>&1
  if ($LASTEXITCODE -ne 0) {
    if ($commitOut -match 'nothing to commit') {
      Write-Host 'Nothing to commit.'
      exit 0
    }
    throw "git commit failed: $commitOut"
  }

  Write-Host $commitOut

  if ($Push) {
    $remoteUrl = (git remote get-url $Remote 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $remoteUrl) {
      throw "Remote '$Remote' is not configured. Configure a GitHub remote first."
    }

    if (-not $Branch) {
      $Branch = (git branch --show-current)
    }

    git push $Remote $Branch
    if ($LASTEXITCODE -ne 0) {
      throw 'git push failed.'
    }

    Write-Host "Pushed to $Remote/$Branch"
  }
} finally {
  if ($lock) { $lock.Dispose() }
}
