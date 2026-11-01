"""Deck QA (ADR-0024): every gate must pass before a deck is labelled QA_PASS.

Two renderers must agree: renderer 1 is the engine's own measurement (fonts, wrap, boxes) recorded at build time;
renderer 2 is LibreOffice's PDF, read back with pdfplumber, where every character must lie inside a slide shape
and keep at least its minimum size. The other gates read the saved .pptx itself and check it against the
storyboard and the Evidence Catalog, independently of the builder. Delivery checks (template provenance, font
profile, the Windows check) are reported separately and never hidden.
"""
from __future__ import annotations

from dataclasses import asdict
from html import escape
import json
from pathlib import Path
import re
from typing import Any

from pptx import Presentation
from pptx.util import Emu

from .catalog import EvidenceCatalog
from .storyboard_v2 import LABELS, Storyboard, axis_title

EMU_PER_PT = 12700
TOLERANCE_PT = 1.5
MIN_PT = {"title": 24.0, "claim": 16.0, "reference": 12.0, "chip": 8.0}
DENSITY_WORDS = {"assertion": 170, "disagree": 170, "chart": 170, "figure": 80, "key_numbers": 220,
                 "agenda": 120, "gaps": 220, "sources": 260, "methods": 220, "title": 60,"closing":170,"warning":120,"section":40}
CONTRAST = {"text": 4.5, "large": 3.0, "graphics": 3.0}  # WCAG 2.x: large = 18 pt, or 14 pt bold
REFERENCE_KINDS = {"sources", "methods"}
MARKER = re.compile(r"\[(\d+)\]")
DIGITS = re.compile(r"\d+(?:[.,]\d+)*")
PART = re.compile(r" \((\d+)/(\d+)\)$")
ORDINAL = re.compile(r"^\d{2}$|^\d$")
# Engine hard constraints mapped to the deck v2 gate they belong to. NO_VISUAL (a v1 design rule: every content
# slide needs a visual) is a layout note: a text-only evidence slide is legitimate in an assertion-evidence deck.
ENGINE_GATES = (("OVERFLOW", "overflow_measured"), ("OUT_OF_BOUNDS", "overflow_measured"),
                ("COLLISION", "overflow_measured"), ("LOW_CONTRAST", "contrast"), ("TEXT_TOO_SMALL", "min_font"),
                ("TITLE_TOO_SMALL", "min_font"), ("EMPTY", "no_empty_slide"), ("TOO_MANY_SIZES", "min_font"),
                ("CHART_TOO_SMALL", "overflow_measured"))
OFFICE_THEMES = {"Facet", "Film Burn", "Integral", "Ion Boardroom", "Modulo", "Office Theme", "Retrospect",
                 "Wisp", "Organic", "Slice", "Ion", "Berlin", "Gallery", "View", "Badge", "Celestial"}


def _paragraphs(shape: Any) -> list[str]:
    if shape.has_text_frame:
        return [p.text.replace("\v", "\n") for p in shape.text_frame.paragraphs if p.text.strip()]
    if getattr(shape, "has_table", False) and shape.has_table:
        return [cell.text.replace("\v", "\n") for row in shape.table.rows for cell in row.cells if cell.text.strip()]
    return []


def _slide_text(slide: Any) -> list[tuple[str, str]]:
    return [(shape.name, text) for shape in slide.shapes for text in _paragraphs(shape)]


def _boxes(slide: Any) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Text-bearing shapes (and graphic frames) in PDF points, top-left origin."""
    boxes = []
    for shape in slide.shapes:
        if shape.width is None:
            continue
        if _paragraphs(shape) or getattr(shape, "has_chart", False):
            x, y = shape.left / EMU_PER_PT, shape.top / EMU_PER_PT
            boxes.append((shape.name, (x, y, x + shape.width / EMU_PER_PT, y + shape.height / EMU_PER_PT)))
    return boxes


def _minimum(kind,shape_name,product=False):
    return 12.0 if product and shape_name=='source' else MIN_PT[_role(kind,shape_name)]


def _role(kind: str, shape_name: str) -> str:
    if shape_name == "title":
        return "title"
    if shape_name == "source":
        return "chip"
    if kind in REFERENCE_KINDS:
        return "reference"
    return "claim"


# ---- storyboard ↔ catalog ---------------------------------------------------------------------------------------

def _allowed_label(text: str, catalog: EvidenceCatalog) -> bool:
    flat = {v for v in LABELS.values() if isinstance(v, str)} | set(LABELS["methods_lines"])
    if text in flat:
        return True
    axes = {axis_title(a.title) for a in catalog.plan.axes}
    for prefix in ("further", "disagree", "figure_source", "gap_axis"):
        head = LABELS[prefix] + ": "
        if text.startswith(head) and text[len(head):] in axes:
            return True
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} · " + re.escape(LABELS["draft"]), text):
        return True
    return False


def _gap_rows(catalog):
    from .product_storyboard import gap_rows
    return gap_rows(catalog)


def storyboard_fidelity(storyboard: Storyboard, catalog: EvidenceCatalog) -> list[str]:
    """Every storyboard string against the catalog category it claims."""
    units = {u.id: u for u in catalog.units}
    contexts = {(u.id, c.quote.strip()) for u in catalog.units for c in u.context if c.kind == "required"}
    synthesis = {s.text.strip() for s in catalog.synthesis}
    axes = {a.id: axis_title(a.title) for a in catalog.plan.axes}
    requirements = {r.description for r in catalog.plan.requirements} | {m for g in catalog.gaps for m in g.missing}
    captions = {f.id: f.caption for f in catalog.figures}
    problems = []
    for index, slide in enumerate(storyboard.slides, start=1):
        texts = [slide.title, *slide.lines, *slide.item_titles]
        texts += [t for b in slide.bullets for t in (b.text, *b.context)]
        for t in texts:
            ok = {
                "unit": lambda: t.ref in units and units[t.ref].text.strip() == t.text,
                "context": lambda: (t.ref, t.text) in contexts,
                "synthesis": lambda: t.text in synthesis,
                "axis": lambda: axes.get(t.ref) == t.text,
                "requirement": lambda: t.text in requirements,
                "caption": lambda: captions.get(t.ref) == t.text,
                "plan": lambda: t.text in (catalog.plan.topic, catalog.plan.audience, storyboard.controls.audience),
                "plan_case": lambda: t.text.casefold()==catalog.plan.topic.casefold(),
                "number_value": lambda: any(n.id==t.ref and n.value_as_written==t.text for n in catalog.numbers),
                "unit_date": lambda: t.ref in units and t.text in units[t.ref].text and bool(re.fullmatch(r'(?:18|19|20)\d{2}',t.text)),
                "gap_reason": lambda: t.ref in _gap_rows(catalog) and _gap_rows(catalog)[t.ref]['reason']==t.text,
                "search_query": lambda: t.ref in _gap_rows(catalog) and t.text in ['Searched: '+q for q in _gap_rows(catalog)[t.ref]['queries']],
                "date": lambda: t.text == storyboard.controls.date,
                "label": lambda: _allowed_label(t.text, catalog),
                "source_meta": lambda: _source_meta_ok(t, catalog),
                "category": lambda: any(t.text in (n.geography, *n.period) for n in catalog.numbers),
            }.get(t.kind, lambda: False)()
            if not ok:
                problems.append(f"slide-spec {index}: {t.kind} not in catalog: {t.text[:60]!r}")
    return problems


def _source_meta_ok(t: Any, catalog: EvidenceCatalog) -> bool:
    try:
        s = catalog.source(t.ref)
    except StopIteration:
        return False
    if t.text == f"{s.publisher} {LABELS['states']}":
        return True
    pieces = set(t.text.split(" · "))
    known = {s.title or LABELS["untitled"], s.publisher, s.type, s.url or "", s.file or ""}
    if s.pages:
        known.add(f"{LABELS['pages']} {', '.join(map(str, s.pages))}")
    if s.accessed:
        known.add(f"{LABELS['accessed']} {s.accessed}")
    return pieces <= known


# ---- the gates ----------------------------------------------------------------------------------------------------

def _expected(record: dict) -> set[str]:
    """Strings a slide may show, as the builder writes them from the storyboard record."""
    allowed = set()
    texts = record["allowed"]
    for t in texts:
        allowed.add(t["text"])
        allowed.add(f"{t['text']} {t['marker']}".strip())
        allowed.add(f"{t['marker']} {t['text']}".strip())
    return allowed


def _bullet_forms(spec: dict) -> set[str]:
    forms = set()
    for b in spec["bullets"]:
        text = f"{b['text']['text']} {b['text']['marker']}".strip()
        for ctx in b["context"]:
            text += f"\n{LABELS['context']}: “{ctx['text']}” {ctx['marker']}".rstrip()
        forms.add(text)
    return forms


def run_qa(folder: Path, *, pdf: Path | None = None) -> dict:
    folder = Path(folder)
    manifest = json.loads((folder / "deck-manifest.json").read_bytes())
    catalog = EvidenceCatalog.from_json((folder / "catalog.json").read_bytes())
    story = json.loads((folder / "storyboard.json").read_bytes())
    from .catalog import _build
    storyboard = _build(Storyboard, story)
    prs = Presentation(str(folder / "deck.pptx"))
    records = manifest["slides"]
    product=bool(manifest.get("product_evidence_design"))
    failures: dict[str, list[str]] = {g: [] for g in (
        "overflow_measured", "overflow_pdf", "min_font", "density", "contrast", "citations", "source_fidelity",
        "numbers", "no_empty_slide", "no_ellipsis", "alt_text", "reading_order", "notes", "roundtrip", "pdf_pages")}
    failing_slides: dict[int, set[str]] = {}

    def fail(gate: str, slide: int | None, message: str) -> None:
        failures[gate].append(f"slide {slide}: {message}" if slide else message)
        if slide:
            failing_slides.setdefault(slide, set()).add(gate)

    # renderer 1: the engine's measurement
    for o in manifest["render"]["overflows"]:
        fail("overflow_measured", o["slide_number"], f"{o['placeholder']} needs {o['needed_emu']} EMU of "
                                                       f"{o['available_emu']}")
    layout_notes = []
    for w in manifest["render"]["warnings"]:
        m = re.match(r"HARD_VIOLATION:slide (\d+):(.*)", w)
        if not m:
            continue
        gate = next((g for prefix, g in ENGINE_GATES if m[2].startswith(prefix)), None)
        if gate is None:  # engine design rules (NO_VISUAL ...) are reported, not gates, for deck v2
            layout_notes.append(f"slide {m[1]}: {m[2]}")
        else:
            fail(gate, int(m[1]), m[2])
    if len(prs.slides) != len(records):
        fail("roundtrip", None, f"{len(prs.slides)} slides in the file, {len(records)} in the manifest")

    sources_slide = next((r for r in records if r["kind"] == "sources"), None)
    citations = len(storyboard.citations)
    units = {u.id: u for u in catalog.units}
    for problem in storyboard_fidelity(storyboard, catalog):
        fail("source_fidelity", None, problem)

    for record, slide in zip(records, prs.slides):
        n, kind = record["slide"], record["kind"]
        spec = story["slides"][record["spec"]]
        texts = _slide_text(slide)
        allowed = _expected(record) | _bullet_forms(spec)
        title = record["title"]
        # source fidelity: every paragraph on the slide is an allowed string
        for name, text in texts:
            if name == "title":
                text = text.replace("\n", " ")  # balanced title lines: a break replaces a space
            base = PART.sub("", text)
            if text in allowed or base in allowed or text == title:
                continue
            if name == "source" and re.fullmatch(re.escape(LABELS["sources"]) + r"( \[\d+\])+", text):
                continue
            if name.startswith(("marker_", "item_")) and ORDINAL.match(text):
                continue
            if name == "key_numbers_table" and record.get("table") and any(text in row for row in record["table"]):
                continue
            if name.startswith("item_") and name.endswith("_title") and text in {t["text"] for t in spec["item_titles"]}:
                continue
            fail("source_fidelity", n, f"{name}: unexpected text {text[:70]!r}")
        # ellipsis
        for name, text in texts:
            for mark in ("…", "..."):
                if mark in text and not any(mark in u.span.quote or mark in u.text for u in catalog.units):
                    fail("no_ellipsis", n, f"{name}: {mark!r}")
        # citations
        if kind in ("assertion", "disagree", "chart", "closing"):
            bullets = [t for name, t in texts if name.startswith("item_") and not name.endswith("_title")
                       or (kind == "chart" and name == "body")]
            for text in bullets:
                first = text.split("\n")[0]
                if not MARKER.search(first.rsplit(" ", 1)[-1]):
                    fail("citations", n, f"bullet without marker: {first[:50]!r}")
        for name, text in texts:
            for m in MARKER.finditer(text):
                if not 1 <= int(m[1]) <= citations:
                    fail("citations", n, f"marker {m[0]} does not resolve")
        # numbers: claim text digits come from the catalog's verified text; table/chart values are facts
        for name, text in texts:
            if kind in ("sources", "methods", "title") or name == "source":
                continue
            clean = MARKER.sub("", PART.sub("", text))
            if name.startswith("marker_") or ORDINAL.match(clean.strip()):
                continue
            for token in DIGITS.findall(clean):
                if not _number_ok(token, clean, record, spec, catalog):
                    fail("numbers", n, f"{name}: number {token!r} has no verified origin")
        # words per slide
        words = sum(len(t.split()) for _, t in texts)
        if words > DENSITY_WORDS.get(kind, 200):
            fail("density", n, f"{words} words > {DENSITY_WORDS.get(kind, 200)}")
        # empty slide
        content = [name for name, _ in texts if name != "title"]
        has_visual = any(s.shape_type == 13 or getattr(s, "has_chart", False) or getattr(s, "has_table", False)
                         for s in slide.shapes)
        if not any(name == "title" for name, _ in texts) or not (content or has_visual):
            fail("no_empty_slide", n, "title or content missing")
        # alt text
        for shape in slide.shapes:
            is_graphic = shape.shape_type == 13 or getattr(shape, "has_chart", False) or getattr(shape, "has_table", False)
            if is_graphic:
                element = shape._element
                cnv = element.find(".//{http://schemas.openxmlformats.org/presentationml/2006/main}cNvPr")
                if cnv is None or not (cnv.get("descr") or "").strip():
                    fail("alt_text", n, f"{shape.name}: no alt text")
        # reading order: title first among text shapes; items in order
        names = [shape.name for shape in slide.shapes if _paragraphs(shape)]
        if names and names[0] != "title":
            fail("reading_order", n, f"first text shape is {names[0]}")
        items = [int(m[1]) for name in names for m in [re.fullmatch(r"item_(\d+)", name)] if m]
        if items != sorted(items):
            fail("reading_order", n, f"items out of order {items}")
        # notes
        if kind in ("assertion", "disagree", "chart", "figure", "key_numbers", "closing"):
            notes = slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip()
            if not notes:
                fail("notes", n, "no speaker notes")
        # contrast (engine-measured ratios)
        for c in record.get("contrast", []):
            from .scoring import GRAPHIC_KINDS
            size = c["size_pt"] or 0
            large = size >= 18 or (c["bold"] and size >= 14)
            need = CONTRAST["graphics" if c.get("kind") in GRAPHIC_KINDS else "large" if large else "text"]
            if c["ratio"] < need:
                fail("contrast", n, f"{c['name']}: {c['ratio']} < {need}")
        # run sizes in the file
        for shape in slide.shapes:
            frames = [shape.text_frame] if shape.has_text_frame else \
                [cell.text_frame for row in shape.table.rows for cell in row.cells] if getattr(shape, "has_table", False) else []
            for frame in frames:
                for p in frame.paragraphs:
                    for r in p.runs:
                        if r.font.size is not None and r.text.strip():
                            role = _role(kind, shape.name)
                            if r.font.size.pt + 1e-6 < _minimum(kind,shape.name,product):
                                fail("min_font", n, f"{shape.name}: {r.font.size.pt} pt < {_minimum(kind,shape.name,product)} ({role})")

    if sources_slide is None and citations:
        fail("citations", None, "no Sources slide")

    # roundtrip
    try:
        again = Presentation(str(folder / "deck.pptx"))
        if [_slide_text(s) for s in again.slides] != [_slide_text(s) for s in prs.slides]:
            fail("roundtrip", None, "reloaded texts differ")
    except Exception as exc:  # any reopen failure is the gate's finding
        fail("roundtrip", None, f"reopen failed: {type(exc).__name__}")

    # renderer 2: the PDF
    pdf_summary = None
    if pdf is not None and Path(pdf).is_file():
        pdf_summary = _pdf_checks(Path(pdf), prs, records, fail,product=product)
    else:
        failures["overflow_pdf"].append("no PDF exported")
        failures["pdf_pages"].append("no PDF exported")

    gates = {g: {"pass": not msgs, "failures": msgs} for g, msgs in failures.items()}
    status = "QA_PASS" if all(g["pass"] for g in gates.values()) else "QA_FAIL"
    delivery = delivery_checks(manifest, two_renderer_verified=status == "QA_PASS" and pdf_summary is not None)
    return {"status": status, "delivery": delivery, "gates": gates, "slides": len(records),
            "failing_slides": {str(k): sorted(v) for k, v in sorted(failing_slides.items())},
            "pdf": pdf_summary, "layout_notes": layout_notes, "storyboard_sha256": manifest["storyboard_sha256"],
            "catalog_sha256": manifest["catalog_sha256"], "fonts": manifest["fonts"].get("profile"),
            "safety": manifest["safety"], "template": manifest["template"]}


def _number_ok(token: str, text: str, record: dict, spec: dict, catalog: EvidenceCatalog) -> bool:
    """A digit token is allowed when the verified catalog text it is copied from contains it."""
    sources = [t["text"] for t in record["allowed"] if t["kind"] in ("unit", "synthesis", "context", "caption",
                                                                     "axis", "requirement", "plan")]
    sources += [b["text"]["text"] for b in spec["bullets"]]
    if any(token in s for s in sources):
        return True
    facts = {f.value_as_written for f in catalog.numbers} | {p for f in catalog.numbers for p in f.period}
    if record.get("table") and any(token in fact for fact in facts):
        return True
    return False


def _pdf_checks(pdf: Path, prs: Any, records: list[dict], fail, *, product=False) -> dict:
    import pdfplumber
    checked = outside = small = 0
    with pdfplumber.open(str(pdf)) as document:
        if len(document.pages) != len(prs.slides):
            fail("pdf_pages", None, f"{len(document.pages)} PDF pages for {len(prs.slides)} slides")
        for page, slide, record in zip(document.pages, prs.slides, records):
            n, kind = record["slide"], record["kind"]
            scale = page.width / (prs.slide_width / EMU_PER_PT)
            boxes = [(name, tuple(v * scale for v in box)) for name, box in _boxes(slide)]
            reported = set()
            for char in page.chars:
                if not char["text"].strip():
                    continue
                checked += 1
                x0, top, x1, bottom = char["x0"], char["top"], char["x1"], char["bottom"]
                inside = [name for name, (a, b, c, d) in boxes
                          if x0 >= a - TOLERANCE_PT and x1 <= c + TOLERANCE_PT and top >= b - TOLERANCE_PT
                          and bottom <= d + TOLERANCE_PT]
                if not inside:
                    outside += 1
                    key = ("out", round(top))
                    if key not in reported:
                        reported.add(key)
                        fail("overflow_pdf", n, f"text outside every shape near y={top:.0f}pt: "
                                                f"{char['text']!r} ({char['fontname'].split('+')[-1]})")
                    continue
                if any(name.startswith("chart") for name in inside):
                    continue  # chart text is LibreOffice's own drawing: covered by the Windows check
                role = _role(kind, inside[0])
                size = char["size"] / scale
                if size + 0.25 < _minimum(kind,inside[0],product):
                    small += 1
                    key = ("small", inside[0])
                    if key not in reported:
                        reported.add(key)
                        fail("min_font", n, f"{inside[0]}: rendered at {size:.1f} pt < {_minimum(kind,inside[0],product)} ({role})")
    return {"characters": checked, "outside": outside, "below_minimum": small}


def delivery_checks(manifest: dict, *, two_renderer_verified: bool = False) -> dict:
    """Not render gates: what still stands between a QA_PASS deck and a ministry delivery."""
    from zipfile import ZipFile
    from .product_templates import is_product_template, original_template_checks
    reasons = []
    template = Path(manifest["template"])
    if is_product_template(template):
        reasons = original_template_checks(template, manifest["fonts"].get("profile", ""))
        if not two_renderer_verified:
            reasons.append("LOCAL_QA_PENDING: both measurement and LibreOffice PDF gates must pass")
        return {"status": "DELIVERY_BLOCKED" if reasons else "DELIVERY_READY", "reasons": reasons,
                "scope": "local app / pinned OFL fonts",
                "platform_validation": {"linux": "TWO_RENDERER_PASS" if two_renderer_verified else "PENDING",
                                        "windows_powerpoint": "UNMEASURED"}}
    with ZipFile(template) as z:
        theme = z.read("ppt/theme/theme1.xml").decode("utf-8", "replace")
        media = [n for n in z.namelist() if n.startswith("ppt/media/")]
    name = re.search(r'<a:theme [^>]*name="([^"]*)"', theme)
    if name and name.group(1) in OFFICE_THEMES:
        reasons.append(f"TEMPLATE_PROVENANCE: built on the Office theme {name.group(1)!r}"
                       + (f" with {len(media)} media part(s)" if media else ""))
    if manifest["fonts"].get("profile") != "office":
        reasons.append("FONTS: the template profile declares Noto faces, which ministry PowerPoint does not have")
    reasons.append("WINDOWS_CHECK_PENDING: open the PPTX in PowerPoint and compare it with the PDF (docs/deck-v2.md)")
    return {"status": "DELIVERY_BLOCKED" if reasons else "DELIVERY_READY", "reasons": reasons}


def write_report(folder: Path, qa: dict, thumbs: list[Path]) -> Path:
    rows = "".join(f"<tr class='{'ok' if g['pass'] else 'bad'}'><td>{escape(name)}</td><td>{'PASS' if g['pass'] else 'FAIL'}"
                   f"</td><td>{'<br>'.join(escape(m) for m in g['failures'][:12])}</td></tr>"
                   for name, g in qa["gates"].items())
    thumbs_html = "".join(f"<figure><img src='{escape(p.relative_to(folder).as_posix())}' alt='slide {i}'>"
                          f"<figcaption>{i}{' · ' + escape(', '.join(qa['failing_slides'].get(str(i), []))) if qa['failing_slides'].get(str(i)) else ''}"
                          f"</figcaption></figure>" for i, p in enumerate(thumbs, start=1))
    html = (
        "<!doctype html><html lang='en'><meta charset='utf-8'><title>Deck QA</title><style>"
        "body{font-family:sans-serif;max-width:1200px;margin:24px auto;padding:0 16px;color:#183342}"
        "table{border-collapse:collapse;width:100%}td{border-bottom:1px solid #dde3e7;padding:6px;vertical-align:top;"
        "font-size:14px}.ok td:nth-child(2){color:#16756a}.bad td:nth-child(2){color:#b0361a;font-weight:bold}"
        "figure{display:inline-block;margin:6px;width:280px}img{width:280px;border:1px solid #9aa7b0}"
        "figcaption{font-size:12px}</style>"
        f"<h1>Deck QA: {escape(qa['status'])}</h1><p>Delivery: {escape(qa['delivery']['status'])} — "
        + "; ".join(escape(r) for r in qa["delivery"]["reasons"]) +
        f"</p><p>Fonts: {escape(str(qa['fonts']))} · width safety {qa['safety']} · template "
        f"{escape(Path(qa['template']).parent.name)} · {qa['slides']} slides</p>"
        f"<table><tr><th>Gate</th><th>Result</th><th>Failures</th></tr>{rows}</table>{thumbs_html}</html>")
    path = Path(folder) / "deck_qa.html"
    path.write_text(html, encoding="utf-8")
    return path
