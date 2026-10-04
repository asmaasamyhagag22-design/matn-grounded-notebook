$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $repo ".venv\Scripts\python.exe"
$index = Join-Path $repo "out\demo_site\index.html"
$builder = Join-Path $repo "app\site\build_site.py"
$manifest = Join-Path $repo "out\demo\manifest.json"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Offline Python environment not found: $python"
}
if (-not (Test-Path -LiteralPath $manifest)) {
    throw "Demo cache not found. Follow docs/DEMO_RUNBOOK.md to rebuild out/demo first."
}

$needsBuild = -not (Test-Path -LiteralPath $index)
if (-not $needsBuild) {
    $indexTime = (Get-Item -LiteralPath $index).LastWriteTimeUtc
    $inputs = @($builder, $manifest, (Join-Path $repo "app\site\build_assets.py"),
        (Join-Path $repo "design\templates\src\gallery.json"))
    $needsBuild = ($inputs | Where-Object { (Get-Item -LiteralPath $_).LastWriteTimeUtc -gt $indexTime }).Count -gt 0
}
if ($needsBuild) {
    Push-Location $repo
    try { & $python -m app.site.build_site } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "Static demo site build failed." }
}

Start-Process -FilePath $index
