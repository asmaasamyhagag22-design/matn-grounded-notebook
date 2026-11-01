"""Build original Matn OOXML templates without Office themes, assets or software.

The package is authored from the ECMA-376 element vocabulary. It has one fresh
Matn theme and master, the existing renderer's 28 contract layouts, and no media.
Run ``python -m design.matn.generate``. The resulting source templates contain no
slides or source documents; content remains the responsibility of deck-v2.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from lxml import etree

from matn_deck.scoring import EMU_PER_PT, Rect
from matn_deck.templates import LAYOUTS, validate_template
from matn_deck.variants import default_layout

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TARGET = ROOT / "design" / "templates" / "matn"
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
WIDTH, HEIGHT = 960, 540
AREA = Rect(58 * EMU_PER_PT, 168 * EMU_PER_PT, 844 * EMU_PER_PT, 306 * EMU_PER_PT)


def _node(tag: str, parent=None, **attrs):
    prefix, local = tag.split(":")
    element = etree.Element(f"{{{NS[prefix]}}}{local}", nsmap=NS if parent is None else None,
                            attrib={k: str(v) for k, v in attrs.items()})
    if parent is not None:
        parent.append(element)
    return element


def _xml(root) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _group(parent):
    tree = _node("p:spTree", parent)
    nv = _node("p:nvGrpSpPr", tree)
    _node("p:cNvPr", nv, id=1, name="")
    _node("p:cNvGrpSpPr", nv)
    _node("p:nvPr", nv)
    transform = _node("a:xfrm", _node("p:grpSpPr", tree))
    for tag in ("off", "chOff"):
        _node(f"a:{tag}", transform, x=0, y=0)
    for tag in ("ext", "chExt"):
        _node(f"a:{tag}", transform, cx=0, cy=0)
    return tree


def _background(parent, color):
    fill = _node("a:solidFill", _node("p:bgPr", _node("p:bg", parent)))
    _node("a:srgbClr", fill, val=color)


def _style(parent, *, face, size, color, bold=False, italic=False):
    level = _node("a:lvl1pPr", parent, marL=0, indent=0, algn="l")
    _node("a:spcPct", _node("a:lnSpc", level), val=100000)
    _node("a:buNone", level)
    rpr = _node("a:defRPr", level, sz=round(size * 100), b=int(bold), i=int(italic))
    _node("a:srgbClr", _node("a:solidFill", rpr), val=color)
    _node("a:latin", rpr, typeface=face)
    _node("a:cs", rpr, typeface="Noto Sans Arabic")
    return level


def _placeholder(tree, index, name, rect, palette, *, role="item", divider=False):
    x, y, w, h = rect
    shape = _node("p:sp", tree)
    nv = _node("p:nvSpPr", shape)
    _node("p:cNvPr", nv, id=index + 1, name=name)
    _node("a:spLocks", _node("p:cNvSpPr", nv), noGrp=1)
    kind = "title" if name == "title" else "chart" if name == "chart" else "body"
    _node("p:ph", _node("p:nvPr", nv), type=kind, idx=index)
    sppr = _node("p:spPr", shape)
    xfrm = _node("a:xfrm", sppr)
    _node("a:off", xfrm, x=round(x * EMU_PER_PT), y=round(y * EMU_PER_PT))
    _node("a:ext", xfrm, cx=round(w * EMU_PER_PT), cy=round(h * EMU_PER_PT))
    _node("a:avLst", _node("a:prstGeom", sppr, prst="rect"))
    _node("a:noFill", sppr)
    _node("a:noFill", _node("a:ln", sppr))
    text = _node("p:txBody", shape)
    _node("a:bodyPr", text, wrap="square", lIns=12700, rIns=12700, tIns=12700, bIns=12700,
          anchor="t")
    styles = _node("a:lstStyle", text)
    sizes = {"title": 34, "cover": 46, "section": 36, "section_number": 160,
             "source": 12, "subtitle": 22, "list": 18, "kpi_value": 60, "hero": 108}
    size = sizes.get(role, 22)
    heading = role in {"title", "cover", "section", "section_number", "item_title", "kpi_value", "hero"}
    color = (palette["divider_text"] if divider else
             palette["accent"] if role in {"item_title", "kpi_value", "hero"} else
             palette["muted"] if role == "source" else palette["text"])
    _style(styles, face=palette["heading"] if heading else palette["body"], size=size,
           color=color, bold=heading, italic=role == "quote")
    _node("a:endParaRPr", _node("a:p", text), lang="en-US")


def _theme(palette):
    theme = _node("a:theme", name="Matn " + palette["name"])
    elements = _node("a:themeElements", theme)
    scheme = _node("a:clrScheme", elements, name="Matn original palette")
    mapping = {
        "dk1": palette["text"], "lt1": palette["surface"], "dk2": palette["muted"],
        "lt2": palette["surface"], "accent1": palette["accent"], "accent2": palette["focus"],
        "accent3": palette["muted"], "accent4": palette["divider"], "accent5": palette["accent"],
        "accent6": palette["focus"], "hlink": palette["accent"], "folHlink": palette["muted"],
    }
    for slot, color in mapping.items():
        _node("a:srgbClr", _node(f"a:{slot}", scheme), val=color)
    fontscheme = _node("a:fontScheme", elements, name="Matn OFL")
    for group, face in (("majorFont", palette["heading"]), ("minorFont", palette["body"])):
        font = _node(f"a:{group}", fontscheme)
        _node("a:latin", font, typeface=face)
        _node("a:ea", font, typeface="")
        _node("a:cs", font, typeface="Noto Sans Arabic")
    fmt = _node("a:fmtScheme", elements, name="Matn flat editable objects")
    fills = _node("a:fillStyleLst", fmt)
    for _ in range(3):
        _node("a:schemeClr", _node("a:solidFill", fills), val="phClr")
    lines = _node("a:lnStyleLst", fmt)
    for width in (12700, 25400, 38100):
        line = _node("a:ln", lines, w=width, cap="flat", cmpd="sng", algn="ctr")
        _node("a:schemeClr", _node("a:solidFill", line), val="phClr")
        _node("a:prstDash", line, val="solid")
    effects = _node("a:effectStyleLst", fmt)
    for _ in range(3):
        _node("a:effectLst", _node("a:effectStyle", effects))
    back = _node("a:bgFillStyleLst", fmt)
    for _ in range(3):
        _node("a:schemeClr", _node("a:solidFill", back), val="phClr")
    _node("a:objectDefaults", theme)
    _node("a:extraClrSchemeLst", theme)
    return _xml(theme)


def _relationships(rows):
    rels = etree.Element(f"{{{REL}}}Relationships", nsmap={None: REL})
    for rid, kind, target in rows:
        etree.SubElement(rels, f"{{{REL}}}Relationship", Id=rid, Type=NS["r"] + "/" + kind, Target=target)
    return _xml(rels)


def _layout(name, palette):
    layout = _node("p:sldLayout", type="cust", preserve=1, showMasterSp=1)
    csld = _node("p:cSld", layout, name=name)
    divider = name == "matn:section_divider:default"
    _background(csld, palette["divider"] if divider else palette["surface"])
    tree = _group(csld)
    if name == "matn:title:default":
        specs = [("title", "cover", (58, 112, 830, 240)), ("subtitle", "subtitle", (62, 374, 790, 104))]
    elif divider:
        specs = [("section_number", "section_number", (58, 48, 820, 190)),
                 ("title", "section", (64, 280, 820, 106)), ("subtitle", "subtitle", (64, 414, 820, 66))]
    else:
        specs = [("title", "title", (58, 48, 844, 102))]
        specs += [(ph, role, (rect.x / EMU_PER_PT, rect.y / EMU_PER_PT,
                              rect.w / EMU_PER_PT, rect.h / EMU_PER_PT))
                  for ph, role, rect in default_layout(name, AREA)]
        if not name.startswith("matn:sources:"):
            specs.append(("source", "source", (58, 488, 844, 25)))
    for i, (ph, role, rect) in enumerate(specs, start=1):
        _placeholder(tree, i, ph, rect, palette, role=role, divider=divider)
    _node("a:masterClrMapping", _node("p:clrMapOvr", layout))
    return _xml(layout)


def _master(palette):
    master = _node("p:sldMaster")
    csld = _node("p:cSld", master, name="Matn original master")
    _background(csld, palette["surface"])
    _group(csld)
    _node("p:clrMap", master, **{slot: slot for slot in ("accent1", "accent2", "accent3", "accent4", "accent5",
                                                       "accent6", "hlink", "folHlink")},
          bg1="lt1", tx1="dk1", bg2="lt2", tx2="dk2")
    ids = _node("p:sldLayoutIdLst", master)
    for index in range(1, len(LAYOUTS) + 1):
        item = _node("p:sldLayoutId", ids, id=2147483648 + index)
        item.set(f"{{{NS['r']}}}id", f"rId{index}")
    styles = _node("p:txStyles", master)
    for tag in ("titleStyle", "bodyStyle", "otherStyle"):
        _style(_node(f"p:{tag}", styles), face=palette["body"], size=22, color=palette["text"])
    return _xml(master)


def build(template_id: str, palette: dict, target: Path = TARGET) -> Path:
    folder = Path(target) / template_id
    folder.mkdir(parents=True, exist_ok=True)
    parts = {"ppt/theme/theme1.xml": _theme(palette), "ppt/slideMasters/slideMaster1.xml": _master(palette)}
    parts["ppt/slideMasters/_rels/slideMaster1.xml.rels"] = _relationships(
        [(f"rId{i}", "slideLayout", f"../slideLayouts/slideLayout{i}.xml") for i in range(1, len(LAYOUTS) + 1)] +
        [(f"rId{len(LAYOUTS) + 1}", "theme", "../theme/theme1.xml")])
    for i, name in enumerate(LAYOUTS, start=1):
        parts[f"ppt/slideLayouts/slideLayout{i}.xml"] = _layout(name, palette)
        parts[f"ppt/slideLayouts/_rels/slideLayout{i}.xml.rels"] = _relationships(
            [("rId1", "slideMaster", "../slideMasters/slideMaster1.xml")])
    presentation = _node("p:presentation", saveSubsetFonts=1)
    mid = _node("p:sldMasterId", _node("p:sldMasterIdLst", presentation), id=2147483648)
    mid.set(f"{{{NS['r']}}}id", "rId1")
    _node("p:sldSz", presentation, cx=WIDTH * EMU_PER_PT, cy=HEIGHT * EMU_PER_PT, type="screen16x9")
    _node("p:notesSz", presentation, cx=HEIGHT * EMU_PER_PT, cy=WIDTH * EMU_PER_PT)
    parts["ppt/presentation.xml"] = _xml(presentation)
    parts["ppt/_rels/presentation.xml.rels"] = _relationships([("rId1", "slideMaster", "slideMasters/slideMaster1.xml")])
    parts["_rels/.rels"] = _relationships([("rId1", "officeDocument", "ppt/presentation.xml")])
    content = etree.Element(f"{{{CT}}}Types", nsmap={None: CT})
    for ext, ctype in (("rels", "application/vnd.openxmlformats-package.relationships+xml"), ("xml", "application/xml")):
        etree.SubElement(content, f"{{{CT}}}Default", Extension=ext, ContentType=ctype)
    for path in parts:
        if not path.endswith(".xml"):
            continue
        kind = ("presentation.main" if path == "ppt/presentation.xml" else "theme" if "/theme/" in path else
                "slideMaster" if "/slideMasters/" in path else "slideLayout")
        ctype = ("application/vnd.openxmlformats-officedocument.theme+xml" if kind == "theme" else
                 f"application/vnd.openxmlformats-officedocument.presentationml.{kind}+xml")
        etree.SubElement(content, f"{{{CT}}}Override", PartName="/" + path, ContentType=ctype)
    parts["[Content_Types].xml"] = _xml(content)
    path = folder / "template.pptx"
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in sorted(parts.items()):
            entry = ZipInfo(name, date_time=(2026, 10, 30, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, data)
    report = validate_template(path)
    if not report.ok:
        raise ValueError(f"TEMPLATE_INVALID:{template_id}:{report.errors}")
    meta = {"id": template_id, "name_en": palette["name"], "mode": palette["mode"],
            "fonts": {"heading": palette["heading"], "body": palette["body"]},
            "family": "matn-original", "source": "design/matn/generate.py", "palette": palette,
            "mood": palette["mood"], "audience": palette["audience"],
            "content_area_pt": [v / EMU_PER_PT for v in (AREA.x, AREA.y, AREA.w, AREA.h)],
            "card_style": {"fill_alpha": 0.035 if palette["mode"] == "light" else 0.06,
                           "corner_radius_pt": 0, "shadow": {"enabled": False}},
            "layout_bias": ["cards-3", "default"] if template_id != "editorial" else ["grid-2x2"],
            "provenance": {"kind": "matn-original", "generator": "design/matn/generate.py", "version": 2,
                           "template_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "third_party_assets": [], "font_license": "OFL-1.1"}}
    (folder / "theme.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def main():
    palettes = json.loads((HERE / "palettes.json").read_bytes())
    for template_id, palette in palettes.items():
        print(build(template_id, palette))


if __name__ == "__main__":
    main()
