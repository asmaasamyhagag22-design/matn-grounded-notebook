"""One-command reader for the owner: ``python -m matn_reading read <pdf> --out <folder> [--milestone]``.

Triage every page, read digital pages from the text layer and scanned pages with the OCR route, then write:
reading.md (text in reading order, [p. N] markers, flagged items inline as ⚠[...], hidden and figure text listed at
the end), blocks.jsonl (contract Blocks), report.md (one screen, Egyptian Arabic) and overlays/ (one PNG per page).
Fully offline: the whole run is inside ``block_egress()`` (GLM-OCR stays on 127.0.0.1). A file whose sha256 is a
test-split document in eval/registry.json is refused unless ``--milestone`` is given.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from checks.egress_guard import block_egress
from matn_contracts.enums import Visibility

from .overlay import draw_overlay, draw_scan_overlay
from .pdf_page import OpenPdf, render_page
from .read import PageReading, read_document
from .triage import Route

REPO = Path(__file__).resolve().parents[1]
OCR_ROUTES = (Route.SCANNED, Route.SCANNED_WITH_OCR_LAYER)
OVERLAY_SCALE = 1.5
EXIT_REFUSED = 3


class RefusedTestSplit(Exception):
    pass


def test_split_hashes() -> set[str]:
    registry = json.loads((REPO / "eval" / "registry.json").read_text(encoding="utf-8"))
    return {doc["sha256"] for doc in registry["documents"] if doc.get("split") == "test"}


def _flag_text(token: dict) -> str:
    reasons = token["reasons"]
    if "readers_disagree" in reasons:
        return f"⚠[uncertain number: {token['token']} / {token['reader2'] or '—'}]"
    if "second_read_failed" in reasons:
        return f"⚠[uncertain number: {token['token']} / no second read]"
    if "ocr_layer_disagreement" in reasons:
        return f"⚠[uncertain number: {token['token']} / OCR layer differs]"
    if "low_confidence" in reasons:
        return f"⚠[low-confidence number: {token['token']}]"
    return f"⚠[check failed ({', '.join(reasons)}): {token['token']}]"


def _inside(box, outer) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return outer[0] - 0.5 <= cx <= outer[2] + 0.5 and outer[1] - 0.5 <= cy <= outer[3] + 0.5


def _block_text(page: PageReading, block) -> str:
    text = block.layout.text
    if page.ocr is None:
        kinds = sorted({f["kind"] for f in page.flags if f.get("bbox") == block.layout.bbox})
        return (f"⚠[flagged: {', '.join(kinds) or block.block_type}] " if block.flagged else "") + text
    cursor, out = 0, []
    for token in sorted((t for t in page.ocr["tokens"] if t["flagged"] and _inside(t["bbox"], block.layout.bbox)),
                        key=lambda t: (t["bbox"][1], t["bbox"][0])):
        found = text.find(token["token"], cursor)
        if found < 0:
            out.append(text[cursor:] + " " + _flag_text(token))
            cursor = len(text)
            continue
        out.append(text[cursor:found] + _flag_text(token))
        cursor = found + len(token["token"])
    return "".join(out) + text[cursor:]


PREFIX = {"heading": "### ", "list_item": "- ", "caption": "_", "footnote": "> "}


def write_reading(pages: list[PageReading], name: str, path: Path) -> None:
    lines, outside = [f"# {name}", ""], []
    for page in pages:
        n = page.page_index + 1
        label = f" (printed {page.page_label})" if page.page_label else ""
        lines += ["---", "", f"**[p. {n}]**{label} · route `{page.route.value}`", ""]
        if page.route not in (Route.DIGITAL_HEALTHY,) and page.ocr is None:
            lines += [f"⚠[page not clean: {page.route.value}]", ""]
        if any(f["kind"] == "ocr_no_text" for f in page.flags):
            lines += ["⚠[OCR found no text on an inked page]", ""]
        if any(f["kind"] == "ocr_unavailable" for f in page.flags):
            lines += ["⚠[scanned page, OCR not available on this machine: no text read]", ""]
        for block in page.blocks:
            visible = block.contract.visibility is Visibility.VISIBLE
            if not visible or block.block_type == "figure":
                why = "figure" if visible else f"{block.contract.visibility.value}: " + ", ".join(
                    r.value for r in block.contract.visibility_reasons)
                outside.append(f"- [p. {n}] ({why}) {block.layout.text}")
                continue
            if block.block_type in ("header", "footer"):
                continue
            prefix = PREFIX.get(block.block_type, "")
            suffix = "_" if block.block_type == "caption" else ""
            lines += [f"{prefix}{_block_text(page, block)}{suffix} [p. {n}]", ""]
    lines += ["<!-- end of prose -->", "", "## خارج النص: نص مخفي أو داخل figures", ""]
    lines += outside or ["- مفيش."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _numbers(page: PageReading) -> tuple[int, int]:
    if page.ocr is not None:
        tokens = page.ocr["tokens"]
        return len(tokens), sum(t["flagged"] for t in tokens)
    from .ocr.numbers import number_tokens

    total = flagged = 0
    for block in page.blocks:
        if block.contract.visibility is not Visibility.VISIBLE:
            continue
        count = len(number_tokens(block.layout.text))
        total += count
        flagged += count if block.flagged or block.block_type == "figure" else 0
    return total, flagged


def write_report(pages: list[PageReading], name: str, seconds: float, ocr_seconds: float, path: Path) -> dict:
    routes: dict[str, list[int]] = {}
    for page in pages:
        routes.setdefault(page.route.value, []).append(page.page_index + 1)
    counts = [_numbers(page) for page in pages]
    total, flagged = sum(c[0] for c in counts), sum(c[1] for c in counts)
    hidden = [(page.page_index + 1, f) for page in pages for f in page.flags if f["kind"] == "hidden_text"]
    outside = [(page.page_index + 1, f["chars"]) for page in pages for f in page.flags if f["kind"] == "outside_cropbox"]
    ocr = [page for page in pages if page.ocr is not None]
    lines = [f"# تقرير القراءة: {name}", "",
             "## الصفحات حسب الـ route", ""] + [f"- `{route}`: {len(p)} صفحة ({_pages(p)})" for route, p in routes.items()]
    lines += ["", "## الأرقام", "", f"- إجمالي الأرقام في النص: **{total}**؛ عليها علامة ⚠ أو في منطقة متعلّمة: "
              f"**{flagged}** ({flagged / total:.0%})." if total else "- مفيش أرقام."]
    lines += ["", "## تحذيرات النص المخفي", ""]
    if hidden or outside:
        lines += [f"- p. {n}: {f['visibility']} ({', '.join(f['reasons'])}), {f['chars']} حرف، "
                  f"severity {f['severity']}" for n, f in hidden[:15]]
        lines += [f"- p. {n}: {chars} حرف برّه الـ CropBox (warning)" for n, chars in outside]
        if len(hidden) > 15:
            lines.append(f"- … و{len(hidden) - 15} تحذير تاني (التفاصيل في blocks.jsonl).")
    else:
        lines.append("- مفيش نص مخفي.")
    lines += ["", "## صفحات الـ OCR", ""]
    if ocr:
        lines += ["| page | route | mean confidence | أرقام | flagged | second reads |", "|---:|---|---:|---:|---:|---:|"]
        lines += [f"| {p.page_index + 1} | {p.route.value} | {p.ocr['mean_confidence']} | {len(p.ocr['tokens'])} | "
                  f"{sum(t['flagged'] for t in p.ocr['tokens'])} | {p.ocr['second_reads']['lines']} |" for p in ocr]
    elif any(f["kind"] == "ocr_unavailable" for p in pages for f in p.flags):
        lines.append("- فيه صفحات ممسوحة بس الـ OCR مش متاح على الجهاز ده، فما اتقريتش (متعلّمة ⚠).")
    else:
        lines.append("- مفيش صفحات ممسوحة.")
    lines += ["", "## الوقت", "", f"- الإجمالي: {seconds:.1f} ثانية ({seconds / max(len(pages), 1):.1f} للصفحة)"
              + (f"؛ منهم OCR {ocr_seconds:.1f} ثانية." if ocr else ".")]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"routes": routes, "numbers_total": total, "numbers_flagged": flagged, "hidden_warnings": len(hidden)}


def _pages(numbers: list[int]) -> str:
    return ", ".join(str(n) for n in numbers[:20]) + (" …" if len(numbers) > 20 else "")


def run(pdf: Path, out: Path, *, milestone: bool = False, worker_factory=None, glm=None, ocr_config=None) -> dict:
    pdf, out = Path(pdf), Path(out)
    if hashlib.sha256(pdf.read_bytes()).hexdigest() in test_split_hashes() and not milestone:
        raise RefusedTestSplit(f"{pdf.name} is a sealed test-split document; use --milestone only at a milestone")
    started = time.perf_counter()
    out.mkdir(parents=True, exist_ok=True)
    ocr_seconds = 0.0
    with block_egress():
        reading = read_document(pdf)
        pages = list(reading.pages)
        scanned = [i for i, page in enumerate(pages) if page.route in OCR_ROUTES]
        processed_images = {}
        if scanned:
            ocr_started = time.perf_counter()
            from .ocr.glm import GlmReader
            from .ocr.preprocess import preprocess, render_page_image
            from .ocr.reader1 import RapidOcrWorker, WorkerError
            from .ocr.route import OcrConfig, read_scan_page

            config = ocr_config or OcrConfig()
            try:
                with (worker_factory or RapidOcrWorker)() as worker, OpenPdf(pdf) as opened:
                    reader2 = glm if glm is not None else GlmReader()
                    for i in scanned:
                        page = pages[i]
                        layer = [(w.text, (w.x0, w.top, w.x1, w.bottom)) for w in opened.page(page.page_index).words] \
                            if page.route is Route.SCANNED_WITH_OCR_LAYER else []
                        image = render_page_image(pdf, page.page_index, config.dpi)
                        pages[i] = read_scan_page(image, page_index=page.page_index, page_label=page.page_label,
                                                  cropbox=page.cropbox, route=page.route, reasons=page.reasons,
                                                  doc_id=reading.doc_id, worker=worker, glm=reader2, config=config,
                                                  crop_dir=out, text_layer=layer)
                        processed_images[i] = preprocess(image, config.preprocess)[0]
            except WorkerError as error:
                for i in scanned:
                    pages[i].flags.append({"kind": "ocr_unavailable", "bbox": (0.0, 0.0, pages[i].width,
                                                                               pages[i].height), "error": str(error)})
            ocr_seconds = time.perf_counter() - ocr_started
        from .ocr.regions import repeat_furniture
        repeat_furniture(pages)
        (out / "blocks.jsonl").write_text("".join(block.contract.model_dump_json() + "\n" for page in pages
                                                  for block in page.blocks), encoding="utf-8")
        write_reading(pages, pdf.name, out / "reading.md")
        overlays = out / "overlays"
        overlays.mkdir(exist_ok=True)
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(str(pdf))
        try:
            for i, page in enumerate(pages):
                target = overlays / f"p{page.page_index:04d}.png"
                if i in processed_images:
                    draw_scan_overlay(page, processed_images[i], 300).save(target, optimize=True)
                else:
                    image = render_page(document[page.page_index], OVERLAY_SCALE)
                    draw_overlay(page, image, OVERLAY_SCALE, (page.cropbox[0], page.cropbox[1])).save(target, optimize=True)
        finally:
            document.close()
    seconds = time.perf_counter() - started
    summary = write_report(pages, pdf.name, seconds, ocr_seconds, out / "report.md")
    summary["ocr_pages"] = [pages[i].page_index for i in scanned if pages[i].ocr is not None]
    summary["ocr_failed_pages"] = [p.page_index for p in pages if any(f["kind"] == "ocr_unavailable" for f in p.flags)]
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m matn_reading", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    read = sub.add_parser("read", help="read one PDF into reading.md, blocks.jsonl, report.md and overlays/")
    read.add_argument("pdf", type=Path)
    read.add_argument("--out", type=Path, required=True)
    read.add_argument("--milestone", action="store_true", help="allow a sealed test-split file (milestones only)")
    args = parser.parse_args(argv)
    try:
        summary = run(args.pdf, args.out, milestone=args.milestone)
    except RefusedTestSplit as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return EXIT_REFUSED
    out = args.out.resolve()
    incomplete = bool(summary.get("ocr_failed_pages"))
    print(f"{'Incomplete' if incomplete else 'Done'}. Outputs in {out}")
    for name in ("reading.md", "blocks.jsonl", "report.md", "overlays"):
        print(f"  {out / name}")
    return 2 if incomplete else 0
