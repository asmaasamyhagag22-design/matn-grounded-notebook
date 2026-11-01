"""Original Matn packages: provenance, OFL formatting and two-renderer evidence fidelity."""
from io import BytesIO
import json
from zipfile import ZipFile

from lxml import etree
from pptx import Presentation
import pytest

from design.matn.generate import build
from matn_deck.deck_qa import delivery_checks, run_qa
from matn_deck.deck_v2 import build_deck
from matn_deck.make_deck import make_deck
from matn_deck.product_templates import (
    PRODUCT_TEMPLATE_IDS, original_template_checks, product_template, product_templates,
)
from matn_deck.storyboard_v2 import Controls
from matn_deck.templates import LAYOUTS, validate_template
from tests.deck_v2.catalog_fixture import make_catalog


@pytest.mark.slow
def test_registry_only_resolves_the_three_shipped_originals():
    assert tuple(t.id for t in product_templates()) == PRODUCT_TEMPLATE_IDS
    with pytest.raises(ValueError, match="PRODUCT_TEMPLATE_UNKNOWN"):
        product_template("../../private")
    for template in product_templates():
        assert validate_template(template.path).ok
        assert original_template_checks(template.path, "template") == []
        assert any("OFL" in r for r in original_template_checks(template.path, "office"))
        assert template.meta["provenance"]["third_party_assets"] == []
        prs = Presentation(str(template.path))
        assert len(prs.slides) == 0
        assert {s.name for s in prs.slide_layouts} == set(LAYOUTS)


@pytest.mark.slow
def test_source_generator_is_reproducible_and_uses_no_office_seed(tmp_path):
    palette = product_templates()[0].meta["palette"]
    one = build("ministry_light", palette, tmp_path / "one")
    two = build("ministry_light", palette, tmp_path / "two")
    assert one.read_bytes() == two.read_bytes() == product_template().read_bytes()
    with ZipFile(one) as package:
        assert not any(n.startswith("ppt/media/") for n in package.namelist())
        theme = etree.fromstring(package.read("ppt/theme/theme1.xml"))
        assert theme.get("name") == "Matn Ministry Light"


def test_local_ready_requires_original_provenance_fonts_and_both_renderers():
    manifest = {"template": str(product_template()), "fonts": {"profile": "template"}}
    qa = delivery_checks(manifest)
    assert qa["status"] == "DELIVERY_BLOCKED"
    assert any("LOCAL_QA_PENDING" in p for p in qa["reasons"])
    qa = delivery_checks(manifest, two_renderer_verified=True)
    assert qa["status"] == "DELIVERY_READY"
    assert qa["platform_validation"]["windows_powerpoint"] == "UNMEASURED"
    assert "local" in qa["scope"]


def _all_package_xml(data: bytes, prefix=""):
    with ZipFile(BytesIO(data)) as package:
        for name in package.namelist():
            if name.endswith(".xml"):
                yield prefix + name, etree.fromstring(package.read(name))
            elif name.endswith(".xlsx"):
                yield from _all_package_xml(package.read(name), prefix + name + "!")


@pytest.mark.slow
def test_generated_deck_notes_charts_and_embedded_workbooks_keep_only_ofl_defaults(tmp_path):
    catalog = make_catalog(tmp_path)
    result = build_deck(catalog, product_template(), tmp_path / "deck", fonts="template",
                        controls=Controls(date="2026-10-30"))
    allowed = {"Carlito", "Noto Sans Arabic"}
    themes = []
    for name, root in _all_package_xml(result.pptx.read_bytes()):
        if etree.QName(root).localname == "theme":
            themes.append(name)
            assert root.get("name", "").startswith("Matn "), name
        for node in root.iter():
            kind = etree.QName(node).localname
            face = node.get("typeface", "") if kind in {"latin", "ea", "cs", "font", "buFont"} else ""
            if kind == "name" and node.getparent() is not None and etree.QName(node.getparent()).localname == "font":
                face = node.get("val", "")
            assert not face or face.startswith("+") or face in allowed, (name, face)
    assert len(themes) >= 3  # slide theme, generated notes theme, embedded chart workbook theme
    prs = Presentation(str(result.pptx))
    assert any(s.notes_slide.notes_text_frame.text for s in prs.slides)
    assert any(s.has_chart for slide in prs.slides for s in slide.shapes)
    assert any(s.shape_type == 13 and s._element.nvPicPr.cNvPr.get("descr") == catalog.figures[0].caption
               for slide in prs.slides for s in slide.shapes)
    qa = run_qa(result.folder)
    assert all(v["pass"] for k, v in qa["gates"].items() if k not in {"overflow_pdf", "pdf_pages"})


@pytest.mark.slow
@pytest.mark.parametrize("template_id", PRODUCT_TEMPLATE_IDS)
def test_every_original_template_passes_two_renderer_qa(tmp_path, template_id):
    import shutil
    if shutil.which("soffice") is None:
        pytest.skip("LibreOffice not installed")
    qa = make_deck(make_catalog(tmp_path), product_template(template_id), tmp_path / "deck", fonts="template",
                   controls=Controls(date="2026-10-30"))
    assert qa["status"] == "QA_PASS", {k: v["failures"] for k, v in qa["gates"].items() if not v["pass"]}
    assert qa["delivery"]["status"] == "DELIVERY_READY"
    assert qa["pdf"]["outside"] == qa["pdf"]["below_minimum"] == 0
    saved = json.loads((tmp_path / "deck" / "deck_qa.json").read_bytes())
    assert saved["delivery"]["platform_validation"]["windows_powerpoint"] == "UNMEASURED"
