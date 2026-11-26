<#
  run_dev.ps1 — jalankan dashboard di laptop (DEV), hanya bisa diakses dari laptop ini.
  Pemakaian:  powershell -ExecutionPolicy Bypass -File legacy\web-v4\run_dev.ps1   [-Port 8000]
#>
param([int]$Port = 8000)

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent (Split-Path -Parent $here)   # legacy\web-v4 -> root repo
$py   = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host "venv belum ada. Buat dari root repo:  python -m venv .venv ; .venv\Scripts\pip install -r legacy\web-v4\requirements.txt"
    exit 1
}
if (-not (Test-Path (Join-Path $here '.env'))) {
    Copy-Item (Join-Path $here '.env.example') (Join-Path $here '.env')
    Write-Host "legacy\web-v4\.env dibuat dari .env.example (Generate live NBU nonaktif)."
}

Set-Location $here
Write-Host "Dashboard DEV: http://127.0.0.1:$Port  (Ctrl+C untuk berhenti)"
& $py -m uvicorn app:app --host 127.0.0.1 --port $Port --reload
