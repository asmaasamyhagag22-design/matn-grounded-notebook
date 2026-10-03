"""Text measurement with the real font files, so overflow is found by code instead of PowerPoint autofit."""
from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

from PIL import ImageFont

from .design import Design

EMU_PER_PT = 12700
_UNITS = 1000  # fonts are loaded at 1000 px per em; widths scale linearly from there


class FontFileNotFound(RuntimeError):
    pass


def _font_dirs() -> list[Path]:
    dirs = []
    if os.environ.get("MATN_FONT_DIR"):
        dirs.append(Path(os.environ["MATN_FONT_DIR"]))
    if os.environ.get("WINDIR"):
        dirs.append(Path(os.environ["WINDIR"]) / "Fonts")
    if os.environ.get("LOCALAPPDATA"):
        dirs.append(Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts")
    home = Path.home()
    dirs += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), home / ".fonts", home / ".local/share/fonts",
             Path("/Library/Fonts"), home / "Library/Fonts"]
    return [d for d in dirs if d.is_dir()]


@lru_cache(maxsize=1)
def _font_index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    for directory in _font_dirs():
        for root, _, files in os.walk(directory):
            for name in files:
                index.setdefault(name.lower(), Path(root) / name)
    return index


@lru_cache(maxsize=16)
def _load_font(candidates: tuple[str, ...]) -> ImageFont.FreeTypeFont:
    index = _font_index()
    for name in candidates:
        path = index.get(name.lower())
        if path is not None:
            return ImageFont.truetype(str(path), _UNITS, layout_engine=ImageFont.Layout.BASIC)
    raise FontFileNotFound(f"FONT_FILE_NOT_FOUND: none of {list(candidates)}; set MATN_FONT_DIR")


_REGULAR_STYLES = {"regular", "normal", "roman", "book"}


@lru_cache(maxsize=1)
def _family_index() -> dict[str, tuple[Path, str | None]]:
    """'family style' (lowercase) -> (font file, variation instance or None), as PowerPoint names faces."""
    index: dict[str, tuple[Path, str | None]] = {}
    for name, path in sorted(_font_index().items()):
        if not name.endswith((".ttf", ".otf", ".ttc")):
            continue
        try:
            font = ImageFont.truetype(str(path), 10)
            family, style = font.getname()
        except OSError:
            continue
        family = family or ""
        regular = (style or "").lower() in _REGULAR_STYLES
        index.setdefault(family.lower() if regular else f"{family} {style}".lower(), (path, None))
        try:
            instances = [n.decode() if isinstance(n, bytes) else n for n in font.get_variation_names()]
        except (OSError, AttributeError):
            instances = []
        for instance in instances:
            index.setdefault(f"{family} {instance}".lower(), (path, instance))
    return index


def font_file(name: str) -> Path | None:
    """Font file for a PowerPoint typeface name (family plus style or variable instance, e.g. "Bahnschrift SemiBold")."""
    entry = _family_index().get(name.lower())
    return entry[0] if entry else None


@lru_cache(maxsize=64)
def load_face(name: str, bold: bool = False, italic: bool = False) -> ImageFont.FreeTypeFont:
    """The face PowerPoint would use for typeface `name` with bold/italic, at 1000 px per em."""
    index = _family_index()
    style = " ".join(s for s, on in (("bold", bold), ("italic", italic)) if on)
    candidates = [f"{name} {style}".lower()] if style else []
    candidates += [name.lower()]
    for key in candidates:
        if key in index:
            path, instance = index[key]
            font = ImageFont.truetype(str(path), _UNITS, layout_engine=ImageFont.Layout.BASIC)
            if instance is not None:
                font.set_variation_by_name(instance)
            return font
    raise FontFileNotFound(f"FONT_FILE_NOT_FOUND: {name!r}; set MATN_FONT_DIR")


class TextMeasurer:
    def __init__(self, design: Design) -> None:
        font = design.tokens["font"]
        self._files = font["files"]
        self._line_height_em = font["line_height_em"]
        self.width_safety = font["width_safety"]
        self._advances: dict[tuple[bool, bool, str], float] = {}

    def _font(self, bold: bool, italic: bool) -> ImageFont.FreeTypeFont:
        face = {(False, False): "regular", (True, False): "bold", (False, True): "italic",
                (True, True): "bold_italic"}[(bold, italic)]
        return _load_font(tuple(self._files[face]))

    def width(self, text: str, size_pt: float, bold: bool = False, italic: bool = False) -> float:
        """Sum of cached per-character advances: within 0.05% of whole-string layout (kerning ignored, so the sum
        errs wide), and about 50 times faster."""
        total = 0.0
        for char in text:
            key = (bold, italic, char)
            if key not in self._advances:
                self._advances[key] = self._font(bold, italic).getlength(char)
            total += self._advances[key]
        return total / _UNITS * size_pt * EMU_PER_PT

    def line_height(self, size_pt: float, line_spacing: float) -> float:
        return size_pt * EMU_PER_PT * self._line_height_em * line_spacing

    def wrap(self, text: str, width: float, size_pt: float, bold: bool = False, italic: bool = False) -> list[str]:
        """Greedy word wrap like PowerPoint's; a word longer than the line is broken between characters."""

        def fits(candidate: str) -> bool:
            return self.width(candidate, size_pt, bold, italic) <= width

        lines: list[str] = []
        for hard_line in text.split("\n"):
            current = ""
            for word in hard_line.split(" "):
                candidate = f"{current} {word}" if current else word
                if fits(candidate):
                    current = candidate
                    continue
                if current:
                    lines.append(current)
                while not fits(word) and len(word) > 1:
                    cut = max(1, max((i for i in range(1, len(word) + 1) if fits(word[:i])), default=1))
                    lines.append(word[:cut])
                    word = word[cut:]
                current = word
            lines.append(current)
        return lines
