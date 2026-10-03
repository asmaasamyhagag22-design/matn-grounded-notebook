"""Gallery QA: render specimen v3 in every template, export PNGs through PowerPoint, measure contrast and whitespace,
compute the beauty score, and build the sheets.

For each template the specimen is rendered strictly (any overflow fails), then a "blank" copy is made with every
text run emptied and chart text made fully transparent. Both are exported through PowerPoint; pixels that
differ are the text. In each text placeholder and chart, the text color is the median of the most-changed pixels and
the background is the blank render under those same pixels, so images and gradients are measured as shown.
Contrast is the 5th percentile over the glyph pixels. Minimums (WCAG 2.x): 4.5 for body text, small text and chart
labels; 3.0 for large text (at least 18 pt, or 14 pt bold).

Whitespace (cross-check of the geometry fill score, after AeSlides): on each content slide's PNG, a pixel is blank when
the standard deviation of its local window is below WHITE_STD; the measure is the blank share of the content area.

Beauty score (the gallery gate, design/scoring.json "beauty_gate"): the mean chosen-candidate score over the specimen's
content slides, plus the count of hard violations (geometry violations kept by the renderer and pixel contrast
failures). A template passes when its score reaches the threshold and it has no hard violation.

Usage: .venv\\Scripts\\python.exe design/templates/src/qa.py
  writes out/gallery/<id>/scores.json, out/gallery/contact_sheet_v3.png, out/gallery/before_after.png,
  out/gallery/scores.md and design/templates/qa.json
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn

SRC = Path(__file__).resolve().parent
ROOT = SRC.parents[2]
OUT = ROOT / "out" / "gallery"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from contact_sheet import build_sheet  # noqa: E402
from matn_deck.fit import placeholder_style  # noqa: E402
from matn_deck.scoring import load_scoring  # noqa: E402
from matn_deck.specimen import main as render_specimen  # noqa: E402
from matn_deck.template_renderer import CONTENT_TYPES, DeckOverflowError  # noqa: E402

EXPORT_W, EXPORT_H = 2560, 1440
BODY_MIN, LARGE_MIN = 4.5, 3.0
WHITE_WINDOW = 15  # px at 2560 wide (about 5.6 pt)
WHITE_STD = 2.0  # grey levels: below this the window is flat
BEFORE_AFTER = ("integral-light", "film-burn-dark", "modulo")
CONTENT = {t.value for t in CONTENT_TYPES}


def blank_copy(deck: Path, out: Path) -> None:
    prs = Presentation(str(deck))
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    for run in paragraph.runs:
                        run.text = ""
            if getattr(shape, "has_chart", False) and shape.has_chart:
                # Fully transparent chart text keeps every label's space, so bars and axes do not move.
                fill = shape.chart.font.fill
                fill.solid()
                fill.fore_color.rgb = RGBColor(0, 0, 0)
                for color in shape.chart._chartSpace.iter(qn("a:srgbClr"), qn("a:schemeClr")):
                    if color.getparent().getparent().tag == qn("a:defRPr") or \
                            color.getparent().getparent().tag == qn("a:rPr"):
                        for alpha in color.findall(qn("a:alpha")):
                            color.remove(alpha)
                        color.append(color.makeelement(qn("a:alpha"), {"val": "0"}))
    prs.save(str(out))


def _luminance(rgb: np.ndarray) -> np.ndarray:
    c = rgb.astype(float) / 255
    linear = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return linear @ np.array([0.2126, 0.7152, 0.0722])


def region_contrast(shown: np.ndarray, blank: np.ndarray) -> float | None:
    diff = np.abs(shown.astype(int) - blank.astype(int)).max(axis=2)
    changed = diff > 48
    if changed.sum() < 30:
        return None
    core = changed & (diff >= np.percentile(diff[changed], 80))
    text = np.median(shown[core], axis=0)
    l_text = _luminance(text[None, :])[0]
    l_back = _luminance(blank[changed])
    ratios = (np.maximum(l_text, l_back) + 0.05) / (np.minimum(l_text, l_back) + 0.05)
    return float(np.percentile(ratios, 5))


def whitespace(png: Path, area_pt: list[float]) -> float:
    """Blank share of the content area: pixels whose local window is flat (std below WHITE_STD)."""
    grey = np.asarray(Image.open(png).convert("L"), dtype=float)
    scale = grey.shape[1] / 960
    x, y, w, h = (round(v * scale) for v in area_pt)
    region = grey[y:y + h, x:x + w]
    k = WHITE_WINDOW

    def box_mean(a: np.ndarray) -> np.ndarray:
        c = np.pad(a, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)

    var = box_mean(region ** 2) - box_mean(region) ** 2
    return float((np.sqrt(np.maximum(var, 0)) < WHITE_STD).mean())


def measure(deck: Path, shown_dir: Path, blank_dir: Path) -> list[dict]:
    prs = Presentation(str(deck))
    sx, sy = EXPORT_W / prs.slide_width, EXPORT_H / prs.slide_height
    rows = []
    for number, slide in enumerate(prs.slides, start=1):
        shown = np.asarray(Image.open(shown_dir / f"slide_{number:02d}.png").convert("RGB"))
        blank = np.asarray(Image.open(blank_dir / f"slide_{number:02d}.png").convert("RGB"))
        layout_ph = {ph.name: ph for ph in slide.slide_layout.placeholders}
        for shape in slide.shapes:
            if shape.has_chart if hasattr(shape, "has_chart") else False:
                kind, minimum = "chart", BODY_MIN
            elif shape.has_text_frame and shape.text_frame.text.strip() and shape.name in layout_ph:
                style = placeholder_style(layout_ph[shape.name])
                runs = [r for p in shape.text_frame.paragraphs for r in p.runs if r.text.strip()]
                size = min((r.font.size.pt for r in runs if r.font.size), default=style.size_pt)
                large = size >= 18 or (style.bold and size >= 14)
                kind, minimum = ("large" if large else "body"), (LARGE_MIN if large else BODY_MIN)
            else:
                continue
            x0, y0 = max(0, int(shape.left * sx)), max(0, int(shape.top * sy))
            x1, y1 = min(EXPORT_W, int((shape.left + shape.width) * sx)), min(EXPORT_H, int((shape.top + shape.height) * sy))
            ratio = region_contrast(shown[y0:y1, x0:x1], blank[y0:y1, x0:x1])
            if ratio is not None:
                rows.append({"slide": number, "placeholder": shape.name, "kind": kind, "contrast": round(ratio, 2),
                             "min": minimum, "ok": ratio >= minimum})
    return rows


def main() -> int:
    gallery = json.loads((SRC / "gallery.json").read_text(encoding="utf-8"))
    gate = load_scoring()["beauty_gate"]
    results, decks, dirs = {}, [], []
    entries = [entry for entry in gallery["templates"] if not entry.get("excluded")]
    for entry in entries:
        tid = entry["id"]
        folder = OUT / tid
        folder.mkdir(parents=True, exist_ok=True)
        template = SRC.parent / tid / "template.pptx"
        try:
            report = render_specimen(template, folder / "specimen.pptx")
        except DeckOverflowError as exc:
            results[tid] = {"overflow": [f"slide {o.slide_number} {o.placeholder}" for o in exc.report.overflows]}
            continue
        (folder / "scores.json").write_text(json.dumps(list(report.scores), ensure_ascii=False, indent=1) + "\n",
                                            encoding="utf-8")
        content = [e for e in report.scores if e["slide_type"] in CONTENT]
        results[tid] = {
            "overflow": [], "layouts": list(report.layouts),
            "hard_geometry": [w for w in report.warnings if w.startswith("HARD_VIOLATION")],
            "beauty": round(sum(e["chosen"]["total"] for e in content) / len(content), 4),
            "mean_fill": round(sum(e["chosen"]["soft"]["fill_ratio"] for e in content) / len(content), 4),
            "mean_balance": round(sum(e["chosen"]["soft"]["balance"] for e in content) / len(content), 4),
            "content_slides": [e["slide"] for e in content],
        }
        blank_copy(folder / "specimen.pptx", folder / "blank.pptx")
        decks += [folder / "specimen.pptx", folder / "blank.pptx"]
        dirs += [folder / "png", folder / "blank_png"]
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SRC / "export_png.ps1"),
                    "-Pptx", ",".join(map(str, decks)), "-OutDir", ",".join(map(str, dirs)),
                    "-Width", str(EXPORT_W), "-Height", str(EXPORT_H)], check=True, cwd=ROOT)

    groups = []
    for entry in entries:
        tid = entry["id"]
        result = results[tid]
        if result["overflow"]:
            continue
        rows = measure(OUT / tid / "specimen.pptx", OUT / tid / "png", OUT / tid / "blank_png")
        failures = [r for r in rows if not r["ok"]]
        area = json.loads((SRC.parent / tid / "theme.json").read_text(encoding="utf-8"))["content_area_pt"]
        blank = [whitespace(OUT / tid / "png" / f"slide_{n:02d}.png", area) for n in result["content_slides"]]
        hard = len(result["hard_geometry"]) + len(failures)
        result.update({
            "min_contrast": {kind: min((r["contrast"] for r in rows if r["kind"] == kind), default=None)
                             for kind in ("body", "large", "chart")},
            "contrast_failures": failures,
            "png_whitespace": round(sum(blank) / len(blank), 4),
            "hard_violations": hard,
            "gate": None if gate["threshold"] is None else
            bool(result["beauty"] >= gate["threshold"] and hard <= gate["max_hard_violations"]),
        })
        pngs = sorted((OUT / tid / "png").glob("slide_*.png"))
        groups.append((f"{entry['name_en']}  ·  {tid}  ·  beauty {result['beauty']:.3f}", pngs))
    build_sheet(groups, OUT / "contact_sheet_v3.png", per_row=1, thumb_w=240, label_size=20)
    pairs = []
    for tid in BEFORE_AFTER:
        if (OUT / tid / "png_v2").is_dir() and tid in results and not results[tid]["overflow"]:
            pairs += [(f"v2 (Step 2b)  ·  {tid}", sorted((OUT / tid / "png_v2").glob("slide_*.png"))),
                      (f"v3 (Step 2c)  ·  {tid}", sorted((OUT / tid / "png").glob("slide_*.png")))]
    if pairs:
        build_sheet(pairs, OUT / "before_after.png", per_row=1, thumb_w=240, label_size=20)
    (SRC.parent / "qa.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_scores_md(results, gate)
    for tid, result in results.items():
        bad = result["overflow"] or [f"slide {f['slide']} {f['placeholder']} {f['contrast']}<{f['min']}"
                                     for f in result.get("contrast_failures", [])] + result.get("hard_geometry", [])
        print(f"{tid}: beauty {result.get('beauty')} hard {result.get('hard_violations')} "
              f"fill {result.get('mean_fill')} white {result.get('png_whitespace')} gate {result.get('gate')} "
              f"{result.get('min_contrast', '')} {bad[:6]}")
    return 0


def write_scores_md(results: dict, gate: dict) -> None:
    lines = [
        "# Gallery scores (specimen v3)",
        "",
        "Written by `design/templates/src/qa.py`. Beauty = mean chosen-candidate score over the content slides (0-1).",
        "Hard = geometry violations kept by the renderer + pixel contrast failures. Fill = mean geometry fill ratio",
        "(card area at half weight); balance = mean balance score; PNG whitespace = blank share of the content area",
        f"(local variance, {WHITE_WINDOW} px window at {EXPORT_W} px, std < {WHITE_STD}).",
        "",
        f"Gate: beauty >= {gate['threshold']} and hard <= {gate['max_hard_violations']}. {gate['calibration']}",
        "",
        "| Template | Beauty | Hard | Mean fill | Mean balance | PNG whitespace | Gate |",
        "|---|---|---|---|---|---|---|",
    ]
    for tid, r in results.items():
        if r["overflow"]:
            lines.append(f"| {tid} | overflow | {len(r['overflow'])} | | | | fail |")
            continue
        verdict = "n/a" if r["gate"] is None else "pass" if r["gate"] else "fail"
        lines.append(f"| {tid} | {r['beauty']:.3f} | {r['hard_violations']} | {r['mean_fill']:.3f} | "
                     f"{r['mean_balance']:.3f} | {r['png_whitespace']:.3f} | {verdict} |")
    (OUT / "scores.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
