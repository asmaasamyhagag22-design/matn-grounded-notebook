# Start the Matn demo dashboard: one command, loopback only, offline.
# Usage (from matn/):  powershell -ExecutionPolicy Bypass -File .\run_dashboard.ps1
# Then open http://127.0.0.1:8501 (the browser opens by itself after a few seconds). Stop with Ctrl+C.
param([int]$Port = 8501, [switch]$NoBrowser)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "MISSING .venv: expected $python" }
if (-not (Test-Path (Join-Path $root "out\demo\manifest.json"))) {
    Write-Warning "out\demo\manifest.json is missing: build the cache first (docs\DEMO_RUNBOOK.md)."
}
$url = "http://127.0.0.1:$Port"
Write-Output "Matn dashboard: $url  (loopback only; Ctrl+C to stop)"
if (-not $NoBrowser) {
    Start-Job -ScriptBlock { param($u) Start-Sleep -Seconds 5; Start-Process $u } -ArgumentList $url | Out-Null
}
& $python -m streamlit run (Join-Path $root "app\dashboard.py") --server.address 127.0.0.1 --server.port $Port `
    --server.headless true --browser.gatherUsageStats false --global.developmentMode false
