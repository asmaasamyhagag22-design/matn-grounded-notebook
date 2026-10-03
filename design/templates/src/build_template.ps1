# Build one Matn gallery template from an installed Office theme, through PowerPoint (no downloads).
# Called by design/templates/src/build.py, which prepares the theme (or variant) .thmx and writes theme.json.
# The contract is docs/design/template-contract.md; layout geometry is design/templates/src/layouts.json.
param(
    [Parameter(Mandatory = $true)][string]$Thmx,
    [Parameter(Mandatory = $true)][string]$OutPptx,
    [Parameter(Mandatory = $true)][string]$Thumbnail,
    [Parameter(Mandatory = $true)][string]$HeadingFont,
    [Parameter(Mandatory = $true)][string]$BodyFont,
    [string]$ComplexFont = "Segoe UI",
    [string]$Label = "Matn template",
    [string]$LayoutsJson = "",
    [double]$AccentBrightness = 0,   # shade of accent1 for accent text and the chip (-0.5 darker .. +0.5 lighter)
    [switch]$TitleAccent,            # titles use the shaded accent (for themes whose own title color is too light)
    [ValidateSet("section", "plain")][string]$Divider = "section",
    [double]$TitleSlideSize = 0,     # 0 = title_slide_title_size from layouts.json
    [switch]$SubtitleLikeTitle       # title slide: the subtitle takes the title's color (theme subtitle too faint)
)
$ErrorActionPreference = "Stop"
if (-not $LayoutsJson) { $LayoutsJson = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "layouts.json" }

# PowerPoint constants
$ppTitle = 1; $ppBody = 2; $ppCenterTitle = 3; $ppSubtitle = 4; $ppChart = 8; $ppObject = 7
$msoAccent1 = 5; $msoText1 = 13
$msoRoundedRectangle = 5
$anchors = @{ top = 1; middle = 3; bottom = 4 }
$ppSaveAsOpenXMLPresentation = 24

$spec = Get-Content -Raw -Encoding UTF8 $LayoutsJson | ConvertFrom-Json

function Find-Layout($master, [string[]]$names, [int]$fallback) {
    foreach ($layout in $master.CustomLayouts) { if ($names -contains $layout.Name) { return $layout } }
    return $master.CustomLayouts.Item($fallback)
}

function Get-Placeholder($layout, [int[]]$types) {
    foreach ($shape in $layout.Shapes) {
        if ($shape.Type -eq 14 -and $types -contains $shape.PlaceholderFormat.Type) { return $shape }
    }
    return $null
}

function Set-Accent($color) {
    $color.ObjectThemeColor = $msoAccent1
    if ($AccentBrightness -ne 0) { $color.Brightness = $AccentBrightness }
}

function Grow-Title($title, [double]$size, [int]$lines) {
    # Make room for `lines` lines of `size` pt by growing the title box upward (its bottom edge stays).
    $need = $lines * 1.36 * $size + 10
    if ($title.Height -ge $need) { return }
    $bottom = $title.Top + $title.Height
    $title.Top = [single][Math]::Max(6, $bottom - $need)
    $title.Height = [single]($bottom - $title.Top)
}

function Set-TextStyle($shape, $style, [string]$prompt) {
    $frame = $shape.TextFrame2
    $frame.AutoSize = 0
    $frame.WordWrap = -1
    $range = $shape.TextFrame.TextRange
    $range.Text = $prompt
    $range.Font.Size = $style.size
    $range.ParagraphFormat.Bullet.Visible = [int][bool]$style.bullets
    if (-not $style.bullets) {
        $range.Paragraphs(1).ParagraphFormat.Bullet.Visible = 0
        $paragraph = $frame.TextRange.ParagraphFormat
        $paragraph.LeftIndent = 0; $paragraph.FirstLineIndent = 0; $paragraph.SpaceBefore = 0
    }
    if ($style.bold) { $range.Font.Bold = -1 }
    if ($style.italic) { $range.Font.Italic = -1 }
    if ($style.heading) { $frame.TextRange.Font.Name = "+mj-lt" }
    if ($style.color -eq "accent1") { Set-Accent $range.Font.Color }
    if ($style.anchor) { $shape.TextFrame.VerticalAnchor = $anchors[$style.anchor] }
    else { $shape.TextFrame.VerticalAnchor = $anchors["top"] }
}

$app = New-Object -ComObject PowerPoint.Application
try {
    $pres = $app.Presentations.Add(0)
    $pres.PageSetup.SlideWidth = 960
    $pres.PageSetup.SlideHeight = 540
    $pres.ApplyTheme((Resolve-Path $Thmx).Path)
    $master = $pres.SlideMaster
    $fonts = $master.Theme.ThemeFontScheme
    $fonts.MajorFont.Item(1).Name = $HeadingFont
    $fonts.MinorFont.Item(1).Name = $BodyFont
    $fonts.MajorFont.Item(2).Name = $ComplexFont
    $fonts.MinorFont.Item(2).Name = $ComplexFont
    # Some themes name a decorative font for bullets in the master styles; bullets use the body font instead.
    foreach ($styleIndex in 1..3) {  # ppDefaultStyle, ppTitleStyle, ppBodyStyle
        $range = $master.TextStyles.Item($styleIndex).TextFrame.TextRange
        foreach ($paragraph in $range.Paragraphs()) {
            $bullet = $paragraph.ParagraphFormat.Bullet
            if ($bullet.Type -eq 1 -and $bullet.Font.Name -notmatch '^(Wingdings|Symbol|Arial|Segoe UI|Calibri)') {
                $bullet.Font.Name = $BodyFont
            }
        }
    }

    $original = @($master.CustomLayouts | ForEach-Object { $_ })
    $bases = @{
        title      = Find-Layout $master @("Title Slide") 1
        content    = Find-Layout $master @("Title and Content") 2
        section    = Find-Layout $master @("Section Header") 3
        title_only = Find-Layout $master @("Title Only") 6
    }
    $body = Get-Placeholder $bases.content @($ppBody, $ppObject)
    $chipBand = $spec.chip.band_pt
    $area = @{ L = $body.Left; T = $body.Top; W = $body.Width; H = $body.Height - $chipBand }

    $index = $master.CustomLayouts.Count + 1
    foreach ($entry in $spec.layouts) {
        $base = $entry.base
        if ($base -eq "section" -and $Divider -eq "plain") { $base = "title_only" }
        $layout = $bases[$base].Duplicate()
        $layout.MoveTo($index); $index++
        $layout.Name = $entry.name
        $title = Get-Placeholder $layout @($ppTitle, $ppCenterTitle)
        $title.Name = "title"
        if ($base -eq "title_only") {
            $title.TextFrame.TextRange.Font.Size = $spec.content_title_size
            Grow-Title $title $spec.content_title_size 2
        }
        if ($base -eq "title") {
            $title.TextFrame.TextRange.Font.Size = [single]$(if ($TitleSlideSize) { $TitleSlideSize } else { $spec.title_slide_title_size })
        }
        if ($base -eq "section") { $title.TextFrame.TextRange.Font.Size = $spec.divider_title_size }
        if ($TitleAccent) { Set-Accent $title.TextFrame.TextRange.Font.Color }
        foreach ($shape in @($layout.Shapes | ForEach-Object { $_ })) {
            if ($shape.Type -ne 14) { continue }
            $type = $shape.PlaceholderFormat.Type
            if ($type -in @($ppBody, $ppSubtitle, $ppObject) -and $entry.base -in @("title", "section")) {
                $shape.Name = "subtitle"
            }
        }
        if ($base -eq "title" -and $SubtitleLikeTitle) {
            $sub = $layout.Shapes | Where-Object { $_.Name -eq "subtitle" }
            $sub.TextFrame.TextRange.Font.Color.RGB = $title.TextFrame.TextRange.Font.Color.RGB
        }
        if ($base -eq "title_only" -and $entry.base -eq "section") {
            # Plain divider on the content background: number, title and question stacked in the content area.
            $title.Left = [single]$area.L; $title.Width = [single]$area.W
            $full = $area.H + $chipBand  # dividers have no source chip
            $title.Top = [single]($area.T + 0.38 * $full); $title.Height = [single](0.36 * $full)
            $title.TextFrame.TextRange.Font.Size = $spec.divider_title_size
            $title.TextFrame.VerticalAnchor = $anchors["top"]
            $number = $layout.Shapes.AddPlaceholder($ppBody, $area.L, $area.T, 360, 0.36 * $full)
            $number.Name = "section_number"
            Set-TextStyle $number $spec.styles.number_plain "01"
            $subtitle = $layout.Shapes.AddPlaceholder($ppBody, $area.L, $area.T + 0.76 * $full, $area.W, 0.24 * $full)
            $subtitle.Name = "subtitle"
            Set-TextStyle $subtitle $spec.styles.subtitle "subtitle"
        }
        if ($base -eq "section") {
            $numberTop = [Math]::Max(24, $title.Top - 156)
            $number = $layout.Shapes.AddPlaceholder($ppBody, $title.Left, $numberTop, 320, 150)
            $number.Name = "section_number"
            Set-TextStyle $number $spec.styles.number "01"
            if (-not ($layout.Shapes | Where-Object { $_.Name -eq "subtitle" })) {
                # The theme's section header has no text box: the divider's question goes under the title.
                $subtitle = $layout.Shapes.AddPlaceholder($ppBody, $title.Left, $title.Top + $title.Height + 6,
                                                          $title.Width, 64)
                $subtitle.Name = "subtitle"
                Set-TextStyle $subtitle $spec.styles.subtitle "subtitle"
            }
        }
        foreach ($card in $entry.cards) {
            $shape = $layout.Shapes.AddShape($msoRoundedRectangle, $area.L + $card[0] * $area.W, $area.T + $card[1] * $area.H,
                                             $card[2] * $area.W, $card[3] * $area.H)
            $shape.Name = "card"
            $shape.Adjustments.Item(1) = 0.06
            $shape.Line.Visible = 0
            $shape.Fill.ForeColor.ObjectThemeColor = $msoText1  # a tint of the text color reads on light and dark
            $shape.Fill.Transparency = 0.93
            $shape.Shadow.Visible = 0
        }
        foreach ($p in $entry.placeholders) {
            $name, $styleName, $x, $y, $w, $h = $p
            $left = $area.L + $x * $area.W; $top = $area.T + $y * $area.H
            if ($styleName -eq "chart") {
                $shape = $layout.Shapes.AddPlaceholder($ppChart, $left, $top, $w * $area.W, $h * $area.H)
                $shape.Name = $name
                continue
            }
            $shape = $layout.Shapes.AddPlaceholder($ppBody, $left, $top, $w * $area.W, $h * $area.H)
            $shape.Name = $name
            Set-TextStyle $shape $spec.styles.$styleName $name
        }
        if ($entry.chip) {
            $chip = $layout.Shapes.AddPlaceholder($ppBody, $area.L, $area.T + $area.H + $chipBand - $spec.chip.h_pt,
                                                  $spec.chip.w_pt, $spec.chip.h_pt)
            $chip.Name = "source"
            $chip.AutoShapeType = $msoRoundedRectangle
            $chip.Adjustments.Item(1) = 0.5
            $chip.Fill.Visible = -1
            $chip.Fill.Solid()
            Set-Accent $chip.Fill.ForeColor
            $chip.Line.Visible = 0
            $chip.TextFrame.MarginLeft = 10; $chip.TextFrame.MarginRight = 10
            $chip.TextFrame.MarginTop = 2; $chip.TextFrame.MarginBottom = 2
            Set-TextStyle $chip $spec.styles.small "p. 1"
            $chip.TextFrame.VerticalAnchor = $anchors["middle"]
            $chip.TextFrame.TextRange.Font.Bold = -1
            $chip.TextFrame.TextRange.Font.Color.ObjectThemeColor = 14  # msoThemeColorBackground1
        }
    }
    foreach ($layout in $original) { $layout.Delete() }

    # Thumbnail: a temporary title slide, exported and removed so the template keeps no slides.
    $titleLayout = $master.CustomLayouts.Item(1)
    $slide = $pres.Slides.AddSlide(1, $titleLayout)
    foreach ($shape in $slide.Shapes) {
        if ($shape.Type -ne 14) { continue }
        if ($shape.PlaceholderFormat.Type -in @($ppTitle, $ppCenterTitle)) { $shape.TextFrame.TextRange.Text = $Label }
        elseif ($shape.PlaceholderFormat.Type -in @($ppSubtitle, $ppBody)) { $shape.TextFrame.TextRange.Text = "Matn" }
    }
    $slide.Export($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Thumbnail), "PNG", 640, 360)
    $slide.Delete()

    New-Item -ItemType Directory -Force (Split-Path $OutPptx) | Out-Null
    $pres.SaveAs($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutPptx), $ppSaveAsOpenXMLPresentation)
    $pres.Close()
} finally {
    $app.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}
Write-Output "built $OutPptx"
