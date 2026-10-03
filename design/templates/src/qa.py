"""Gallery QA: render specimen v2 in every template, export PNGs through PowerPoint, measure contrast, build sheets.

For each template the specimen is rendered strictly (any overflow fails), then a "blank" copy is made with every
text run emptied and chart text made fully transparent. Both are exported through PowerPoint; pixels that
differ are the text. In each text placeholder and chart, the text color is the median of the most-changed pixels and
the background is the blank render under those same pixels, so images and gradients are measured as shown.
Contrast is the 5th percentile over the glyph pixels. Minimums (WCAG 2.x): 4.5 for body text, small text and chart
labels; 3.0 for large text (at least 18 pt, or 14 pt bold).

Usage: .venv\\Scripts\\python.exe design/templates/src/qa.py   (writes out/gallery/ and design/templates/qa.json)
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
from matn_deck.specimen_v2 import main as render_specimen  # noqa: E402
from matn_deck.template_renderer import DeckOverflowError  # noqa: E402

EXPORT_W, EXPORT_H = 2560, 1440
BODY_MIN, LARGE_MIN = 4.5, 3.0


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
                color = shape.chart._chartSpace.find(".//" + qn("c:txPr")).find(".//" + qn("a:srgbClr"))
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
                large = style.size_pt >= 18 or (style.bold and style.size_pt >= 14)
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
    results, decks, dirs = {}, [], []
    gallery["templates"] = [entry for entry in gallery["templates"] if not entry.get("excluded")]
    for entry in gallery["templates"]:
        tid = entry["id"]
        folder = OUT / tid
        folder.mkdir(parents=True, exist_ok=True)
        template = SRC.parent / tid / "template.pptx"
        try:
            report = render_specimen(template, folder / "specimen.pptx")
            results[tid] = {"overflow": [], "layouts": list(report.layouts)}
        except DeckOverflowError as exc:
            results[tid] = {"overflow": [f"slide {o.slide_number} {o.placeholder}" for o in exc.report.overflows]}
            continue
        blank_copy(folder / "specimen.pptx", folder / "blank.pptx")
        decks += [folder / "specimen.pptx", folder / "blank.pptx"]
        dirs += [folder / "png", folder / "blank_png"]
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SRC / "export_png.ps1"),
                    "-Pptx", ",".join(map(str, decks)), "-OutDir", ",".join(map(str, dirs)),
                    "-Width", str(EXPORT_W), "-Height", str(EXPORT_H)], check=True, cwd=ROOT)

    groups = []
    for entry in gallery["templates"]:
        tid = entry["id"]
        if results[tid]["overflow"]:
            continue
        rows = measure(OUT / tid / "specimen.pptx", OUT / tid / "png", OUT / tid / "blank_png")
        failures = [r for r in rows if not r["ok"]]
        results[tid].update({
            "min_contrast": {kind: min((r["contrast"] for r in rows if r["kind"] == kind), default=None)
                             for kind in ("body", "large", "chart")},
            "contrast_failures": failures,
        })
        pngs = sorted((OUT / tid / "png").glob("slide_*.png"))
        groups.append((f"{entry['name_en']}  ·  {tid}", pngs))
    build_sheet(groups, OUT / "contact_sheet.png", per_row=1, thumb_w=240, label_size=20)
    (SRC.parent / "qa.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for tid, result in results.items():
        bad = result["overflow"] or [f"slide {f['slide']} {f['placeholder']} {f['contrast']}<{f['min']}"
                                     for f in result.get("contrast_failures", [])]
        print(f"{tid}: {'OK' if not bad else 'FAIL'} {result.get('min_contrast', '')} {bad[:6]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
