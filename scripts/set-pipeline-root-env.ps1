[CmdletBinding()]
param(
  # Desired pipeline root. If omitted, prefers D:\AI\pipeline when available, otherwise C:\AI\pipeline.
  [string]$PipelineRoot = ''
)

$ErrorActionPreference = 'Stop'

function Resolve-DefaultPipelineRoot {
  if (Test-Path 'D:\') { return 'D:\AI\pipeline' }
  return 'C:\AI\pipeline'
}

if (-not $PipelineRoot) {
  $PipelineRoot = Resolve-DefaultPipelineRoot
}

# Ensure the directory exists (creates sub-structure elsewhere via setup-pipeline-dirs.ps1)
if (-not (Test-Path $PipelineRoot)) {
  New-Item -ItemType Directory -Force -Path $PipelineRoot | Out-Null
}

# Set for current process (this terminal)
$env:PIPELINE_ROOT = $PipelineRoot

# Persist for the current user
[Environment]::SetEnvironmentVariable('PIPELINE_ROOT', $PipelineRoot, 'User')

Write-Host "Set PIPELINE_ROOT (User + Process) => $PipelineRoot"
Write-Host "Note: new terminals/apps will pick it up automatically."
