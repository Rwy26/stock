[CmdletBinding()]
param(
  # Base directory to create the pipeline folder structure under.
  # If omitted, prefers D:\AI\pipeline when available, otherwise C:\AI\pipeline.
  [string]$BasePath = ''
)

$ErrorActionPreference = 'Stop'

function Resolve-DefaultBasePath {
  $dPreferred = 'D:\AI\pipeline'
  if (Test-Path 'D:\') {
    return $dPreferred
  }
  return 'C:\AI\pipeline'
}

if (-not $BasePath) {
  $BasePath = Resolve-DefaultBasePath
}

$paths = @(
  $BasePath,

  # Data tiers
  (Join-Path $BasePath 'data'),
  (Join-Path $BasePath 'data\raw'),
  (Join-Path $BasePath 'data\external'),
  (Join-Path $BasePath 'data\interim'),
  (Join-Path $BasePath 'data\processed'),

  # Outputs / artifacts
  (Join-Path $BasePath 'artifacts'),
  (Join-Path $BasePath 'artifacts\models'),
  (Join-Path $BasePath 'artifacts\metrics'),
  (Join-Path $BasePath 'artifacts\reports'),
  (Join-Path $BasePath 'artifacts\exports'),

  # Experiment/run outputs
  (Join-Path $BasePath 'runs'),
  (Join-Path $BasePath 'runs\train'),
  (Join-Path $BasePath 'runs\eval'),
  (Join-Path $BasePath 'runs\inference'),

  # Logs + scratch
  (Join-Path $BasePath 'logs'),
  (Join-Path $BasePath 'tmp')
)

foreach ($p in $paths) {
  if (-not (Test-Path $p)) {
    New-Item -ItemType Directory -Force -Path $p | Out-Null
  }
}

Write-Host "Created/verified pipeline directories under: $BasePath"
Write-Host "- data: raw/external/interim/processed"
Write-Host "- artifacts: models/metrics/reports/exports"
Write-Host "- runs: train/eval/inference"
Write-Host "- logs, tmp"
