# Build one Matn gallery template from an installed Office theme, through PowerPoint (no downloads).
# Called by design/templates/src/build.py, which prepares the theme (or variant) .thmx, expands the layout geometry
# from design/variants.json into -LayoutsJson, computes the divider colors, and writes theme.json.
# The contract is docs/design/template-contract.md.
param(
    [Parameter(Mandatory = $true)][string]$Thmx,
    [Parameter(Mandatory = $true)][string]$OutPptx,
    [Parameter(Mandatory = $true)][string]$Thumbnail,
    [Parameter(Mandatory = $true)][string]$HeadingFont,
    [Parameter(Mandatory = $true)][string]$BodyFont,
    [Parameter(Mandatory = $true)][string]$LayoutsJson,
    [Parameter(Mandatory = $true)][string]$AreaOut,    # writes the content area (pt) as JSON
    [string]$ComplexFont = "Segoe UI",
    [string]$Label = "Matn template",
    [double]$AccentBrightness = 0,   # shade of accent1 for accent text and the chip (-0.5 darker .. +0.5 lighter)
    [switch]$TitleAccent,            # titles use the shaded accent (for themes whose own title color is too light)
    [double]$TitleSlideSize = 0,     # 0 = title_slide_title_size from layouts.json
    [switch]$SubtitleLikeTitle,      # title slide: the subtitle takes the title's color (theme subtitle too faint)
    [string]$DividerFill = "",       # divider background "RRGGBB" (full bleed)
    [string]$DividerFill2 = "",      # optional second color: a diagonal gradient from DividerFill
    [string]$DividerText = "FFFFFF", # divider text color
    [string]$DividerSafe = "",       # "x,y,w,h" fractions of the slide; empty = layouts.json divider.safe
    [ValidateSet("", "dots", "lines", "mashrabiya")][string]$Pattern = "",  # optional divider pattern
    [switch]$Glow,                   # a subtle accent glow on content slides (from the cover gradient)
    [string]$BackgroundImage = "",  # optional deterministic 16:9 asset placed behind content layouts
    [switch]$CleanThemeArt,          # remove the donor Office theme's non-placeholder art
    [ValidateSet("color_block", "gradient", "outline_number")][string]$DividerStyle = "color_block",
    [string]$DividerNumberColor = "",
    [double]$DividerOutlineWidth = 4.5,
    [double]$SafeLeftPt = 0,
    [switch]$ThinRules
)
$ErrorActionPreference = "Stop"

# PowerPoint constants
$ppTitle = 1; $ppBody = 2; $ppCenterTitle = 3; $ppSubtitle = 4; $ppChart = 8; $ppObject = 7
$msoAccent1 = 5; $msoBackground1 = 14
$msoRoundedRectangle = 5; $msoOval = 9; $msoRectangle = 1
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

function Rgb([string]$hex) {
    # PowerPoint RGB is BGR-packed
    $r = [Convert]::ToInt32($hex.Substring(0, 2), 16); $g = [Convert]::ToInt32($hex.Substring(2, 2), 16)
    $b = [Convert]::ToInt32($hex.Substring(4, 2), 16)
    return $r + 256 * $g + 65536 * $b
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
    if ($style.color -eq "bg1") { $range.Font.Color.ObjectThemeColor = $msoBackground1 }
    if ($style.align -eq "center") { $range.ParagraphFormat.Alignment = 2 }
    $shape.TextFrame.VerticalAnchor = $anchors[$(if ($style.anchor) { $style.anchor } else { "top" })]
    if ($style.shape -eq "oval") {
        $shape.AutoShapeType = $msoOval
        $shape.Fill.Visible = -1; $shape.Fill.Solid(); Set-Accent $shape.Fill.ForeColor
        $shape.Line.Visible = 0
        $shape.TextFrame.MarginLeft = 0; $shape.TextFrame.MarginRight = 0
        $shape.TextFrame.MarginTop = 0; $shape.TextFrame.MarginBottom = 0
    }
}

function Add-Divider($layout, $title, $area) {
    # Full-bleed theme color (or gradient), giant number, the title and the one-line question in the safe zone.
    $layout.FollowMasterBackground = 0
    $fill = $layout.Background.Fill
    if ($DividerFill2) {
        $fill.TwoColorGradient(3, 1)  # msoGradientDiagonalUp
        $fill.ForeColor.RGB = Rgb $DividerFill; $fill.BackColor.RGB = Rgb $DividerFill2
    } else {
        $fill.Solid(); $fill.ForeColor.RGB = Rgb $DividerFill
    }
    $layout.DisplayMasterShapes = 0
    foreach ($shape in @($layout.Shapes | ForEach-Object { $_ })) {
        if ($shape.Type -eq 14 -and $shape.PlaceholderFormat.Type -notin @($ppTitle, $ppCenterTitle)) { $shape.Delete() }
    }
    $d = $spec.divider
    $safe = $(if ($DividerSafe) { $DividerSafe -split "," | ForEach-Object { [double]$_ } } else { $d.safe })
    $W = 960; $H = 540
    $sx = $safe[0] * $W; $sy = $safe[1] * $H; $sw = $safe[2] * $W; $sh = $safe[3] * $H
    $number = $layout.Shapes.AddPlaceholder($ppBody, $sx, $sy, $sw * 0.6, $sh * $d.number_h)
    $number.Name = "section_number"
    Set-TextStyle $number @{ size = $d.number_size; bullets = $false; bold = $true; heading = $true; anchor = "bottom" } "01"
    $number.TextFrame.MarginLeft = 0; $number.TextFrame.MarginTop = 0; $number.TextFrame.MarginBottom = 0
    $number.TextFrame.TextRange.ParagraphFormat.SpaceWithin = 0.85
    $title.Left = [single]$sx; $title.Width = [single]$sw
    $title.Top = [single]($sy + $sh * ($d.number_h + 0.02)); $title.Height = [single]($sh * $d.title_h)
    $title.TextFrame.TextRange.Font.Size = $d.title_size
    $title.TextFrame.VerticalAnchor = $anchors["top"]
    $title.TextFrame.MarginLeft = 0
    $subtitle = $layout.Shapes.AddPlaceholder($ppBody, $sx, $sy + $sh * ($d.number_h + $d.title_h + 0.04), $sw,
                                              $sh * (1 - $d.number_h - $d.title_h - 0.04))
    $subtitle.Name = "subtitle"
    Set-TextStyle $subtitle @{ size = $d.subtitle_size; bullets = $false } "subtitle"
    $subtitle.TextFrame.MarginLeft = 0
    foreach ($shape in @($number, $title, $subtitle)) { $shape.TextFrame.TextRange.Font.Color.RGB = Rgb $DividerText }
    if ($DividerNumberColor) { $number.TextFrame.TextRange.Font.Color.RGB = Rgb $DividerNumberColor }
    if ($DividerStyle -eq "outline_number") {
        $number.TextFrame2.TextRange.Font.Fill.Visible = 0
        $number.TextFrame2.TextRange.Font.Line.Visible = -1
        $number.TextFrame2.TextRange.Font.Line.Weight = $DividerOutlineWidth
        $number.TextFrame2.TextRange.Font.Line.ForeColor.RGB = Rgb $(if ($DividerNumberColor) { $DividerNumberColor } else { $DividerText })
    }
    if ($ThinRules) {
        foreach ($y in @($sy, $sy + $sh)) {
            $rule = $layout.Shapes.AddLine($sx, $y, $sx + $sw, $y)
            $rule.Name = "divider_rule"; $rule.Line.ForeColor.RGB = Rgb $DividerText
            $rule.Line.Transparency = 0.45; $rule.Line.Weight = 1
        }
    }
    if ($Pattern) {
        # A subtle band of native shapes along the bottom edge, below the safe zone.
        $top = $sy + $sh + 8; $rows = [Math]::Max(1, [Math]::Floor(($H - $top - 10) / 14))
        for ($r = 0; $r -lt [Math]::Min($rows, 3); $r++) {
            for ($c = 0; $c -lt 64; $c++) {
                $x = 12 + $c * 15 + ($r % 2) * 7.5; $y = $top + $r * 14
                if ($Pattern -eq "dots") { $dot = $layout.Shapes.AddShape($msoOval, $x, $y, 4, 4) }
                elseif ($Pattern -eq "mashrabiya") {
                    $dot = $layout.Shapes.AddShape(4, $x, $y, 8, 8) # diamond
                    $dot.Fill.Visible = 0; $dot.Line.Visible = -1
                } else { $dot = $layout.Shapes.AddShape($msoRectangle, $x, $y, 9, 2) }
                $dot.Name = "pattern"; $dot.Line.Visible = 0
                if ($Pattern -eq "mashrabiya") {
                    $dot.Line.Visible = -1; $dot.Line.ForeColor.RGB = Rgb $DividerText; $dot.Line.Transparency = 0.78
                } else {
                    $dot.Fill.ForeColor.RGB = Rgb $DividerText; $dot.Fill.Transparency = 0.8
                }
            }
        }
    }
}

function Add-Glow($layout) {
    # A soft accent glow in the lower-right corner, behind everything (radial gradient to transparent).
    $glow = $layout.Shapes.AddShape($msoOval, 600, 250, 560, 460)
    $glow.Name = "glow"; $glow.Line.Visible = 0
    $glow.Fill.OneColorGradient(7, 1, 1)  # msoGradientFromCenter
    Set-Accent $glow.Fill.GradientStops.Item(1).Color
    Set-Accent $glow.Fill.GradientStops.Item(2).Color
    $glow.Fill.GradientStops.Item(1).Transparency = 0.72
    $glow.Fill.GradientStops.Item(2).Transparency = 1.0
    $glow.ZOrder(1)  # msoSendToBack
}

$app = New-Object -ComObject PowerPoint.Application
try {
    $pres = $app.Presentations.Add(0)
    $pres.PageSetup.SlideWidth = 960
    $pres.PageSetup.SlideHeight = 540
    $pres.ApplyTheme((Resolve-Path $Thmx).Path)
    $master = $pres.SlideMaster
    if ($CleanThemeArt) {
        foreach ($shape in @($master.Shapes | ForEach-Object { $_ })) {
            if ($shape.Type -ne 14) { $shape.Delete() }
        }
    }
    if ($BackgroundImage) {
        $masterBg = $master.Shapes.AddPicture((Resolve-Path $BackgroundImage).Path, 0, -1, 0, 0, 960, 540)
        $masterBg.Name = "creative_background_master"; $masterBg.ZOrder(1)
    }
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
        title_only = Find-Layout $master @("Title Only") 6
    }
    $body = Get-Placeholder $bases.content @($ppBody, $ppObject)
    $titleOnly = Get-Placeholder $bases.title_only @($ppTitle, $ppCenterTitle)
    $chipBand = $spec.chip.band_pt
    # The content area starts below the title box (some themes let the body overlap it).
    $areaTop = [Math]::Max($body.Top, $titleOnly.Top + $titleOnly.Height + 8)
    $areaLeft = [Math]::Max($body.Left, $SafeLeftPt)
    $area = @{ L = $areaLeft; T = $areaTop; W = $body.Left + $body.Width - $areaLeft;
               H = $body.Top + $body.Height - $areaTop - $chipBand }
    @{ left = $area.L; top = $area.T; width = $area.W; height = $area.H; chip_band = $chipBand } |
        ConvertTo-Json | Set-Content -Encoding UTF8 $AreaOut

    $index = $master.CustomLayouts.Count + 1
    foreach ($entry in $spec.layouts) {
        $base = $entry.base
        $layout = $bases[$(if ($base -eq "divider") { "title_only" } else { $base })].Duplicate()
        $layout.MoveTo($index); $index++
        $layout.Name = $entry.name
        if ($CleanThemeArt) {
            foreach ($shape in @($layout.Shapes | ForEach-Object { $_ })) {
                if ($shape.Type -ne 14) { $shape.Delete() }
            }
        }
        if ($BackgroundImage -and $base -ne "divider") {
            $layoutBg = $layout.Shapes.AddPicture((Resolve-Path $BackgroundImage).Path, 0, -1, 0, 0, 960, 540)
            $layoutBg.Name = "creative_background"; $layoutBg.ZOrder(1)
        }
        $title = Get-Placeholder $layout @($ppTitle, $ppCenterTitle)
        $title.Name = "title"
        if ($base -eq "title_only") {
            $title.TextFrame.TextRange.Font.Size = $spec.content_title_size
            Grow-Title $title $spec.content_title_size 2
            if ($Glow) { Add-Glow $layout }
        }
        if ($base -eq "title") {
            $title.TextFrame.TextRange.Font.Size = [single]$(if ($TitleSlideSize) { $TitleSlideSize } else { $spec.title_slide_title_size })
            foreach ($shape in @($layout.Shapes | ForEach-Object { $_ })) {
                if ($shape.Type -eq 14 -and $shape.PlaceholderFormat.Type -in @($ppBody, $ppSubtitle, $ppObject)) {
                    $shape.Name = "subtitle"
                }
            }
            if ($SubtitleLikeTitle) {
                $sub = $layout.Shapes | Where-Object { $_.Name -eq "subtitle" }
                $sub.TextFrame.TextRange.Font.Color.RGB = $title.TextFrame.TextRange.Font.Color.RGB
            }
        }
        if ($SafeLeftPt -gt 0 -and $base -ne "divider") {
            foreach ($shape in @($layout.Shapes | ForEach-Object { $_ })) {
                if ($shape.Type -ne 14 -or $shape.Left -ge $SafeLeftPt) { continue }
                $right = $shape.Left + $shape.Width
                $shape.Left = [single]$SafeLeftPt
                $shape.Width = [single][Math]::Max(1, $right - $SafeLeftPt)
            }
        }
        if ($TitleAccent -and $base -ne "divider") { Set-Accent $title.TextFrame.TextRange.Font.Color }
        if ($base -eq "divider") { Add-Divider $layout $title $area }
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
            $chip.TextFrame.TextRange.Font.Color.ObjectThemeColor = $msoBackground1
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
