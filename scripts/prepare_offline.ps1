[CmdletBinding()]
param(
    [string]$Wheelhouse = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LockFile = Join-Path $ProjectRoot "requirements.lock.txt"
if (-not $Wheelhouse) {
    $Wheelhouse = Join-Path $ProjectRoot "wheelhouse"
}
$Wheelhouse = [System.IO.Path]::GetFullPath($Wheelhouse)

if (Test-Path -LiteralPath $Wheelhouse) {
    throw "Wheelhouse already exists; refusing to mix or overwrite downloads: $Wheelhouse"
}

New-Item -ItemType Directory -Path $Wheelhouse | Out-Null
py -3.11 -m pip download --only-binary=:all: --dest $Wheelhouse --requirement $LockFile
if ($LASTEXITCODE -ne 0) {
    throw "pip download failed with exit code $LASTEXITCODE"
}

$hashLines = Get-ChildItem -LiteralPath $Wheelhouse -File |
    Sort-Object Name |
    ForEach-Object {
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $($_.Name)"
    }
$hashLines | Set-Content -LiteralPath (Join-Path $Wheelhouse "SHA256SUMS.txt") -Encoding UTF8
Write-Host "Prepared offline wheelhouse: $Wheelhouse"
