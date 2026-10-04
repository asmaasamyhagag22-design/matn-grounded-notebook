# Export decks through PowerPoint: every slide to PNG (<OutDir>/slide_01.png, ...) and the whole deck to PDF.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/export_deck.ps1 -Pptx a.pptx,b.pptx -OutDir outA,outB -Pdf a.pdf,b.pdf
# Trick 28 (PDF part). One PowerPoint session for all decks; each deck opens read-only with no window.
param(
    [Parameter(Mandatory = $true)][string[]]$Pptx,
    [Parameter(Mandatory = $true)][string[]]$OutDir,
    [Parameter(Mandatory = $true)][string[]]$Pdf,
    [int]$Width = 1280,
    [int]$Height = 720
)
$ErrorActionPreference = "Stop"
$Pptx = @($Pptx | ForEach-Object { $_ -split "," }); $OutDir = @($OutDir | ForEach-Object { $_ -split "," })
$Pdf = @($Pdf | ForEach-Object { $_ -split "," })
if ($Pptx.Count -ne $OutDir.Count -or $Pptx.Count -ne $Pdf.Count) { throw "PPTX_OUTDIR_PDF_COUNTS_DIFFER" }
$ppSaveAsPDF = 32
$app = New-Object -ComObject PowerPoint.Application
try {
    for ($i = 0; $i -lt $Pptx.Count; $i++) {
        $out = New-Item -ItemType Directory -Force $OutDir[$i]
        Get-ChildItem $out.FullName -Filter "slide_*.png" | Remove-Item
        $pres = $app.Presentations.Open((Resolve-Path $Pptx[$i]).Path, -1, 0, 0)
        try {
            foreach ($slide in $pres.Slides) {
                $name = "slide_{0:D2}.png" -f $slide.SlideIndex
                $slide.Export((Join-Path $out.FullName $name), "PNG", $Width, $Height)
            }
            $pdfPath = [System.IO.Path]::GetFullPath($Pdf[$i])
            $pres.SaveAs($pdfPath, $ppSaveAsPDF)
        } finally { $pres.Close() }
        Write-Output "exported $($Pptx[$i])"
    }
} finally {
    $app.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}
