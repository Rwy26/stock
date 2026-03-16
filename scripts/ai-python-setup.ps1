[CmdletBinding()]
param(
  [string]$EnvPath = "$PSScriptRoot\..\.venv-ai",
  [switch]$CpuOnly
)

$ErrorActionPreference = 'Stop'

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "ai-python-setup-$ts.txt"

function Log([string]$message) {
  $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $message
  $line | Out-File -FilePath $logPath -Append -Encoding utf8
  Write-Host $line
}

Log "==== AI Python Setup (Windows) ===="
Log "EnvPath: $EnvPath"

$py = $null
try {
  $py = (Get-Command py -ErrorAction Stop).Source
}
catch {
  try { $py = (Get-Command python -ErrorAction Stop).Source } catch { }
}
if (-not $py) { throw "Python이 필요합니다. (현재 PC에는 Python 3.11이 설치되어 있어야 합니다)" }

# Create venv
if (-not (Test-Path $EnvPath)) {
  Log "Creating venv..."
  & $py -m venv $EnvPath
}

$pip = Join-Path $EnvPath 'Scripts\python.exe'
Log "Python: $pip"

Log "Upgrading pip/setuptools/wheel..."
& $pip -m pip install --upgrade pip setuptools wheel | Out-Null

$basePkgs = @('ipykernel', 'jupyter', 'numpy', 'pandas', 'matplotlib', 'scipy', 'scikit-learn', 'tqdm', 'rich', 'python-dotenv')
Log "Installing base packages..."
& $pip -m pip install @basePkgs | Out-Null

if ($CpuOnly) {
  Log "Installing PyTorch (CPU-only)..."
  & $pip -m pip install torch torchvision torchaudio | Out-Null
}
else {
  Log "Installing PyTorch (NVIDIA CUDA build via PyTorch index)..."
  # NOTE: This uses the official PyTorch CUDA wheel index. It does NOT require local CUDA toolkit.
  & $pip -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124 | Out-Null
}

Log "Registering Jupyter kernel..."
& $pip -m ipykernel install --user --name ai-venv --display-name "Python (AI venv)" | Out-Null

Log "Done. Log: $logPath"
Log "Next: run scripts\\ai-gpu-test.ps1 to verify GPU."
