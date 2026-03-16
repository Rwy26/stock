[CmdletBinding()]
param(
  [string]$Base = 'D:\AI',
  [switch]$SkipMigrate
)

$ErrorActionPreference = 'Stop'

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "ai-cache-to-d-$ts.txt"

function Log([string]$message) {
  $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $message
  $line | Out-File -FilePath $logPath -Append -Encoding utf8
  Write-Host $line
}

function New-DirectoryIfMissing([string]$path) {
  if (-not (Test-Path $path)) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
  }
}

function Set-UserEnv([string]$name, [string]$value) {
  [Environment]::SetEnvironmentVariable($name, $value, 'User')
  Log "Set User env: $name=$value"
}

function Copy-Then-Backup([string]$src, [string]$dst) {
  if (-not (Test-Path $src)) {
    Log "Skip migrate (not found): $src"
    return
  }

  New-DirectoryIfMissing $dst

  $srcResolved = (Resolve-Path $src).Path
  $dstResolved = (Resolve-Path $dst).Path
  Log "Migrate: $srcResolved -> $dstResolved"

  # Use robocopy for performance & resiliency
  $rcLog = Join-Path (Split-Path $logPath -Parent) ("robocopy-{0}.log" -f ([IO.Path]::GetFileNameWithoutExtension($logPath)))
  $robocopyArgs = @(
    $srcResolved,
    $dstResolved,
    '/E',
    '/COPY:DAT',
    '/DCOPY:DAT',
    '/R:1',
    '/W:1',
    '/NP',
    '/XJ',
    "/LOG+:$rcLog"
  )

  $p = Start-Process -FilePath robocopy.exe -ArgumentList $robocopyArgs -Wait -PassThru -NoNewWindow
  # robocopy exit codes: 0-7 are success (with different meanings)
  if ($p.ExitCode -ge 8) {
    Log "WARN: Robocopy exit code $($p.ExitCode). See: $rcLog"
    # Don't hard-fail; keep original intact.
    return
  }

  $backup = "$srcResolved.bak-$ts"
  try {
    Rename-Item -Path $srcResolved -NewName (Split-Path $backup -Leaf) -ErrorAction Stop
    Log "Backed up original to: $backup"
  } catch {
    Log "WARN: Could not rename original folder for backup: $($_.Exception.Message)"
  }
}

Log "==== AI cache to D: ===="
Log "Base: $Base"

# 1) Create folder structure
$datasets = Join-Path $Base 'datasets'
$models = Join-Path $Base 'models'
$cache = Join-Path $Base 'cache'
$tmp = Join-Path $Base 'tmp'

New-DirectoryIfMissing $Base
New-DirectoryIfMissing $datasets
New-DirectoryIfMissing $models
New-DirectoryIfMissing $cache
New-DirectoryIfMissing $tmp

# Subfolders for specific tools
$hfHome = Join-Path $cache 'huggingface'
$hfHub = Join-Path $hfHome 'hub'
$hfXformers = Join-Path $hfHome 'transformers'
$torchHome = Join-Path $cache 'torch'
$pipCache = Join-Path $cache 'pip'

New-DirectoryIfMissing $hfHome
New-DirectoryIfMissing $hfHub
New-DirectoryIfMissing $hfXformers
New-DirectoryIfMissing $torchHome
New-DirectoryIfMissing $pipCache

# 2) Environment variables (User scope)
# HuggingFace ecosystem
Set-UserEnv 'HF_HOME' $hfHome
Set-UserEnv 'HUGGINGFACE_HUB_CACHE' $hfHub
Set-UserEnv 'TRANSFORMERS_CACHE' $hfXformers

# PyTorch cache
Set-UserEnv 'TORCH_HOME' $torchHome

# pip cache
Set-UserEnv 'PIP_CACHE_DIR' $pipCache

# Optional: temp for heavy downloads/extractions (kept conservative: only for python/hf tooling if they respect TMP/TEMP)
# This affects many apps; still useful for large model extraction. If you don't want this, comment these 2 lines.
Set-UserEnv 'TEMP' $tmp
Set-UserEnv 'TMP' $tmp

# 3) Migration (best-effort, safe copy then backup)
if (-not $SkipMigrate) {
  # Typical cache locations on Windows
  $userProfile = $env:USERPROFILE
  $localAppData = $env:LOCALAPPDATA

  $srcHf = Join-Path $userProfile '.cache\huggingface'
  $srcTorch = Join-Path $userProfile '.cache\torch'
  $srcPip = Join-Path $localAppData 'pip\Cache'

  Copy-Then-Backup $srcHf $hfHome
  Copy-Then-Backup $srcTorch $torchHome
  Copy-Then-Backup $srcPip $pipCache
} else {
  Log 'Skip migration: -SkipMigrate'
}

Log "Done. Log: $logPath"
Log 'NOTE: 새 환경변수는 새 터미널/새 VS Code 세션부터 적용됩니다.'
