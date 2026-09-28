[CmdletBinding()]
param(
    [string]$Wheelhouse = "",
    [string]$Venv = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LockFile = Join-Path $ProjectRoot "requirements.lock.txt"
if (-not $Wheelhouse) {
    $Wheelhouse = Join-Path $ProjectRoot "wheelhouse"
}
if (-not $Venv) {
    $Venv = Join-Path $ProjectRoot ".venv-offline"
}
$Wheelhouse = [System.IO.Path]::GetFullPath($Wheelhouse)
$Venv = [System.IO.Path]::GetFullPath($Venv)

if (-not (Test-Path -LiteralPath $Wheelhouse -PathType Container)) {
    throw "Wheelhouse does not exist: $Wheelhouse"
}
if (Test-Path -LiteralPath $Venv) {
    throw "Target virtual environment already exists; refusing to overwrite it: $Venv"
}

py -3.11 -m venv $Venv
if ($LASTEXITCODE -ne 0) {
    throw "venv creation failed with exit code $LASTEXITCODE"
}
$Python = Join-Path $Venv "Scripts\python.exe"
& $Python -m pip install --no-index --find-links $Wheelhouse --requirement $LockFile
if ($LASTEXITCODE -ne 0) {
    throw "offline pip install failed with exit code $LASTEXITCODE"
}
& $Python -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "pip check failed with exit code $LASTEXITCODE"
}
Write-Host "Installed locked dependencies without an index into: $Venv"
