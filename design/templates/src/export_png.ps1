# Export every slide of a .pptx to PNG through PowerPoint: <OutDir>/slide_01.png, slide_02.png, ...
# Usage: powershell -ExecutionPolicy Bypass -File design/templates/src/export_png.ps1 -Pptx deck.pptx -OutDir out/png
param(
    [Parameter(Mandatory = $true)][string[]]$Pptx,
    [Parameter(Mandatory = $true)][string[]]$OutDir,
    [int]$Width = 1280,
    [int]$Height = 720
)
$ErrorActionPreference = "Stop"
if ($Pptx.Count -ne $OutDir.Count) { throw "PPTX_AND_OUTDIR_COUNTS_DIFFER" }
$app = New-Object -ComObject PowerPoint.Application
try {
    for ($i = 0; $i -lt $Pptx.Count; $i++) {
        $out = New-Item -ItemType Directory -Force $OutDir[$i]
        Get-ChildItem $out.FullName -Filter "slide_*.png" | Remove-Item
        $pres = $app.Presentations.Open((Resolve-Path $Pptx[$i]).Path, -1, 0, 0)  # read-only, no window
        try {
            foreach ($slide in $pres.Slides) {
                $name = "slide_{0:D2}.png" -f $slide.SlideIndex
                $slide.Export((Join-Path $out.FullName $name), "PNG", $Width, $Height)
            }
        } finally { $pres.Close() }
    }
} finally {
    $app.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}
