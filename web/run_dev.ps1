<#
  run_dev.ps1 — jalankan dashboard di laptop (DEV), hanya bisa diakses dari laptop ini.
  Pemakaian:  powershell -ExecutionPolicy Bypass -File web\run_dev.ps1   [-Port 8000]
#>
param([int]$Port = 8000)

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py   = Join-Path (Split-Path -Parent $here) '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host "venv belum ada. Buat dari root repo:  python -m venv .venv ; .venv\Scripts\pip install -r web\requirements.txt"
    exit 1
}
if (-not (Test-Path (Join-Path $here '.env'))) {
    Copy-Item (Join-Path $here '.env.example') (Join-Path $here '.env')
    Write-Host "web\.env dibuat dari .env.example (Generate live NBU nonaktif)."
}

Set-Location $here
Write-Host "Dashboard DEV: http://127.0.0.1:$Port  (Ctrl+C untuk berhenti)"
& $py -m uvicorn app:app --host 127.0.0.1 --port $Port --reload
