"""Gallery QA: render the specimen (v4) in every template, export PNGs through PowerPoint, measure contrast and whitespace,
compute the beauty score, and build the sheets.

For each template the specimen is rendered strictly (any overflow fails), then a "blank" copy is made with every
text run emptied and chart text made fully transparent. Both are exported through PowerPoint; pixels that
differ are the text. In each text placeholder and chart, the text color is the median of the most-changed pixels and
the background is the blank render under those same pixels, so images and gradients are measured as shown.
Contrast is the 5th percentile over the glyph pixels. Minimums (WCAG 2.x): 4.5 for body text, small text and chart
labels; 3.0 for large text (at least 18 pt, or 14 pt bold). Dark templates are held to projector minimums (overnight
Part 4, owner request): 7.0 for body text and chart labels, 4.5 for large text.

Whitespace (cross-check of the geometry ink fill, after AeSlides): on each content slide's PNG, a pixel is blank when
the standard deviation of its local window is below WHITE_STD; the PNG non-blank share is 1 - the blank share of the
content area. scores.md reports how the two measures agree, slide by slide.

Beauty score (the gallery gate, design/scoring.json "beauty_gate"): the mean chosen-candidate score over the specimen's
content slides, plus the count of hard violations (geometry violations kept by the renderer and pixel contrast
failures). A template passes when its score reaches the threshold and it has no hard violation.

Usage: .venv\\Scripts\\python.exe design/templates/src/qa.py
  writes out/gallery/<id>/scores.json, out/gallery/contact_sheet_v4.png, out/gallery/before_after_v4.png (v3 PNGs
  kept in out/gallery/<id>/png_v3/), out/gallery/scores.md and design/templates/qa.json
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
PROJECTOR_BODY_MIN, PROJECTOR_LARGE_MIN = 7.0, 4.5  # dark templates (theme.json mode "dark")
WHITE_WINDOW = 15  # px at 2560 wide (about 5.6 pt)
WHITE_STD = 2.0  # grey levels: below this the window is flat
ART_CONTENT_STD_MAX = 12.0
ART_EDGE_STD_DELTA_MIN = 0.5
ART_MEAN_DELTA_MIN = 6.0
BEFORE_AFTER = ("integral-light", "film-burn-dark", "modulo")
SHEET, PAIRS = "contact_sheet_v4.png", "before_after_v4.png"
CREATIVE_SHEET, FAMILIES_SHEET = "contact_sheet_creative.png", "families.png"
FAMILY_COMPARE = ("integral-light", "film-burn-dark", "modulo", "nile-night", "papyrus", "mashrabiya")
PREVIOUS = ("png_v3", "v3 (Step 2c)", "v4 (Step 2c.1)")  # folder of the earlier PNGs, row labels
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


def decor_zone_metrics(png: Path, area_pt: list[float]) -> dict:
    """Exported-background personality: calm content area plus visibly different edge/decor area."""
    data = np.asarray(Image.open(png).convert("RGB"), dtype=float)
    scale = data.shape[1] / 960
    x, y, w, h = (round(v * scale) for v in area_pt)
    content = data[y:y + h, x:x + w]
    mask = np.ones(data.shape[:2], dtype=bool)
    mask[y:y + h, x:x + w] = False
    edge = data[mask]
    content_std = float(np.std(content, axis=(0, 1)).mean())
    edge_std = float(np.std(edge, axis=0).mean())
    mean_delta = float(np.linalg.norm(edge.mean(axis=0) - content.mean(axis=(0, 1))))
    return {"content_std": round(content_std, 2), "edge_std": round(edge_std, 2),
            "mean_delta": round(mean_delta, 2), "calm": content_std < ART_CONTENT_STD_MAX,
            "perceptible": edge_std - content_std >= ART_EDGE_STD_DELTA_MIN or mean_delta >= ART_MEAN_DELTA_MIN}


def content_sizes(slide) -> set[float]:
    """Distinct text sizes on a slide, without chrome (the source chip)."""
    sizes = set()
    for shape in slide.placeholders:
        if shape.name == "source":
            continue
        if getattr(shape, "has_chart", False) and shape.has_chart:
            if shape.chart.font.size:
                sizes.add(shape.chart.font.size.pt)
            continue
        sizes |= {r.font.size.pt for p in shape.text_frame.paragraphs for r in p.runs if r.font.size}
    return sizes


def reference_scores(scores: list[dict]) -> dict:
    """Calibration reference points from the recorded candidates of the content slides: a 2b-style choice (first
    valid variant, step S, top), an arbitrary valid candidate (mean of all valid ones) and the chosen one."""
    naive, arbitrary, chosen = [], [], []
    for e in scores:
        if e["slide_type"] not in CONTENT:
            continue
        chosen.append(e["chosen"]["total"])
        valid = [c for c in e["candidates"] if not c["hard"]]
        first = e["candidates"][0]["layout"]
        two_b = [c for c in e["candidates"] if c["layout"] == first and c["step"] == "S" and c["anchor"] == "top"]
        naive.append(two_b[0]["total"] if two_b and not two_b[0]["hard"] else 0.0)
        arbitrary.append(sum(c["total"] for c in valid) / len(valid) if valid else 0.0)

    def mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 4)

    return {"two_b_style": mean(naive), "arbitrary_valid": mean(arbitrary), "chosen": mean(chosen)}


def measure(deck: Path, shown_dir: Path, blank_dir: Path, *, dark: bool = False) -> list[dict]:
    body_min, large_min = (PROJECTOR_BODY_MIN, PROJECTOR_LARGE_MIN) if dark else (BODY_MIN, LARGE_MIN)
    prs = Presentation(str(deck))
    sx, sy = EXPORT_W / prs.slide_width, EXPORT_H / prs.slide_height
    rows = []
    for number, slide in enumerate(prs.slides, start=1):
        shown = np.asarray(Image.open(shown_dir / f"slide_{number:02d}.png").convert("RGB"))
        blank = np.asarray(Image.open(blank_dir / f"slide_{number:02d}.png").convert("RGB"))
        layout_ph = {ph.name: ph for ph in slide.slide_layout.placeholders}
        for shape in slide.shapes:
            if shape.has_chart if hasattr(shape, "has_chart") else False:
                kind, minimum = "chart", body_min
            elif shape.has_text_frame and shape.text_frame.text.strip() and shape.name in layout_ph:
                style = placeholder_style(layout_ph[shape.name])
                runs = [r for p in shape.text_frame.paragraphs for r in p.runs if r.text.strip()]
                size = min((r.font.size.pt for r in runs if r.font.size), default=style.size_pt)
                large = size >= 18 or (style.bold and size >= 14)
                kind, minimum = ("large" if large else "body"), (large_min if large else body_min)
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
        prs = Presentation(str(folder / "specimen.pptx"))
        results[tid] = {
            "references": reference_scores(list(report.scores)),
            "split_slides": len({e["plan_index"] for e in report.scores if e["part"] is not None}),
            "max_content_sizes": max(len(content_sizes(prs.slides[e["slide"] - 1])) for e in content),
            "slide_fill": {e["slide"]: e["chosen"]["soft"]["fill_ratio"] for e in content},
            "slide_layout": {e["slide"]: e["chosen"]["layout"] for e in content},
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
    if sys.platform == "win32":
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SRC / "export_png.ps1"),
                        "-Pptx", ",".join(map(str, decks)), "-OutDir", ",".join(map(str, dirs)),
                        "-Width", str(EXPORT_W), "-Height", str(EXPORT_H)], check=True, cwd=ROOT)
    else:
        from scripts.export_deck import export_deck
        for deck, directory in zip(decks, dirs):
            export_deck(deck, directory, deck.with_suffix(".pdf"), width=EXPORT_W, height=EXPORT_H)


    groups = []
    groups_by_id = {}
    for entry in entries:
        tid = entry["id"]
        result = results[tid]
        if result["overflow"]:
            continue
        meta = json.loads((SRC.parent / tid / "theme.json").read_text(encoding="utf-8"))
        rows = measure(OUT / tid / "specimen.pptx", OUT / tid / "png", OUT / tid / "blank_png",
                       dark=meta.get("mode") == "dark")
        failures = [r for r in rows if not r["ok"]]
        area = meta["content_area_pt"]
        blank = [whitespace(OUT / tid / "png" / f"slide_{n:02d}.png", area) for n in result["content_slides"]]
        result["slide_png"] = {n: round(1 - b, 4) for n, b in zip(result["content_slides"], blank)}
        art = decor_zone_metrics(OUT / tid / "blank_png" / "slide_01.png", area)
        art_failures = []
        if meta.get("family") == "creative":
            if not art["calm"]:
                art_failures.append(f"ART_CONTENT_NOT_CALM:{art['content_std']}>={ART_CONTENT_STD_MAX}")
            if not art["perceptible"]:
                art_failures.append("ART_NOT_PERCEPTIBLE")
        hard = len(result["hard_geometry"]) + len(failures) + len(art_failures)
        result.update({
            "min_contrast": {kind: min((r["contrast"] for r in rows if r["kind"] == kind), default=None)
                             for kind in ("body", "large", "chart")},
            "contrast_failures": failures,
            "art": art,
            "art_failures": art_failures,
            "png_whitespace": round(sum(blank) / len(blank), 4),
            "png_nonblank": round(1 - sum(blank) / len(blank), 4),
            "hard_violations": hard,
            "gate": None if gate["threshold"] is None else
            bool(result["beauty"] >= gate["threshold"] and hard <= gate["max_hard_violations"]),
        })
        pngs = sorted((OUT / tid / "png").glob("slide_*.png"))
        group = (f"{entry['name_en']}  ·  {tid}  ·  beauty {result['beauty']:.3f}", pngs)
        groups.append(group)
        groups_by_id[tid] = group
    build_sheet(groups, OUT / SHEET, per_row=1, thumb_w=240, label_size=20)
    creative_ids = [entry["id"] for entry in entries if entry.get("family", "classic") == "creative"]
    build_sheet([groups_by_id[tid] for tid in creative_ids if tid in groups_by_id], OUT / CREATIVE_SHEET,
                per_row=1, thumb_w=240, label_size=20)
    build_sheet([(tid, [groups_by_id[tid][1][0]]) for tid in FAMILY_COMPARE if tid in groups_by_id],
                OUT / FAMILIES_SHEET, per_row=len(FAMILY_COMPARE), thumb_w=240, label_size=18)
    pairs = []
    folder_before, label_before, label_after = PREVIOUS
    for tid in BEFORE_AFTER:
        if (OUT / tid / folder_before).is_dir() and tid in results and not results[tid]["overflow"]:
            pairs += [(f"{label_before}  ·  {tid}", sorted((OUT / tid / folder_before).glob("slide_*.png"))),
                      (f"{label_after}  ·  {tid}", sorted((OUT / tid / "png").glob("slide_*.png")))]
    if pairs:
        build_sheet(pairs, OUT / PAIRS, per_row=1, thumb_w=240, label_size=20)
    (SRC.parent / "qa.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_scores_md(results, gate)
    for tid, result in results.items():
        bad = result["overflow"] or [f"slide {f['slide']} {f['placeholder']} {f['contrast']}<{f['min']}"
                                     for f in result.get("contrast_failures", [])] + result.get("hard_geometry", []) + \
                                    result.get("art_failures", [])
        print(f"{tid}: beauty {result.get('beauty')} hard {result.get('hard_violations')} "
              f"fill {result.get('mean_fill')} png {result.get('png_nonblank')} splits {result.get('split_slides')} "
              f"sizes {result.get('max_content_sizes')} refs {result.get('references')} gate {result.get('gate')} "
              f"{result.get('min_contrast', '')} art {result.get('art', '')} {bad[:6]}")
    return 0


def agreement(results: dict) -> dict:
    """How the geometry ink fill and the PNG non-blank share agree over every content slide of every template."""
    rows = [(tid, n, r["slide_fill"][n], r["slide_png"][n], r["slide_layout"][n])
            for tid, r in results.items() if not r["overflow"] for n in r["slide_fill"]]  # keys survive qa.json
    geo = np.array([row[2] for row in rows])
    png = np.array([row[3] for row in rows])
    charts = np.array([row[4].startswith("matn:chart:") for row in rows])
    def worst(mask: np.ndarray) -> list[tuple]:
        g, p = geo[mask], png[mask]
        z = (g - g.mean()) / g.std() - (p - p.mean()) / p.std()
        picked = [row for row, keep in zip(rows, mask) if keep]
        return [picked[i] + (round(float(z[i]), 2),) for i in np.argsort(-np.abs(z))[:5]]

    everything = np.ones(len(rows), dtype=bool)
    return {"n": len(rows), "r_all": float(np.corrcoef(geo, png)[0, 1]),
            "r_no_charts": float(np.corrcoef(geo[~charts], png[~charts])[0, 1]),
            "worst": worst(everything), "worst_no_charts": worst(~charts)}


def write_scores_md(results: dict, gate: dict) -> None:
    agree = agreement(results)
    card_weight = load_scoring()["fill"]["card_weight"]
    lines = [
        "# Gallery scores (specimen v4, Step 2d)",
        "",
        "Written by `design/templates/src/qa.py`. Beauty = mean chosen-candidate score over the content slides (0-1);",
        "it shows the system beats arbitrary choices, it is not an absolute measure of beauty. Hard = geometry",
        "violations kept by the renderer + pixel contrast failures. Ink fill = mean geometry fill from ink (text line",
        f"boxes, chart plot areas, values, icons, bars; card background at weight {card_weight}). PNG non-blank = share",
        f"of the content area whose local variance is not flat ({WHITE_WINDOW} px window at {EXPORT_W} px, std >=",
        f"{WHITE_STD}). Splits = plan slides that became several slides. Sizes = most content text sizes on one slide",
        "(chrome excluded). 2b-style and Arbitrary = calibration reference scores from the same candidates.",
        "",
        f"Gate: beauty >= {gate['threshold']} and hard <= {gate['max_hard_violations']}. {gate['calibration']}",
        "",
        "| Template | Beauty | Hard | Ink fill | PNG non-blank | Edge std | Content std | Mean balance | Splits | Sizes "
        "| 2b-style | Arbitrary | Gate |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for tid, r in results.items():
        if r["overflow"]:
            lines.append(f"| {tid} | overflow | {len(r['overflow'])} | | | | | | | | | | fail |")
            continue
        verdict = "n/a" if r["gate"] is None else "pass" if r["gate"] else "fail"
        ref = r["references"]
        art = r["art"]
        lines.append(f"| {tid} | {r['beauty']:.3f} | {r['hard_violations']} | {r['mean_fill']:.3f} | "
                     f"{r['png_nonblank']:.3f} | {art['edge_std']:.2f} | {art['content_std']:.2f} | "
                     f"{r['mean_balance']:.3f} | {r['split_slides']} | {r['max_content_sizes']} | "
                     f"{ref['two_b_style']:.3f} | {ref['arbitrary_valid']:.3f} | {verdict} |")
    lines += [
        "",
        "## Ink fill vs PNG non-blank",
        "",
        f"Pearson r over {agree['n']} content slides: {agree['r_all']:.2f} with charts, "
        f"{agree['r_no_charts']:.2f} without charts.",
        "",
        "The five slides where the two measures disagree most (difference of their z-scores; positive = the geometry",
        "counts more ink than the PNG shows):",
        "",
        "| Template | Slide | Layout | Ink fill | PNG non-blank | z difference |",
        "|---|---|---|---|---|---|",
    ]
    lines += [f"| {tid} | {n} | {layout} | {g:.3f} | {p:.3f} | {d:+.2f} |" for tid, n, g, p, layout, d in agree["worst"]]
    lines += ["", "Without charts:", "", "| Template | Slide | Layout | Ink fill | PNG non-blank | z difference |",
              "|---|---|---|---|---|---|"]
    lines += [f"| {tid} | {n} | {layout} | {g:.3f} | {p:.3f} | {d:+.2f} |"
              for tid, n, g, p, layout, d in agree["worst_no_charts"]]
    lines += [
        "",
        "Why they still disagree: the variance map sees edges, not area. Inside a solid bar, a flat KPI tile, a tinted",
        "hero card or the thick strokes of a 100+ pt number there is no local variance, so the PNG calls it blank,",
        "while the geometry counts a chart's plot area and a value's line box as ink by definition. Charts are the",
        "largest outliers; without them the agreement is only moderate, and the remaining gap is systematic by layout:",
        "big-number layouts (hero-number, bento, single-hero) read emptier in the PNG than in the geometry, and row",
        "layouts with markers and card edges (numbered limitations, the executive-summary rows) read fuller. The fill",
        "definition was not tuned to close this gap.",
    ]
    (OUT / "scores.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
