"""Step 4b digital-reading measurement on the 3 dev documents (rules: docs/reading_eval_rules.md, frozen).

Reader: matn_reading (pdfplumber + pypdfium2). Reference: PyMuPDF words and blocks (eval tooling only, ADR-0001),
a different engine. Only dev-split documents are read; anything else is refused before the file is opened.

Outputs (git-ignored):  out/reading/overlays/<doc_id>/pNNNN.png, out/reading/baseline/<doc_id>.json
Report (in git):        reports/step4-baseline.md, reports/step4-reading-review.md

Usage: .venv\\Scripts\\python.exe -m eval.reading.digital [--label baseline] [--no-overlays]
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import pymupdf  # eval tooling only (ADR-0001)

from eval.reading.metrics import (
    NumberReport,
    Word as MetricWord,
    levenshtein,
    markdown_table,
    aggregate,
    normalize_for_cer,
    score_numbers,
)
from matn_reading.overlay import write_overlays
from matn_reading.pdf_page import render_page
from matn_reading.read import DocumentReading, read_document, words_out

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "eval"
OUT = REPO / "out" / "reading"
OVERLAY_SCALE = 1.5
REVIEW_PAGES = {"2601-14525v1": (0, 2, 9), "wb-eem-2021-12": (6, 14, 22), "gao-21-519sp": (1, 12, 29, 90)}
DEV_PAGE_SPLIT = json.loads((EVAL / "reading" / "dev_split.json").read_text(encoding="utf-8"))


def dev_documents() -> list[tuple[str, Path]]:
    splits = json.loads((EVAL / "splits.json").read_text(encoding="utf-8"))
    registry = json.loads((EVAL / "registry.json").read_text(encoding="utf-8"))
    docs = []
    for entry in registry["documents"]:
        if splits.get(entry["doc_id"], {}).get("split") != "dev":
            continue  # the test split is never opened here
        docs.append((entry["doc_id"], EVAL / entry["file"]))
    if sorted(d for d, _ in docs) != ["2601-14525v1", "gao-21-519sp", "wb-eem-2021-12"]:
        raise SystemExit(f"DEV_SET_CHANGED:{[d for d, _ in docs]}")
    return docs


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return 0.0 if union <= 0 else inter / union


def _cer_counts(ref_blocks: list[tuple[tuple, str]], hyp_blocks: list[tuple[tuple, str]]) -> dict:
    """Order-independent CER/WER over regions matched by IoU >= 0.5."""
    pairs, used = [], set()
    candidates = sorted(((_iou(r[0], h[0]), i, j) for i, r in enumerate(ref_blocks) for j, h in enumerate(hyp_blocks)),
                        reverse=True)
    matched_ref = set()
    for score, i, j in candidates:
        if score < 0.5:
            break
        if i not in matched_ref and j not in used:
            pairs.append((i, j))
            matched_ref.add(i)
            used.add(j)
    counts = {"char_edits": 0, "chars": 0, "word_edits": 0, "words": 0, "matched_blocks": len(pairs),
              "ref_blocks": len(ref_blocks), "hyp_blocks": len(hyp_blocks)}
    for i, j in pairs:
        ref, hyp = normalize_for_cer(ref_blocks[i][1]), normalize_for_cer(hyp_blocks[j][1])
        counts["chars"] += len(ref)
        counts["words"] += len(ref.split())
        if ref != hyp:
            counts["char_edits"] += levenshtein(ref, hyp)
            counts["word_edits"] += levenshtein(ref.split(), hyp.split())
    for i, (_, text) in enumerate(ref_blocks):
        if i not in matched_ref:
            ref = normalize_for_cer(text)
            counts["chars"] += len(ref)
            counts["char_edits"] += len(ref)
            counts["words"] += len(ref.split())
            counts["word_edits"] += len(ref.split())
    for j, (_, text) in enumerate(hyp_blocks):
        if j not in used:
            hyp = normalize_for_cer(text)
            counts["char_edits"] += len(hyp)
            counts["word_edits"] += len(hyp.split())
    return counts


def _reference_lines(page) -> list[tuple[tuple, str]]:
    lines = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            lines.append((tuple(line["bbox"]), text))
    return lines


def _hypothesis_lines(page) -> list[tuple[tuple, str]]:
    return [(tuple((line.x0, line.top, line.x1, line.bottom)), line.text)
            for block in page.blocks if block.contract.visibility.value == "visible"
            for line in block.layout.lines]


def _metric_markers(page) -> list[dict]:
    markers = list(page.footnote_markers)
    marker_texts = {marker["text"] for marker in page.footnote_markers}
    for block in page.blocks:
        if block.block_type != "footnote":
            continue
        words = [word for line in block.layout.lines for word in line.words]
        marker = next((text for text in marker_texts if words and words[0].text.startswith(text)), None)
        if marker:
            first = words[0]
            markers.append({"text": marker, "bbox": (first.x0, first.top, first.x1, first.bottom)})
    return markers


def _marker_regions(page) -> list[tuple]:
    return [tuple(marker["bbox"]) for marker in _metric_markers(page)]


def _centre_in_regions(box, regions) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(region[0] <= cx <= region[2] and region[1] <= cy <= region[3] for region in regions)


def _reference_word_without_markers(text: str, box, markers: list[dict]) -> str:
    """PyMuPDF often glues a raised marker to the preceding word; remove only the linked suffix."""
    for marker in markers:
        region = marker["bbox"]
        intersects = min(box[2], region[2]) > max(box[0], region[0]) and min(box[3], region[3]) > max(box[1], region[1])
        if intersects:
            if text.endswith(marker["text"]):
                return text[:-len(marker["text"])]
            if text.startswith(marker["text"]):
                return text[len(marker["text"]):]
            trailing = re.search(re.escape(marker["text"]) + r"(?=\W*$)", text)
            if trailing:
                return text[:trailing.start()] + text[trailing.end():]
    return text


def measure(doc_id: str, path: Path, label: str, overlays: bool, subset: str = "all") -> dict:
    started = time.monotonic()
    pages = None if subset == "all" else DEV_PAGE_SPLIT["documents"][doc_id][subset]
    reading: DocumentReading = read_document(path, pages=pages)
    reference = pymupdf.open(path)
    pages, totals = [], NumberReport()
    for page in reading.pages:
        ref_page = reference[page.page_index]
        metric_markers = _metric_markers(page)
        marker_regions = [tuple(marker["bbox"]) for marker in metric_markers]
        gt_words = []
        for word in ref_page.get_text("words"):
            box = (word[0], word[1], word[2], word[3])
            if _centre_in_regions(box, marker_regions):
                continue
            text = _reference_word_without_markers(word[4], box, metric_markers)
            if text:
                gt_words.append(MetricWord(text, box))
        hyp = [MetricWord(word.text, (word.x0, word.top, word.x1, word.bottom), flagged)
               for word, flagged in words_out(page)]
        flagged_regions = [f["bbox"] for f in page.flags
                           if f["kind"] in ("page_route", "figure_text", "code_text", "outside_cropbox")]
        flagged_regions += [b.layout.bbox for b in page.blocks if b.flagged]
        numbers = score_numbers(gt_words, hyp, flagged_regions=flagged_regions)
        totals.add(numbers)
        ref_blocks = [((b[0], b[1], b[2], b[3]), b[4]) for b in ref_page.get_text("blocks") if b[6] == 0]
        hyp_blocks = [(b.layout.bbox, b.layout.raw_text.replace("\n", " ")) for b in page.blocks
                      if b.contract.visibility.value == "visible"]
        cer = _cer_counts(_reference_lines(ref_page), _hypothesis_lines(page))
        legacy_cer = _cer_counts(ref_blocks, hyp_blocks)
        subset = "dev_tune" if page.page_index in DEV_PAGE_SPLIT["documents"][doc_id]["dev_tune"] else "dev_check"
        pages.append({
            "page_index": page.page_index, "page_label": page.page_label, "subset": subset, "route": page.route.value,
            "reasons": page.reasons, "signals": page.signals, "edge_cases": page.edge_cases,
            "blocks": [{"order": i, "type": b.block_type, "flagged": b.flagged, "bbox": b.layout.bbox,
                        "text": b.layout.text[:200], "block_id": b.contract.block_id,
                        "visibility": b.contract.visibility.value,
                        "visibility_reasons": [reason.value for reason in b.contract.visibility_reasons]}
                       for i, b in enumerate(page.blocks)],
            "flags": page.flags, "figure_regions": page.figure_regions, "tables": page.tables,
            "numbers": {k: getattr(numbers, k) for k in ("total", "correct", "wrong", "missing", "inserted",
                                                         "silent_errors", "silent_drops", "flagged_wrong",
                                                         "flagged_total", "unflagged_total", "unflagged_correct")},
            "number_problems": numbers.details, "cer": cer, "legacy_block_cer": legacy_cer,
            "footnote_markers": page.footnote_markers,
        })
    overlay_paths = []
    if overlays:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(path))
        renders = ((p.page_index, render_page(pdf[p.page_index], OVERLAY_SCALE), (p.cropbox[0], p.cropbox[1]))
                   for p in reading.pages)
        overlay_paths = write_overlays(reading.pages, renders, OUT / "overlays" / doc_id, OVERLAY_SCALE)
        pdf.close()
    result = {"label": label, "doc_id": doc_id, "contract_doc_id": reading.doc_id, "file": str(path.relative_to(REPO)),
              "body_size": reading.body_size, "seconds": round(time.monotonic() - started, 1), "pages": pages,
              "overlays": len(overlay_paths)}
    (OUT / label).mkdir(parents=True, exist_ok=True)
    (OUT / label / f"{doc_id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str),
                                                encoding="utf-8")
    return result


def _rows(result: dict, subset: str | None = None) -> list[dict]:
    """One metrics row per page (the aggregate table counts pages)."""
    return [{
        "page_type": "digital",
        "char_edits": p["cer"]["char_edits"], "chars": p["cer"]["chars"],
        "word_edits": p["cer"]["word_edits"], "words": p["cer"]["words"],
        "numbers": p["numbers"]["unflagged_total"], "numbers_correct": p["numbers"]["unflagged_correct"],
        "silent_errors": p["numbers"]["silent_errors"], "silent_drops": p["numbers"]["silent_drops"],
    } for p in result["pages"] if subset is None or p["subset"] == subset]


def write_reports(results: list[dict], label: str, *, write_review: bool = True) -> None:
    lines = [f"# Step 4b.2 — {label}: إعادة قياس القراءة الرقمية", "",
             "القواعد والـ thresholds في `docs/reading_eval_rules.md` و`eval/reading/thresholds.json` ومتجمّدين قبل "
             "الـ run. الـ reader هو `matn_reading`، والـ reference المستقل PyMuPDF (eval بس).", "",
             "## dev-tune (70%)", "",
             markdown_table(aggregate(row for result in results for row in _rows(result, "dev_tune"))), "",
             "## dev-check (30%)", "",
             markdown_table(aggregate(row for result in results for row in _rows(result, "dev_check"))), "",
             "- `synthetic_scan`: مفيش gate قبل Step 4c.",
             "- `real_scan`: GAO 1990 لسه pending؛ أي ملف لازم يعدّي sha256 verifier الأول.",
             "- `reading_order` و`block_type`: مستنيين confirmation البصري للصفحات العشرة.", "",
             "## بالتفصيل لكل مستند ولكل subset", "",
             "| subset | doc | pages | numbers | correct | silent errors | silent drops | flagged | inserted | line CER | old block CER | line WER | figure blocks |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for subset in ("dev_tune", "dev_check"):
        for result in results:
            pages = [page for page in result["pages"] if page["subset"] == subset]
            total = lambda key: sum(page["numbers"][key] for page in pages)  # noqa: E731
            line = lambda key: sum(page["cer"][key] for page in pages)  # noqa: E731
            old = lambda key: sum(page["legacy_block_cer"][key] for page in pages)  # noqa: E731
            figures = sum(1 for page in pages for block in page["blocks"] if block["type"] == "figure")
            lines.append(f"| {subset} | {result['doc_id']} | {len(pages)} | {total('unflagged_total')} | "
                         f"{total('unflagged_correct')} | {total('silent_errors')} | {total('silent_drops')} | "
                         f"{total('flagged_total')} | {total('inserted')} | "
                         f"{line('char_edits') / max(line('chars'), 1):.4f} | "
                         f"{old('char_edits') / max(old('chars'), 1):.4f} | "
                         f"{line('word_edits') / max(line('words'), 1):.4f} | {figures} |")
    lines += ["", "## Visibility والـ edge cases", "",
              "| doc | hidden blocks | uncertain blocks | outside CropBox chars | near-zero chars |",
              "|---|---|---|---|---|"]
    for r in results:
        e = lambda key: sum(p["edge_cases"][key] for p in r["pages"])  # noqa: E731
        hidden = sum(block["visibility"] == "hidden" for page in r["pages"] for block in page["blocks"])
        uncertain = sum(block["visibility"] == "uncertain" for page in r["pages"] for block in page["blocks"])
        lines.append(f"| {r['doc_id']} | {hidden} | {uncertain} | {e('outside_cropbox')} | {e('near_zero_font')} |")
    lines += ["", "الصفحات اللي فيها edge cases:", ""]
    for r in results:
        hits = [f"p{p['page_index']} {p['edge_cases']}" for p in r["pages"] if any(p["edge_cases"].values())]
        lines.append(f"- {r['doc_id']}: " + ("; ".join(hits) if hits else "none"))
    lines += ["", "## مشاكل الأرقام (أول 40 لكل مستند؛ الباقي في JSON)", ""]
    for r in results:
        problems = [(p["page_index"], d) for p in r["pages"] for d in p["number_problems"]]
        lines.append(f"### {r['doc_id']}: {len(problems)} مشكلة")
        lines.append("")
        for page_index, d in problems[:40]:
            where = [round(v, 1) for v in d["where"]] if isinstance(d["where"], (list, tuple)) else d["where"]
            lines.append(f"- p{page_index} {d['status']}: expected `{d['expected']}` got `{d['got']}` "
                         f"flagged={d['flagged']} at {where}")
        lines.append("")
    lines += ["## Triage", "", "كل صفحة ليها route وسبب. الصفحات غير `digital_healthy`:", ""]
    for r in results:
        for p in r["pages"]:
            if p["route"] != "digital_healthy":
                lines.append(f"- {r['doc_id']} p{p['page_index']}: **{p['route']}**: {p['reasons'][0]}")
    missing_reasons = sum(1 for r in results for p in r["pages"] if not p["reasons"])
    lines += ["", f"صفحات من غير سبب متسجل: {missing_reasons}.", ""]
    (REPO / "reports" / f"step4-{label}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if not write_review:
        return
    review = ["# Step 4b review: 10 pages for the owner to confirm", "",
              "For each page: open the overlay, then check the reading order and the block type of every block. "
              "Write corrections inline (e.g. `-> heading`, `-> move after 5`) and set **Confirmed** to yes. These "
              "pages become the reading-order and block-type ground truth (rules section 3).", ""]
    by_id = {r["doc_id"]: r for r in results}
    for doc_id, indices in REVIEW_PAGES.items():
        for index in indices:
            page = next(page for page in by_id[doc_id]["pages"] if page["page_index"] == index)
            review += [f"## {doc_id} p{index} (route: {page['route']})", "",
                       f"Overlay: `out/reading/overlays/{doc_id}/p{index:04d}.png`", "", "Confirmed: no", ""]
            for b in page["blocks"]:
                snippet = " ".join(b["text"].split())[:90].replace("|", "/")
                review.append(f"{b['order']}. [{b['type']}{' !' if b['flagged'] else ''}] {snippet}")
            review.append("")
    (REPO / "reports" / "step4-reading-review.md").write_text("\n".join(review) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--no-overlays", action="store_true")
    parser.add_argument("--report-only", action="store_true", help="rebuild the reports from out/reading/<label>/")
    parser.add_argument("--subset", choices=("all", "dev_tune", "dev_check"), default="all")
    args = parser.parse_args()
    if args.report_only:
        results = [json.loads((OUT / args.label / f"{doc_id}.json").read_text(encoding="utf-8"))
                   for doc_id, _ in dev_documents()]
    else:
        results = [measure(doc_id, path, args.label, not args.no_overlays, args.subset)
                   for doc_id, path in dev_documents()]
    write_reports(results, args.label, write_review=args.subset == "all")
    for r in results:
        print(r["doc_id"], len(r["pages"]), "pages", r["seconds"], "s")


if __name__ == "__main__":
    main()
