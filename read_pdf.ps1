param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Path,
    [string]$Out,
    [switch]$Milestone
)
# Read one PDF offline: .\read_pdf.ps1 "C:\path\file.pdf" [-Out folder] [-Milestone]
# Writes reading.md, blocks.jsonl, report.md and overlays\ (default folder: out\read\<file name>).
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Offline Python environment not found: $python"
}
$pdf = (Resolve-Path -LiteralPath $Path).Path
if (-not $Out) {
    $Out = Join-Path $repo ("out\read\" + [IO.Path]::GetFileNameWithoutExtension($pdf))
}
$arguments = @("-m", "matn_reading", "read", $pdf, "--out", $Out)
if ($Milestone) { $arguments += "--milestone" }
Push-Location $repo
try {
    & $python @arguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
