"""Resolve DrawingML colors (scheme slots, mods) to RGB from a template's theme, for contrast checks by code.

Covers what the gallery templates use: srgbClr, sysClr (lastClr), schemeClr through the master color map, and the
lumMod, lumOff, shade, tint and alpha mods. Backgrounds resolve to every color a viewer may see behind content
(all gradient stops), so a contrast check takes the worst one.
"""
from __future__ import annotations

import colorsys
from typing import Any

from lxml import etree
from pptx.opc.constants import RELATIONSHIP_TYPE as RT

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS = {"a": _A, "p": _P}
RGB = tuple[float, float, float]
_SLOTS = ("dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink",
          "folHlink")


def luminance(rgb: RGB) -> float:
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: RGB, b: RGB) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def blend(top: RGB, bottom: RGB, alpha: float) -> RGB:
    return tuple(alpha * t + (1 - alpha) * b for t, b in zip(top, bottom))  # type: ignore[return-value]


def hex_rgb(value: str) -> RGB:
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_srgb(c: float) -> float:
    c = min(1.0, max(0.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


class ColorResolver:
    def __init__(self, master: Any) -> None:
        theme = etree.fromstring(master.part.part_related_by(RT.THEME).blob)
        scheme = theme.find(".//a:clrScheme", _NS)
        self.slots: dict[str, RGB] = {}
        for slot in _SLOTS:
            element = scheme.find(f"a:{slot}", _NS)
            child = element[0]
            value = child.get("lastClr") if child.tag == f"{{{_A}}}sysClr" else child.get("val")
            self.slots[slot] = hex_rgb(value)
        clr_map = master._element.find("p:clrMap", _NS)
        self.map = dict(clr_map.attrib) if clr_map is not None else {}
        self.master = master

    def scheme(self, name: str) -> RGB:
        name = self.map.get(name, name)
        return self.slots[name]

    def resolve(self, element: Any) -> tuple[RGB, float]:
        """(rgb, alpha) of a color element (srgbClr, sysClr, schemeClr, or a solidFill holding one)."""
        if isinstance(element, str):
            element = etree.fromstring(element)
        if element.tag == f"{{{_A}}}solidFill":
            element = element[0]
        tag = etree.QName(element).localname
        if tag == "srgbClr":
            rgb = hex_rgb(element.get("val"))
        elif tag == "sysClr":
            rgb = hex_rgb(element.get("lastClr"))
        elif tag == "schemeClr":
            rgb = self.scheme(element.get("val"))
        else:
            raise ValueError(f"UNSUPPORTED_COLOR:{tag}")
        alpha = 1.0
        hue, light, sat = colorsys.rgb_to_hls(*rgb)
        lum_mod, lum_off = 1.0, 0.0
        for mod in element:
            name, val = etree.QName(mod).localname, int(mod.get("val", "100000")) / 100000
            if name == "lumMod":
                lum_mod = val
            elif name == "lumOff":
                lum_off = val
            elif name == "alpha":
                alpha = val
        if (lum_mod, lum_off) != (1.0, 0.0):
            rgb = colorsys.hls_to_rgb(hue, min(1.0, max(0.0, light * lum_mod + lum_off)), sat)
        for mod in element:
            name, val = etree.QName(mod).localname, int(mod.get("val", "100000")) / 100000
            if name == "shade":
                rgb = tuple(_to_srgb(_to_linear(c) * val) for c in rgb)
            elif name == "tint":
                rgb = tuple(_to_srgb(1 - (1 - _to_linear(c)) * val) for c in rgb)
        return rgb, alpha  # type: ignore[return-value]

    def background(self, layout: Any | None = None) -> list[RGB]:
        """Every color the slide background shows: the layout's own background if it has one, else the master's."""
        for owner in (layout, self.master):
            if owner is None:
                continue
            bg = owner._element.find("p:cSld/p:bg", _NS)
            if bg is None:
                continue
            fill = bg.find("p:bgPr/a:solidFill", _NS)
            if fill is not None:
                return [self.resolve(fill)[0]]
            stops = bg.findall("p:bgPr/a:gradFill/a:gsLst/a:gs", _NS)
            if stops:
                return [self.resolve(stop[0])[0] for stop in stops]
            ref = bg.find("p:bgRef", _NS)
            if ref is not None and len(ref):
                return [self.resolve(ref[0])[0]]
        return [self.scheme("bg1")]
