# Render a title slide and one content slide for every installed Office theme (.thmx), through PowerPoint.
# Output: <OutDir>/<theme name>_1.png (title) and _2.png (content), plus themes.json listing what was rendered.
# Usage: powershell -ExecutionPolicy Bypass -File design/templates/src/preview_office_themes.ps1 -OutDir out/gallery/themes
param(
    [string]$OutDir = "out/gallery/themes",
    [int]$Width = 960,
    [int]$Height = 540
)
$ErrorActionPreference = "Stop"
if (Get-Process POWERPNT -ErrorAction SilentlyContinue) { throw "POWERPOINT_IN_USE: close PowerPoint first" }

$themeDirs = @("$env:ProgramFiles\Microsoft Office\root\Document Themes 16",
               "${env:ProgramFiles(x86)}\Microsoft Office\root\Document Themes 16")
$themes = foreach ($dir in $themeDirs) { if (Test-Path $dir) { Get-ChildItem $dir -Filter *.thmx } }
$out = New-Item -ItemType Directory -Force $OutDir
$ppLayoutTitle = 1; $ppLayoutText = 2

$app = New-Object -ComObject PowerPoint.Application
$rendered = @()
try {
    foreach ($theme in $themes) {
        $name = $theme.BaseName
        $pres = $app.Presentations.Add(0)  # msoFalse: no window
        try {
            $pres.PageSetup.SlideWidth = 960; $pres.PageSetup.SlideHeight = 540
            $pres.ApplyTheme($theme.FullName)
            $title = $pres.Slides.Add(1, $ppLayoutTitle)
            $title.Shapes(1).TextFrame.TextRange.Text = $name
            $title.Shapes(2).TextFrame.TextRange.Text = "Office theme preview"
            $content = $pres.Slides.Add(2, $ppLayoutText)
            $content.Shapes(1).TextFrame.TextRange.Text = "Sample content slide"
            $content.Shapes(2).TextFrame.TextRange.Text = "First sample point`rSecond sample point`rThird sample point"
            $title.Export((Join-Path $out.FullName "$($name)_1.png"), "PNG", $Width, $Height)
            $content.Export((Join-Path $out.FullName "$($name)_2.png"), "PNG", $Width, $Height)
            $rendered += [ordered]@{ name = $name; path = $theme.FullName }
        } finally {
            $pres.Close()
        }
    }
} finally {
    $app.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}
$rendered | ConvertTo-Json | Out-File -Encoding utf8 (Join-Path $out.FullName "themes.json")
Write-Output "rendered $($rendered.Count) themes into $($out.FullName)"
