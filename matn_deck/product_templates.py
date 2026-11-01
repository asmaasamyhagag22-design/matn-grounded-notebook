"""The three original Matn templates, independent of the legacy Office gallery."""
from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree
from pptx.opc.constants import RELATIONSHIP_TYPE as RT

from .templates import GalleryTemplate, validate_template

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_TEMPLATES_DIR = ROOT / "design" / "templates" / "matn"
PRODUCT_TEMPLATE_IDS = ("ministry_light", "midnight", "editorial")
DEFAULT_PRODUCT_TEMPLATE = "ministry_light"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def product_template(template_id: str = DEFAULT_PRODUCT_TEMPLATE) -> Path:
    """A closed registry: user text is never interpreted as a template path."""
    if template_id not in PRODUCT_TEMPLATE_IDS:
        raise ValueError(f"PRODUCT_TEMPLATE_UNKNOWN:{template_id}")
    return PRODUCT_TEMPLATES_DIR / template_id / "template.pptx"


def product_templates() -> tuple[GalleryTemplate, ...]:
    return tuple(GalleryTemplate(template_id, product_template(template_id),
                                 product_template(template_id).with_name("thumbnail.png"),
                                 json.loads(product_template(template_id).with_name("theme.json").read_bytes()))
                 for template_id in PRODUCT_TEMPLATE_IDS)


def is_product_template(path: Path) -> bool:
    return Path(path).resolve() in {product_template(t).resolve() for t in PRODUCT_TEMPLATE_IDS}


def original_template_checks(path: Path, fonts: str) -> list[str]:
    """Validate the committed original package and its pinned OFL declarations."""
    path = Path(path)
    reasons = []
    if not is_product_template(path):
        return ["TEMPLATE_PROVENANCE: not a registered Matn original"]
    meta = json.loads(path.with_name("theme.json").read_bytes())
    provenance = meta.get("provenance", {})
    if provenance.get("kind") != "matn-original" or provenance.get("generator") != "design/matn/generate.py":
        reasons.append("TEMPLATE_PROVENANCE: missing original Matn generator record")
    if provenance.get("template_sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
        reasons.append("TEMPLATE_PROVENANCE: template bytes differ from the recorded original")
    if fonts != "template":
        reasons.append("FONTS: original Matn templates require their pinned OFL font profile")
    report = validate_template(path)
    reasons.extend(f"TEMPLATE_INVALID:{p}" for p in report.errors)
    manifest = json.loads((ROOT / "design" / "fonts" / "fonts.json").read_bytes())
    allowed = {font["family"] for font in manifest["fonts"] if font["license"] == "OFL-1.1"}
    with ZipFile(path) as archive:
        if any(n.startswith("ppt/media/") for n in archive.namelist()):
            reasons.append("TEMPLATE_PROVENANCE: original template unexpectedly contains media")
        for name in archive.namelist():
            if not name.endswith(".xml"):
                continue
            root = etree.fromstring(archive.read(name))
            if etree.QName(root).localname == "theme" and not root.get("name", "").startswith("Matn "):
                reasons.append(f"TEMPLATE_PROVENANCE: non-Matn theme in {name}")
            for node in root.iter():
                if etree.QName(node).localname not in {"latin", "ea", "cs", "font", "buFont"}:
                    continue
                face = node.get("typeface", "")
                if face and not face.startswith("+") and face not in allowed:
                    reasons.append(f"FONTS: unpinned face {face!r} in {name}")
    return sorted(set(reasons))


def finalize_product_fonts(prs, template: Path) -> None:
    """Remove auto-generated Office themes in notes and chart workbooks.

    python-pptx's notes master and XlsxWriter's embedded chart workbook both add
    default Office theme data. These are formatting defaults, not source data.
    The original Matn theme and OFL family replace them before saving.
    """
    if not is_product_template(template):
        return
    meta = json.loads(Path(template).with_name("theme.json").read_bytes())
    theme = prs.slide_masters[0].part.part_related_by(RT.THEME).blob
    body = meta["fonts"]["body"]
    # Explicit rules keep native tables readable in dark mode without depending
    # on the viewer's built-in Office table style definitions.
    for slide in prs.slides:
        for shape in slide.shapes:
            if not getattr(shape, "has_table", False):
                continue
            for row in shape.table.rows:
                for cell in row.cells:
                    cell.fill.background()
                    props = cell._tc.get_or_add_tcPr()
                    for edge in ("lnL", "lnR", "lnT", "lnB"):
                        old = props.find(f"{{{_A}}}{edge}")
                        if old is not None:
                            props.remove(old)
                        line = etree.SubElement(props, f"{{{_A}}}{edge}", w="6350", cap="flat", cmpd="sng")
                        color = etree.SubElement(etree.SubElement(line, f"{{{_A}}}solidFill"),
                                                 f"{{{_A}}}srgbClr", val=meta["palette"]["muted"])
                        etree.SubElement(color, f"{{{_A}}}alpha", val="40000")
                        etree.SubElement(line, f"{{{_A}}}prstDash", val="solid")
                    for paragraph in cell.text_frame.paragraphs:
                        for run in paragraph.runs:
                            run.font.name = body
    for part in list(prs.part.package.iter_parts()):
        if part.content_type == "application/vnd.openxmlformats-officedocument.theme+xml":
            if hasattr(part, "_element"):
                part._element = etree.fromstring(theme)
            else:
                part._blob = theme
        if not str(part.partname).endswith(".xlsx"):
            continue
        output = BytesIO()
        with ZipFile(BytesIO(part.blob)) as before, ZipFile(output, "w", compression=ZIP_DEFLATED) as after:
            for item in before.infolist():
                data = before.read(item.filename)
                if "/theme/" in item.filename and item.filename.endswith(".xml"):
                    data = theme
                elif item.filename == "xl/styles.xml":
                    root = etree.fromstring(data)
                    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                    for face in root.findall(".//s:fonts/s:font/s:name", ns):
                        face.set("val", body)
                    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                after.writestr(item, data)
        part._blob = output.getvalue()
