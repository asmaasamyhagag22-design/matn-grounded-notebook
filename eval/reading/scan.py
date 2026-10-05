"""Step 4c measurement: the OCR route on synthetic scans (exact truth) and on the real scans that have arrived.

Rules: docs/ocr_rules.md (frozen). Outputs (git-ignored) go to out/reading/ocr/<config>/: one JSON per subset with
page records, plus crops of every flagged line. The report is reports/step4c-ocr.md.

    .venv\\Scripts\\python.exe -m eval.reading.scan calibrate              # dev-tune only, GAO p12 excluded
    .venv\\Scripts\\python.exe -m eval.reading.scan run --config full --subset dev_tune
    .venv\\Scripts\\python.exe -m eval.reading.scan real --config full
    .venv\\Scripts\\python.exe -m eval.reading.scan report

dev_check refuses to run while the confidence bar is not frozen. The test split is never opened here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from PIL import Image

from eval.reading.degrade import degrade, page_seed, rotate_bbox
from eval.reading.digital import DEV_PAGE_SPLIT, _cer_counts, dev_documents
from eval.reading.metrics import Word as MetricWord, score_numbers
from matn_contracts.enums import Visibility
from matn_reading.ocr.glm import GlmReader
from matn_reading.ocr.numbers import number_tokens
from matn_reading.ocr.preprocess import PreprocessConfig, preprocess, render_page_image
from matn_reading.overlay import draw_scan_overlay
from matn_reading.ocr.reader1 import RapidOcrWorker
from matn_reading.ocr.route import RULES, OcrConfig, read_scan_page
from matn_reading.pdf_page import OpenPdf
from matn_reading.read import read_document
from matn_reading.triage import Route, decide_route

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "out" / "reading" / "ocr"
SYNTHETIC = json.loads((REPO / "eval" / "reading" / "synthetic" / "pages.json").read_text(encoding="utf-8"))
CALIBRATION_EXCLUDED = {("gao-21-519sp", 12)}          # previously seen by the owner (Step 4c Part 0)
CONFIGS = {
    "full": dict(preprocess=PreprocessConfig(), second_read=True),
    "no_deskew": dict(preprocess=PreprocessConfig(deskew=False), second_read=True),
    "no_denoise": dict(preprocess=PreprocessConfig(denoise=False), second_read=True),
    "reader1_alone": dict(preprocess=PreprocessConfig(), second_read=False),
}
FLAGGED_REGION_KINDS = ("possible_drop", "ocr_no_text")
BAR_GRID = [round(0.50 + 0.01 * i, 2) for i in range(50)] + [0.995, 0.999, 1.0]


def _subset(doc_id: str, page_index: int) -> str:
    return "dev_tune" if page_index in DEV_PAGE_SPLIT["documents"][doc_id]["dev_tune"] else "dev_check"


def synthetic_pages(subset: str) -> list[dict]:
    return [p for p in SYNTHETIC["pages"] if _subset(p["doc_id"], p["page_index"]) == subset]


def synthetic_image(doc_id: str, path: Path, page_index: int) -> tuple[Image.Image, dict]:
    """The degraded 300-DPI scan, regenerated from its seed and cached (out/ is git-ignored)."""
    cache = REPO / "out" / "reading" / "synthetic" / doc_id / f"p{page_index:04d}.png"
    rendered = render_page_image(path, page_index, SYNTHETIC["dpi"])
    image, params = degrade(rendered, page_seed(doc_id, page_index))
    if not cache.is_file():
        cache.parent.mkdir(parents=True, exist_ok=True)
        image.save(cache)
    params["sha256"] = hashlib.sha256(image.tobytes()).hexdigest()
    return image, params


def ground_truth(page, angle: float, size: tuple[int, int]) -> tuple[list[MetricWord], list[tuple]]:
    """Visible words (all block types) plus footnote markers, and visible lines; boxes moved into the processed frame."""
    scale = SYNTHETIC["dpi"] / 72
    ox, oy = page.cropbox[0], page.cropbox[1]

    def move(box):
        px = ((box[0] - ox) * scale, (box[1] - oy) * scale, (box[2] - ox) * scale, (box[3] - oy) * scale)
        x0, y0, x1, y1 = rotate_bbox(px, angle, size) if angle else px
        return (ox + x0 / scale, oy + y0 / scale, ox + x1 / scale, oy + y1 / scale)

    words, lines, seen = [], [], set()
    for block in page.blocks:
        if block.contract.visibility is not Visibility.VISIBLE:
            continue
        for line in block.layout.lines:
            lines.append((move((line.x0, line.top, line.x1, line.bottom)), line.text))
            for word in line.words:
                key = (word.text, round(word.x0, 1), round(word.top, 1))
                if key not in seen:
                    seen.add(key)
                    words.append(MetricWord(word.text, move((word.x0, word.top, word.x1, word.bottom))))
    for marker in page.footnote_markers:
        key = (marker["text"], round(marker["bbox"][0], 1), round(marker["bbox"][1], 1))
        if key not in seen:
            seen.add(key)
            words.append(MetricWord(marker["text"], move(marker["bbox"])))
    return words, lines


def _overlap(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return 0.0 if smaller <= 0 else ix * iy / smaller


def token_correct(token: dict, gt: list[MetricWord]) -> bool:
    best, best_overlap = None, 0.3
    for word in gt:
        overlap = _overlap(token["bbox"], word.bbox)
        if overlap > best_overlap:
            best, best_overlap = word, overlap
    return best is not None and token["token"] in number_tokens(best.text)


def score_page(ocr_page, gt_words, gt_lines) -> dict:
    tokens = ocr_page.ocr["tokens"]
    hyp = [MetricWord(t["token"], tuple(t["bbox"]), t["flagged"]) for t in tokens]
    regions = [tuple(f["bbox"]) for f in ocr_page.flags if f["kind"] in FLAGGED_REGION_KINDS]
    numbers = score_numbers(gt_words, hyp, flagged_regions=regions)
    for t in tokens:
        t["correct"] = token_correct(t, gt_words)
    flagged = [t for t in tokens if t["flagged"]]
    second = [t for t in tokens if t["status"] != "reader1_only"]
    hyp_lines = [(tuple(l["bbox"]), l["text"]) for l in ocr_page.ocr["lines"]]
    cer = _cer_counts(gt_lines, hyp_lines)
    return {
        "numbers": {k: getattr(numbers, k) for k in ("total", "correct", "wrong", "missing", "inserted", "silent_errors",
                                                     "silent_drops", "flagged_wrong", "flagged_total",
                                                     "unflagged_total", "unflagged_correct")},
        "number_problems": numbers.details,
        "reader1_tokens": len(tokens), "flagged_tokens": len(flagged),
        "false_alarms": sum(t["correct"] for t in flagged),
        "second_read_tokens": len(second), "agreed_tokens": sum(t["status"] == "agreed" for t in second),
        "reader1_correct": sum(t["correct"] for t in tokens),
        "cer": cer,
    }


def _timing(ocr: dict, preprocess_s: float) -> dict:
    reader1 = ocr.get("reader1_wall_seconds") or ocr.get("reader1_seconds") or 0.0
    second = ocr["second_reads"]["seconds"]
    return {"preprocess": round(preprocess_s, 2), "reader1": round(reader1, 2), "second_reads": round(second, 2),
            "without_second_reads": round(preprocess_s + reader1, 2),
            "with_second_reads": round(preprocess_s + reader1 + second, 2)}


def write_overlay(ocr_page, image: Image.Image, config: OcrConfig, path: Path) -> Path:
    """Overlay on the image reader 1 saw (preprocessing is deterministic, so it is recomputed here)."""
    processed, _ = preprocess(image, config.preprocess)
    path.parent.mkdir(parents=True, exist_ok=True)
    draw_scan_overlay(ocr_page, processed, config.dpi).save(path, optimize=True)
    return path


def _config(name: str, bar: float | None) -> OcrConfig:
    return OcrConfig(confidence_bar=bar, **CONFIGS[name])


def run_synthetic(config_name: str, subset: str, *, bar: float | None = None, pages: list[dict] | None = None,
                  label: str | None = None, glm: GlmReader | None = None) -> dict:
    frozen = RULES["confidence_bar"]
    if subset == "dev_check" and frozen is None:
        raise SystemExit("dev_check refused: the confidence bar is not frozen yet (docs/ocr_rules.md section 4)")
    bar = frozen if bar is None else bar
    config = _config(config_name, bar)
    docs = dict(dev_documents())
    pages = synthetic_pages(subset) if pages is None else pages
    out_dir = OUT / (label or config_name)
    glm = glm if glm is not None else (GlmReader() if config.second_read else None)
    records = []
    with RapidOcrWorker() as worker:
        for spec in pages:
            doc_id, index = spec["doc_id"], spec["page_index"]
            started = time.perf_counter()
            image, params = synthetic_image(doc_id, docs[doc_id], index)
            digital = read_document(docs[doc_id], pages=[index]).pages[0]
            page_started = time.perf_counter()
            ocr_page = read_scan_page(image, page_index=index, page_label=digital.page_label, cropbox=digital.cropbox,
                                      route=Route.SCANNED, reasons=["synthetic scan"], doc_id="sha256-" + "0" * 64,
                                      worker=worker, glm=glm, config=config, crop_dir=out_dir)
            wall = time.perf_counter() - page_started
            angle = params["rotation_deg"] + ocr_page.ocr["preprocess"]["rotation_deg"]
            gt_words, gt_lines = ground_truth(digital, angle, image.size)
            if config_name == "full":
                write_overlay(ocr_page, image, config, out_dir / "overlays" / doc_id / f"p{index:04d}.png")
            scored = score_page(ocr_page, gt_words, gt_lines)
            records.append({
                "doc_id": doc_id, "page_index": index, "subset": subset, "kinds": spec["kinds"], "degrade": params,
                "config": config_name, "bar": bar, "wall_seconds": round(wall, 2),
                "timing": _timing(ocr_page.ocr, ocr_page.ocr.get("preprocess_seconds", 0.0)),
                "mean_confidence": ocr_page.ocr["mean_confidence"], "second_reads": ocr_page.ocr["second_reads"],
                **scored, "tokens": ocr_page.ocr["tokens"], "flags": ocr_page.flags,
                "preprocess": ocr_page.ocr["preprocess"], "total_seconds": round(time.perf_counter() - started, 2),
            })
            print(f"{config_name} {subset} {doc_id} p{index}: tokens {scored['reader1_tokens']} flagged "
                  f"{scored['flagged_tokens']} silent {scored['numbers']['silent_errors']} drops "
                  f"{scored['numbers']['silent_drops']} {wall:.1f}s", flush=True)
    result = {"config": config_name, "subset": subset, "bar": bar, "pages": records}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{subset}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str),
                                            encoding="utf-8")
    return result


def calibrate() -> dict:
    """Frozen procedure (docs/ocr_rules.md section 4): reader 1 only, dev-tune minus GAO p12."""
    pages = [p for p in synthetic_pages("dev_tune") if (p["doc_id"], p["page_index"]) not in CALIBRATION_EXCLUDED]
    result = run_synthetic("reader1_alone", "dev_tune", bar=0.0, pages=pages, label="calibration")
    wrong = [t for page in result["pages"] for t in page["tokens"]
             if not t["correct"] and not ({"table", "kpi"} & set(t["targets"]))]
    bar = next(b for b in BAR_GRID if all(t["score"] < b for t in wrong))
    all_tokens = [t for page in result["pages"] for t in page["tokens"]]
    summary = {"bar": bar, "pages": len(pages), "tokens": len(all_tokens),
               "wrong_outside_table_kpi": len(wrong), "wrong_total": sum(not t["correct"] for t in all_tokens),
               "max_wrong_score": max((t["score"] for t in wrong), default=None),
               "below_bar_share": round(sum(t["score"] < bar for t in all_tokens) / max(len(all_tokens), 1), 4),
               "wrong_examples": [{k: t[k] for k in ("token", "word", "score")} for t in
                                  sorted(wrong, key=lambda t: -t["score"])[:15]]}
    (OUT / "calibration" / "bar.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


REAL_PAGES = {"nbs_circular_31_e4_1956": [7, 15, 32], "statab_1951_part04": [0, 8, 45]}


def run_real(config_name: str) -> dict:
    from eval.reading.real.verify import require_verified

    if RULES["confidence_bar"] is None:
        raise SystemExit("real scans wait for the frozen confidence bar")
    config = _config(config_name, RULES["confidence_bar"])
    out_dir = OUT / config_name
    glm = GlmReader() if config.second_read else None
    records = []
    with RapidOcrWorker() as worker:
        for doc_key, indices in REAL_PAGES.items():
            try:
                path = require_verified(doc_key)
            except Exception as error:  # absent or hash mismatch: report, never measure
                records.append({"doc_key": doc_key, "skipped": str(error)})
                continue
            with OpenPdf(path) as pdf:
                for index in indices:
                    data = pdf.page(index)
                    route, reasons = decide_route(data.signals)
                    layer = [(w.text, (w.x0, w.top, w.x1, w.bottom)) for w in data.words] \
                        if route is Route.SCANNED_WITH_OCR_LAYER else []
                    image = render_page_image(path, index)
                    started = time.perf_counter()
                    ocr_page = read_scan_page(image, page_index=index, page_label=data.page_label,
                                              cropbox=data.cropbox, route=route, reasons=reasons,
                                              doc_id="sha256-" + "0" * 64, worker=worker, glm=glm, config=config,
                                              crop_dir=out_dir, text_layer=layer)
                    tokens = ocr_page.ocr["tokens"]
                    if config_name == "full":
                        write_overlay(ocr_page, image, config, out_dir / "overlays" / doc_key / f"p{index:04d}.png")
                    layer_numbers = tokens if layer else []
                    records.append({
                        "doc_key": doc_key, "page_index": index, "route": route.value, "reasons": reasons,
                        "wall_seconds": round(time.perf_counter() - started, 2),
                        "timing": _timing(ocr_page.ocr, ocr_page.ocr.get("preprocess_seconds", 0.0)),
                        "mean_confidence": ocr_page.ocr["mean_confidence"], "tokens": tokens, "flags": ocr_page.flags,
                        "reader1_tokens": len(tokens), "flagged_tokens": sum(t["flagged"] for t in tokens),
                        "layer_disagreements": sum("ocr_layer_disagreement" in t["reasons"] for t in layer_numbers),
                        "layer_compared": len(layer_numbers),
                        "second_read_tokens": sum(t["status"] != "reader1_only" for t in tokens),
                        "agreed_tokens": sum(t["status"] == "agreed" for t in tokens),
                        "preprocess": ocr_page.ocr["preprocess"],
                    })
                    print(f"real {doc_key} p{index}: {route.value} tokens {len(tokens)} flagged "
                          f"{records[-1]['flagged_tokens']}", flush=True)
    result = {"config": config_name, "subset": "real", "pages": records}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "real.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("calibrate")
    run = sub.add_parser("run")
    run.add_argument("--config", choices=sorted(CONFIGS), default="full")
    run.add_argument("--subset", choices=("dev_tune", "dev_check"), required=True)
    real = sub.add_parser("real")
    real.add_argument("--config", choices=sorted(CONFIGS), default="full")
    sub.add_parser("report")
    args = parser.parse_args()
    if args.command == "calibrate":
        calibrate()
    elif args.command == "run":
        run_synthetic(args.config, args.subset)
    elif args.command == "real":
        run_real(args.config)
    else:
        from eval.reading.scan_report import write_report

        write_report()


if __name__ == "__main__":
    main()
