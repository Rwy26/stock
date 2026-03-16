[CmdletBinding()]
param(
  [string]$Python = 'c:\stock\.venv-ai\Scripts\python.exe',
  [switch]$SyncFromUser
)

$ErrorActionPreference = 'Stop'

$names = @(
  'HF_HOME',
  'HUGGINGFACE_HUB_CACHE',
  'TRANSFORMERS_CACHE',
  'TORCH_HOME',
  'PIP_CACHE_DIR',
  'TEMP',
  'TMP'
)

Write-Host '=== User env vars (registry-backed) ==='
foreach ($n in $names) {
  $v = [Environment]::GetEnvironmentVariable($n, 'User')
  "{0}={1}" -f $n, ($v ?? '<null>')
}

Write-Host '=== Process env vars (current session) ==='
foreach ($n in $names) {
  $v = [Environment]::GetEnvironmentVariable($n, 'Process')
  "{0}={1}" -f $n, ($v ?? '<null>')
}

if ($SyncFromUser) {
  Write-Host '=== Sync Process env from User env (temporary) ==='
  foreach ($n in $names) {
    $v = [Environment]::GetEnvironmentVariable($n, 'User')
    if ($v) { Set-Item -Path ("Env:" + $n) -Value $v }
  }
  foreach ($n in $names) {
    $v = [Environment]::GetEnvironmentVariable($n, 'Process')
    "{0}={1}" -f $n, ($v ?? '<null>')
  }
}

if (-not (Test-Path $Python)) {
  throw "Python not found: $Python"
}

$py = @'
import os, sys, tempfile
from pathlib import Path

names = [
  "HF_HOME","HUGGINGFACE_HUB_CACHE","TRANSFORMERS_CACHE","TORCH_HOME","PIP_CACHE_DIR","TEMP","TMP"
]
print("=== env (python process) ===")
for n in names:
    print(f"{n}={os.environ.get(n)}")

print("=== torch ===")
try:
    import torch
    import torch.hub
    print("torch:", torch.__version__)
    print("torch.hub.get_dir():", torch.hub.get_dir())
except Exception as e:
    print("torch import failed:", e)

print("=== pip cache ===")
try:
    import subprocess
    out = subprocess.check_output([sys.executable, "-m", "pip", "cache", "dir"], text=True)
    print(out.strip())
except Exception as e:
    print("pip cache dir failed:", e)

print("=== huggingface hub download (optional) ===")
try:
    from huggingface_hub import hf_hub_download
    hub = os.environ.get("HUGGINGFACE_HUB_CACHE")
    print("hub cache:", hub)
    p = hf_hub_download(repo_id="hf-internal-testing/tiny-random-bert", filename="config.json")
    print("downloaded:", p)
    if hub:
        ok = Path(p).resolve().as_posix().lower().startswith(Path(hub).resolve().as_posix().lower())
        print("in hub cache:", ok)
except Exception as e:
    print("hf check skipped/failed:", e)

print("=== TEMP/TMP write test ===")
try:
    fd, p = tempfile.mkstemp(prefix="tmp-test-", suffix=".txt")
    os.close(fd)
    print("created:", p)
    try:
        Path(p).unlink()
        print("deleted: True")
    except Exception as e:
        print("deleted: False", e)
except Exception as e:
    print("tempfile failed:", e)
'@

$tmpDir = [Environment]::GetEnvironmentVariable('TEMP', 'Process')
if (-not $tmpDir) { $tmpDir = [IO.Path]::GetTempPath() }
$pyPath = Join-Path $tmpDir ('verify-ai-cache-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.py')
Set-Content -Path $pyPath -Value $py -Encoding utf8

Write-Host "=== Running: $Python $pyPath ==="
& $Python $pyPath
