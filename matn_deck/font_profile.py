"""Office font profile for decks (ADR-0020): the PPTX declares Office families that every ministry Windows
PowerPoint has, while Linux measures and renders them with their metric-compatible OFL files (fonts.json
`metric_aliases`, resolved in measure.py; LibreOffice/fontconfig substitute the same files).

Applied to an in-memory template, so the template files on disk keep their ADR-0019 faces. Arabic (`a:cs`) and
symbol faces are left unchanged.
"""
from __future__ import annotations

from typing import Any

from lxml import etree
from pptx.enum.shapes import PP_PLACEHOLDER
from pptx.opc.constants import RELATIONSHIP_TYPE as RT

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS = {"a": _A, "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}

# Template face (lowercase) -> declared Office face. Titles and body use Calibri (narrowest of the safe Office
# faces: Arial is 8 % wider in body text and 15 % wider in bold, measured on the saved verified units). Serif
# headings use Times New Roman until Caladea (Cambria's metric twin) is pinned; Cambria without Caladea renders
# in Noto Serif under LibreOffice, which breaks width parity.
OFFICE_FACES = {
    "noto sans display": "Calibri",
    "noto sans": "Calibri",
    "carlito": "Calibri",
    "calibri": "Calibri",
    "liberation sans": "Arial",
    "arial": "Arial",
    "noto serif": "Times New Roman",
    "liberation serif": "Times New Roman",
    "times new roman": "Times New Roman",
}
PROFILES = ("template", "office")
_TITLES = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE, PP_PLACEHOLDER.VERTICAL_TITLE}


def _office(face: str) -> str | None:
    return OFFICE_FACES.get(face.lower())


def _rewrite_latin(root: Any) -> list[str]:
    changed = []
    for element in root.iter(f"{{{_A}}}latin"):
        face = element.get("typeface", "")
        if face.startswith("+"):
            continue
        office = _office(face)
        if office is None:
            raise ValueError(f"FONT_PROFILE_UNMAPPED:{face}")
        if office != face:
            element.set("typeface", office)
            changed.append(f"{face}->{office}")
    return changed


def _bold_titles(master: Any) -> int:
    count = 0
    style = master._element.find("./p:txStyles/p:titleStyle/a:lvl1pPr/a:defRPr", _NS)
    if style is not None:
        style.set("b", "1")
        count += 1
    for owner in [master, *master.slide_layouts]:
        for ph in owner.placeholders:
            if ph.placeholder_format.type not in _TITLES:
                continue
            for rpr in ph._element.iter(f"{{{_A}}}defRPr", f"{{{_A}}}rPr"):
                if rpr.get("b") is not None:
                    rpr.set("b", "1")
                    count += 1
    return count


def apply_office_profile(prs: Any, *, bold_titles: bool = True) -> dict:
    """Rewrite every declared latin face of `prs` (theme, masters, layouts) to its Office family; bold titles."""
    record: dict = {"profile": "office", "theme": [], "parts": [], "bold_title_styles": 0}
    for master in prs.slide_masters:
        theme = master.part.part_related_by(RT.THEME)
        root = etree.fromstring(theme.blob)
        for scheme in ("majorFont", "minorFont"):
            latin = root.find(f".//a:fontScheme/a:{scheme}/a:latin", _NS)
            office = _office(latin.get("typeface"))
            if office is None:
                raise ValueError(f"FONT_PROFILE_UNMAPPED:{latin.get('typeface')}")
            record["theme"].append(f"{scheme}:{latin.get('typeface')}->{office}")
            latin.set("typeface", office)
        theme._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        for part in [master, *master.slide_layouts]:
            record["parts"] += _rewrite_latin(part._element)
        if bold_titles:
            record["bold_title_styles"] += _bold_titles(master)
    record["parts"] = sorted(set(record["parts"]))
    return record
