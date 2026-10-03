"""Measure text against a template placeholder's real box and inherited style (layout -> master -> theme).

Only first-level paragraphs are measured, because the renderer writes only first-level paragraphs. Fonts are the
real files (measure.load_face), so overflow is found by code instead of PowerPoint autofit.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from lxml import etree
from pptx.enum.shapes import PP_PLACEHOLDER
from pptx.opc.constants import RELATIONSHIP_TYPE as RT

from .measure import EMU_PER_PT, load_face

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS = {"a": _A, "p": _P}
_TITLE_TYPES = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE, PP_PLACEHOLDER.VERTICAL_TITLE}
_BODY_TYPES = {PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.SUBTITLE, PP_PLACEHOLDER.OBJECT}
_DEFAULT_INSETS = (91440, 45720, 91440, 45720)  # left, top, right, bottom (OOXML defaults)
WIDTH_SAFETY = 0.95  # kerning and renderer differences; errs toward reporting overflow


@dataclass(frozen=True)
class TextStyle:
    face: str
    bold: bool
    italic: bool
    size_pt: float
    line_spacing: float  # multiple of the font's natural line height
    space_before_pt: float
    space_after_pt: float
    indent_emu: int  # widest of marL and marL + indent, taken off the line width
    insets: tuple[int, int, int, int]


@dataclass(frozen=True)
class Box:
    w: int
    h: int


@lru_cache(maxsize=32)
def _theme_faces(theme_blob: bytes) -> tuple[str, str]:
    root = etree.fromstring(theme_blob)
    major = root.find(".//a:fontScheme/a:majorFont/a:latin", _NS)
    minor = root.find(".//a:fontScheme/a:minorFont/a:latin", _NS)
    return major.get("typeface"), minor.get("typeface")


def _lvl1(sp: Any) -> Any:
    return None if sp is None else sp.find("./p:txBody/a:lstStyle/a:lvl1pPr", _NS)


def _first(chain: list[Any], path: str, attr: str | None = None) -> Any:
    for element in chain:
        if element is None:
            continue
        found = element if path == "." else element.find(path, _NS)
        if found is not None and (attr is None or found.get(attr) is not None):
            return found if attr is None else found.get(attr)
    return None


def _spacing_pt(chain: list[Any], tag: str, size_pt: float) -> float:
    element = _first(chain, f"./a:{tag}")
    if element is None:
        return 0.0
    points = element.find("./a:spcPts", _NS)
    if points is not None:
        return int(points.get("val")) / 100
    percent = element.find("./a:spcPct", _NS)
    return int(percent.get("val")) / 100000 * size_pt * 1.2 if percent is not None else 0.0


def placeholder_style(layout_placeholder: Any) -> TextStyle:
    """Effective first-level text style of a layout placeholder, as slides that use the layout inherit it."""
    kind = layout_placeholder.placeholder_format.type
    layout = layout_placeholder.part.slide_layout
    master = layout.slide_master
    base_type = PP_PLACEHOLDER.TITLE if kind in _TITLE_TYPES else PP_PLACEHOLDER.BODY
    base = next((ph for ph in master.placeholders if ph.placeholder_format.type == base_type), None)
    style_tag = "titleStyle" if kind in _TITLE_TYPES else "bodyStyle" if kind in _BODY_TYPES else "otherStyle"
    master_style = master._element.find(f"./p:txStyles/p:{style_tag}/a:lvl1pPr", _NS)
    chain = [_lvl1(layout_placeholder._element), _lvl1(base._element if base is not None else None), master_style]

    size = int(_first(chain, "./a:defRPr", "sz") or 1800) / 100
    bold = (_first(chain, "./a:defRPr", "b") or "0") in ("1", "true")
    italic = (_first(chain, "./a:defRPr", "i") or "0") in ("1", "true")
    face = _first(chain, "./a:defRPr/a:latin", "typeface")
    major, minor = _theme_faces(master.part.part_related_by(RT.THEME).blob)
    if face is None:
        face = "+mj-lt" if kind in _TITLE_TYPES else "+mn-lt"
    face = {"+mj-lt": major, "+mn-lt": minor}.get(face, face)
    line = _first(chain, "./a:lnSpc/a:spcPct", "val")
    mar_l = int(_first(chain, ".", "marL") or 0)
    indent = int(_first(chain, ".", "indent") or 0)

    body_prs = [layout_placeholder._element.find("./p:txBody/a:bodyPr", _NS),
                base._element.find("./p:txBody/a:bodyPr", _NS) if base is not None else None]
    insets = tuple(int(_first(body_prs, ".", attr) or default)
                   for attr, default in zip(("lIns", "tIns", "rIns", "bIns"), _DEFAULT_INSETS))
    return TextStyle(face=face, bold=bold, italic=italic, size_pt=size,
                     line_spacing=int(line) / 100000 if line else 1.0,
                     space_before_pt=_spacing_pt(chain, "spcBef", size), space_after_pt=_spacing_pt(chain, "spcAft", size),
                     indent_emu=max(mar_l, mar_l + indent), insets=insets)


class Fitter:
    def __init__(self) -> None:
        self._advances: dict[tuple[str, bool, bool, str], float] = {}

    def width(self, text: str, style: TextStyle) -> float:
        face = load_face(style.face, style.bold, style.italic)
        total = 0.0
        for char in text:
            key = (style.face, style.bold, style.italic, char)
            if key not in self._advances:
                self._advances[key] = face.getlength(char)
            total += self._advances[key]
        return total / 1000 * style.size_pt * EMU_PER_PT

    def line_height(self, style: TextStyle) -> float:
        ascent, descent = load_face(style.face, style.bold, style.italic).getmetrics()
        return (ascent + descent) / 1000 * style.size_pt * EMU_PER_PT * style.line_spacing

    def wrap(self, text: str, width: float, style: TextStyle) -> list[str]:
        """Greedy word wrap like PowerPoint's; a word longer than the line is broken between characters."""
        lines: list[str] = []
        for hard_line in text.split("\n"):
            current = ""
            for word in hard_line.split(" "):
                candidate = f"{current} {word}" if current else word
                if self.width(candidate, style) <= width:
                    current = candidate
                    continue
                if current:
                    lines.append(current)
                while self.width(word, style) > width and len(word) > 1:
                    cut = max((i for i in range(1, len(word) + 1) if self.width(word[:i], style) <= width), default=1)
                    lines.append(word[:cut])
                    word = word[cut:]
                current = word
            lines.append(current)
        return lines

    def text_width(self, text: str, style: TextStyle) -> int:
        """Box width that holds `text` on one line, insets included, with one em to spare (PowerPoint lays out
        slightly wider than the font's advances)."""
        spare = style.size_pt * EMU_PER_PT
        return int(self.width(text, style) / WIDTH_SAFETY + spare) + style.insets[0] + style.insets[2]

    def needed(self, paragraphs: list[str], style: TextStyle, box: Box) -> float:
        """Height in EMU that `paragraphs` need in a box `box.w` wide, insets included."""
        width = (box.w - style.insets[0] - style.insets[2] - style.indent_emu) * WIDTH_SAFETY
        line = self.line_height(style)
        total = style.insets[1] + style.insets[3]
        for index, text in enumerate(paragraphs):
            total += len(self.wrap(text, width, style)) * line
            if index:
                total += style.space_before_pt * EMU_PER_PT
            if index < len(paragraphs) - 1:
                total += style.space_after_pt * EMU_PER_PT
        return total
