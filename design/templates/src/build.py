"""Build the gallery templates listed in design/templates/src/gallery.json from installed Office themes.

For each entry: take the Office theme (or one of its built-in color variants, unpacked from the .thmx into a
standalone .thmx), run build_template.ps1 through PowerPoint, write theme.json and check the result with
matn_deck.templates.validate_template. Nothing is downloaded.

Usage: .venv\\Scripts\\python.exe design/templates/src/build.py [template_id ...]
"""
from __future__ import annotations

import colorsys
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parent
ROOT = SRC.parents[2]
GALLERY = SRC.parent
WORK = ROOT / "out" / "template-build"
sys.path.insert(0, str(ROOT))
from matn_deck.scoring import EMU_PER_PT, Rect  # noqa: E402
from matn_deck.templates import LAYOUTS, validate_template  # noqa: E402
from matn_deck.variants import default_layout, load_variants  # noqa: E402

THEME_DIRS = [Path(os.environ.get(var, "")) / "Microsoft Office" / "root" / "Document Themes 16"
              for var in ("ProgramFiles", "ProgramFiles(x86)")]
_CONTENT_TYPES = {
    "rels": "application/vnd.openxmlformats-package.relationships+xml",
    "xml": "application/xml",
    "jpeg": "image/jpeg",
    "png": "image/png",
}
_OVERRIDES = {
    r"theme/presentation\.xml": "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    r"theme/slideMasters/slideMaster\d+\.xml": "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml",
    r"theme/slideLayouts/slideLayout\d+\.xml": "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml",
    r"theme/theme/theme\d+\.xml": "application/vnd.openxmlformats-officedocument.theme+xml",
    r"theme/theme/themeManager\.xml": "application/vnd.openxmlformats-officedocument.themeManager+xml",
}


def theme_path(name: str) -> Path:
    for directory in THEME_DIRS:
        path = directory / f"{name}.thmx"
        if path.is_file():
            return path
    raise FileNotFoundError(f"OFFICE_THEME_NOT_INSTALLED:{name}")


def variant_modes(path: Path) -> dict[int, str]:
    """{variant number: "dark" | "light"} from each variant's slide-master color map (bg1 mapped to dk1 = dark)."""
    modes = {}
    with zipfile.ZipFile(path) as package:
        for name in package.namelist():
            match = re.fullmatch(r"themeVariants/variant(\d+)/theme/slideMasters/slideMaster1\.xml", name)
            if match:
                modes[int(match.group(1))] = "dark" if 'bg1="dk1"' in package.read(name).decode("utf-8") else "light"
    return dict(sorted(modes.items()))


def _contrast(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    def lum(rgb: tuple[float, ...]) -> float:
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    high, low = sorted((lum(a), lum(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def theme_colors(thmx: Path, accent: str = "accent1") -> tuple[tuple[float, ...], tuple[float, ...]]:
    """(background, accent) as RGB 0..1: bg1 follows the slide master's color map, as PowerPoint shows it."""
    with zipfile.ZipFile(thmx) as package:
        names = package.namelist()
        theme = package.read(next(n for n in names if re.fullmatch(r"theme/theme/theme\d+\.xml", n))).decode("utf-8")
        master = package.read(next(n for n in names if re.fullmatch(r"theme/slideMasters/slideMaster1\.xml", n)))
    bg_slot = re.search(r'<p:clrMap[^>]* bg1="(\w+)"', master.decode("utf-8")).group(1)

    def slot(name: str) -> tuple[float, ...]:
        block = re.search(rf"<a:{name}>(.*?)</a:{name}>", theme, re.S).group(1)
        value = re.search(r'(?:lastClr|srgbClr val)="([0-9A-Fa-f]{6})"', block).group(1)
        return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))

    return slot(bg_slot), slot(accent)


def accent_brightness(thmx: Path, minimum: float = 4.6) -> float:
    """Smallest PowerPoint brightness shift that gives accent1 `minimum` contrast on the background, keeping its hue
    (negative darkens on light backgrounds, positive lightens on dark ones)."""
    background, accent = theme_colors(thmx)
    hue, lightness, saturation = colorsys.rgb_to_hls(*accent)
    dark_background = colorsys.rgb_to_hls(*background)[1] < 0.5
    for step in range(0, 16):
        shift = step * 0.05 * (1 if dark_background else -1)
        shaded = lightness * (1 - shift) + shift if shift > 0 else lightness * (1 + shift)
        if _contrast(colorsys.hls_to_rgb(hue, shaded, saturation), background) >= minimum:
            return round(shift, 2)
    return round(0.75 * (1 if dark_background else -1), 2)


WHITE = (1.0, 1.0, 1.0)
DIVIDER_MIN = 4.6  # divider text is large, but every divider line is held to the body-text minimum


def darken_for(color: tuple[float, ...], text: tuple[float, ...] = WHITE, minimum: float = DIVIDER_MIN
               ) -> tuple[float, ...]:
    """`color` with its lightness lowered (hue kept) until `text` on it reaches `minimum` contrast."""
    hue, lightness, saturation = colorsys.rgb_to_hls(*color)
    while _contrast(colorsys.hls_to_rgb(hue, lightness, saturation), text) < minimum and lightness > 0:
        lightness = max(0.0, lightness - 0.01)
    return colorsys.hls_to_rgb(hue, lightness, saturation)


def hex_rgb(rgb: tuple[float, ...]) -> str:
    return "".join(f"{round(c * 255):02X}" for c in rgb)


def divider_colors(thmx: Path, entry: dict) -> dict:
    """Full-bleed divider fill taken from the theme accents, darkened until white text keeps DIVIDER_MIN."""
    slots = entry.get("divider_colors", ["accent1"])
    fills = [darken_for(theme_colors(thmx, slot)[1]) for slot in slots]
    contrast = min(_contrast(fill, WHITE) for fill in fills)
    return {"fill": [hex_rgb(f) for f in fills], "text": hex_rgb(WHITE), "contrast": round(contrast, 2),
            "from": slots}


NOMINAL_AREA = Rect(0, 0, 780 * EMU_PER_PT, 270 * EMU_PER_PT)  # fractions below are of the real area


def expanded_layouts(out: Path) -> Path:
    """design/variants.json expanded into the builder's input: every contract layout with its default placeholder
    geometry (fractions of the content area) and styles from layouts.json."""
    base = json.loads((SRC / "layouts.json").read_text(encoding="utf-8"))
    variants = load_variants()["variants"]
    missing = set(LAYOUTS) ^ set(variants)
    if missing:
        raise SystemExit(f"variants.json and the contract differ: {sorted(missing)}")
    entries = []
    for name in LAYOUTS:
        spec = variants[name]
        kind = spec.get("base", "title_only")
        placeholders = []
        for ph, style, rect in default_layout(name, NOMINAL_AREA):
            if spec.get("list") and ph == "body":
                style = "list"
            placeholders.append([ph, style, rect.x / NOMINAL_AREA.w, rect.y / NOMINAL_AREA.h,
                                 rect.w / NOMINAL_AREA.w, rect.h / NOMINAL_AREA.h])
        chip = kind == "title_only" and not name.startswith("matn:sources:")
        entries.append({"name": name, "base": kind, "chip": chip, "placeholders": placeholders})
    base["layouts"] = entries
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(base, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def variant_thmx(path: Path, variant: int, out: Path) -> Path:
    """Unpack themeVariants/variant<N>/ of an installed .thmx into a standalone .thmx PowerPoint can apply."""
    prefix = f"themeVariants/variant{variant}/"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        parts = [n for n in source.namelist() if n.startswith(prefix) and not n.endswith("/")]
        if not parts:
            raise ValueError(f"THEME_VARIANT_MISSING:{path.stem}:{variant}")
        overrides = []
        for name in parts:
            inner = name[len(prefix):]
            target.writestr(inner, source.read(name))
            for pattern, content_type in _OVERRIDES.items():
                if re.fullmatch(pattern, inner):
                    overrides.append(f'<Override PartName="/{inner}" ContentType="{content_type}"/>')
        defaults = "".join(f'<Default Extension="{ext}" ContentType="{ct}"/>' for ext, ct in _CONTENT_TYPES.items())
        target.writestr("[Content_Types].xml",
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                        f"{defaults}{''.join(overrides)}</Types>")
    return out


def build(entry: dict) -> None:
    source = theme_path(entry["theme"])
    thmx = source
    if entry.get("variant"):
        thmx = variant_thmx(source, entry["variant"], WORK / f"{entry['id']}.thmx")
    brightness = entry.get("accent_brightness", accent_brightness(thmx))
    folder = GALLERY / entry["id"]
    folder.mkdir(parents=True, exist_ok=True)
    layouts = expanded_layouts(WORK / f"{entry['id']}.layouts.json")
    area_out = WORK / f"{entry['id']}.area.json"
    divider = divider_colors(thmx, entry)
    spec = json.loads((SRC / "layouts.json").read_text(encoding="utf-8"))
    divider["safe"] = entry.get("divider_safe", spec["divider"]["safe"])
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SRC / "build_template.ps1"),
                    "-Thmx", str(thmx), "-OutPptx", str(folder / "template.pptx"),
                    "-Thumbnail", str(folder / "thumbnail.png"), "-HeadingFont", entry["fonts"]["heading"],
                    "-BodyFont", entry["fonts"]["body"], "-Label", entry["name_en"],
                    "-LayoutsJson", str(layouts), "-AreaOut", str(area_out),
                    "-AccentBrightness", str(brightness),
                    "-TitleSlideSize", str(entry.get("title_slide_title_size", 0)),
                    "-DividerFill", divider["fill"][0], "-DividerText", divider["text"],
                    "-DividerSafe", ",".join(map(str, divider["safe"]))]
                   + (["-DividerFill2", divider["fill"][1]] if len(divider["fill"]) > 1 else [])
                   + (["-Pattern", entry["pattern"]] if entry.get("pattern") else [])
                   + (["-Glow"] if entry.get("glow") else [])
                   + (["-TitleAccent"] if entry.get("title_accent") else [])
                   + (["-SubtitleLikeTitle"] if entry.get("subtitle_like_title") else []), check=True, cwd=ROOT)
    meta = {key: entry[key] for key in ("id", "name_ar", "name_en", "fonts", "mode")}
    meta.update({"family": entry.get("family", "classic"), "mood": entry["mood"], "audience": entry["audience"]})
    meta["source"] = f"Office theme {entry['theme']}" + (f" (variant {entry['variant']})" if entry.get("variant") else "")
    area = json.loads(area_out.read_text(encoding="utf-8-sig"))
    meta["content_area_pt"] = [round(area[k], 2) for k in ("left", "top", "width", "height")]
    meta["divider"] = divider
    meta["pattern"] = entry.get("pattern")
    meta["glow"] = bool(entry.get("glow"))
    (folder / "theme.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_template(folder / "template.pptx")
    if not report.ok:
        raise SystemExit(f"{entry['id']}: template invalid: {report.errors}")
    print(f"{entry['id']}: ok ({(folder / 'template.pptx').stat().st_size // 1024} KB, accent shift {brightness}, "
          f"divider contrast {divider['contrast']})")


def main(ids: list[str]) -> int:
    entries = json.loads((SRC / "gallery.json").read_text(encoding="utf-8"))["templates"]
    for entry in entries:
        if entry.get("excluded") or entry.get("family", "classic") != "classic":
            continue
        if not ids or entry["id"] in ids:
            build(entry)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
