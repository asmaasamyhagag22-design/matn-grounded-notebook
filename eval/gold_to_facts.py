"""Demo adapter: dev gold -> contract Facts, page-level Blocks and pre-rendered page images (overnight demo, Part 1).

The demo decks are built from the verified reference (silver gold) of the three DEV documents, not from the model
pipeline (Steps 3-9 are not built yet). This file turns that reference into the Step 1 contracts so the renderer and
the dashboard can use real content with honest provenance:

- Block: one per cited page, page-level (bbox = the whole page, text = PyMuPDF page text). It does not pretend to
  know the paragraph; the quote's position on the page is located separately for the receipt images.
- Fact: one per key point (kind and importance from the gold) and one number fact per key number. The statement of a
  number fact is built by code ("<label>: <value as written>"); the value is copied from the gold, never typed.
- Status: VERIFIED only when the quote is on its page exactly once (same normalization as verify_gold.py), every
  number in the statement is in the quote, the number value is a whole token of the quote, and no image covers the
  quote. Otherwise REJECTED with its reasons (the planner never cites a rejected fact).
- Tables: a table is kept only when PyMuPDF finds a clean one on a page a number fact cites (header row, at least 3
  data rows, a text first column, a fully numeric column, and the cited value in a cell). No table -> no chart.
- Images: every cited page is rendered whole with the quote highlighted, plus a crop around the quote, into
  out/demo/pages/<doc_key>/. The dashboard shows these PNGs, so dashboard code never imports PyMuPDF.

PyMuPDF (AGPL) is allowed here because this is eval tooling (ADR-0001). The TEST split is never read: the document
list below is fixed to dev gold files, and each one's registry entry must say split "dev".

Usage: .venv\\Scripts\\python.exe eval/gold_to_facts.py   (writes out/demo/facts/<doc_key>.json and the PNGs)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from importlib.metadata import metadata
from pathlib import Path

import pymupdf

EVAL_DIR = Path(__file__).resolve().parent
REPO = EVAL_DIR.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(EVAL_DIR))

from hidden_text import hidden_spans  # noqa: E402
from normalize import count_on_page, normalize_text, value_in_quote  # noqa: E402
from matn_contracts.domain import Block, BlockStyle, EvidenceRef, ExtractorInfo, Fact, NumberFactValue, Table, TableCell  # noqa: E402
from matn_contracts.enums import BlockType, ExtractionRoute, FactKind, FactStatus, Importance, RejectReason, Visibility  # noqa: E402

# Gold doc_id -> demo key (the PDF file stem). Dev documents only; the test split stays sealed.
DEMO_DOCS = {"wb-eem-2021-12": "wb_eem_2021_12", "gao-21-519sp": "gao_21_519sp", "2601-14525v1": "2601.14525v1"}
OUT = REPO / "out" / "demo"
PAGE_ZOOM = 1.5
CROP_ZOOM = 2.0
HIGHLIGHT = (1.0, 0.85, 0.2)
NO_DISPLAY_UNITS = {"count", "year"}


class AdapterError(RuntimeError):
    pass


def display_unit(value: str, unit: str | None) -> str | None:
    """The unit shown after a value: none for counts and years, none when the value already carries it ("69.4%")."""
    if unit is None or unit in NO_DISPLAY_UNITS:
        return None
    if value.rstrip().endswith(unit):
        return None
    return unit


def number_statement(label: str, value: str, unit: str | None) -> str:
    shown = display_unit(value, unit)
    if shown is None:
        return f"{label}: {value}"
    return f"{label}: {value}{shown}" if shown == "%" else f"{label}: {value} {shown}"


def numbers_in(text: str) -> list[str]:
    return re.findall(r"\d+(?:[.,]\d+)*", text)


def numbers_missing(text: str, quote: str) -> list[str]:
    """Numbers of `text` not printed in `quote` (same rule as verify_gold.numbers_missing)."""
    missing = []
    for number in numbers_in(text):
        pattern = r"(?<!\d)(?<!\d[.,])" + re.escape(number) + r"(?!\d|[.,]\d)"
        if not (re.search(pattern, quote) or re.search(pattern, normalize_text(quote))):
            missing.append(number)
    return missing


def check_item(statement_numbers_text: str, quote: str, page_text: str, hidden_image: str,
               value: str | None = None) -> list[RejectReason]:
    """Why a gold item cannot be a verified fact (empty list = verified)."""
    reasons: list[RejectReason] = []
    if count_on_page(quote, page_text) != 1:
        reasons.append(RejectReason.QUOTE_NOT_FOUND)
    if numbers_missing(statement_numbers_text, quote):
        reasons.append(RejectReason.NUMBER_NOT_IN_EVIDENCE)
    if value is not None and not value_in_quote(value, quote):
        reasons.append(RejectReason.NUMBER_NOT_IN_EVIDENCE)
    if hidden_image and normalize_text(quote)[:60] in normalize_text(hidden_image):
        reasons.append(RejectReason.EVIDENCE_HIDDEN)
    return list(dict.fromkeys(reasons))


def _registry_entry(gold_id: str) -> dict:
    registry = json.loads((EVAL_DIR / "registry.json").read_text(encoding="utf-8"))
    entry = next((d for d in registry["documents"] if d["doc_id"] == gold_id), None)
    if entry is None or entry.get("split") != "dev":
        raise AdapterError(f"NOT_A_DEV_DOCUMENT:{gold_id}")
    return entry


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quote_rects(page: pymupdf.Page, quote: str) -> list[pymupdf.Rect]:
    """Where the quote sits on the page: the whole quote, else its first and last words (line breaks, hyphens)."""
    rects = page.search_for(quote)
    if rects:
        return rects
    words = quote.split()
    found: list[pymupdf.Rect] = []
    for chunk in (" ".join(words[:6]), " ".join(words[-6:])):
        found += page.search_for(chunk) if len(chunk) >= 12 else []
    if len(found) >= 2:  # also mark the lines between the first and last chunk
        top, bottom = min(r.y0 for r in found), max(r.y1 for r in found)
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                box = pymupdf.Rect(line["bbox"])
                if box.y0 >= top - 1 and box.y1 <= bottom + 1 and box.x0 >= min(r.x0 for r in found) - 200:
                    found.append(box)
    return found


def render_page_images(doc: pymupdf.Document, page_index: int, quote: str, out_dir: Path, stem: str) -> dict:
    """Whole page with the quote highlighted, plus a crop around it. The document is never saved."""
    page = doc[page_index]
    rects = quote_rects(page, quote)
    annots = [page.add_highlight_annot(r) for r in rects]
    for annot in annots:
        annot.set_colors(stroke=HIGHLIGHT)
        annot.update()
    out_dir.mkdir(parents=True, exist_ok=True)
    page_png = out_dir / f"p{page_index:04d}_{stem}.png"
    page.get_pixmap(matrix=pymupdf.Matrix(PAGE_ZOOM, PAGE_ZOOM), annots=True).save(str(page_png))
    crop_png = None
    if rects:
        top = max(page.rect.y0, min(r.y0 for r in rects) - 48)
        bottom = min(page.rect.y1, max(r.y1 for r in rects) + 48)
        clip = pymupdf.Rect(page.rect.x0 + 24, top, page.rect.x1 - 24, bottom)
        crop_png = out_dir / f"p{page_index:04d}_{stem}_crop.png"
        page.get_pixmap(matrix=pymupdf.Matrix(CROP_ZOOM, CROP_ZOOM), clip=clip, annots=True).save(str(crop_png))
    for annot in annots:
        page.delete_annot(annot)
    return {"page_png": page_png.relative_to(REPO).as_posix(),
            "crop_png": crop_png.relative_to(REPO).as_posix() if crop_png else None,
            "located": bool(rects)}


_NUMERIC_CELL = re.compile(r"^[-+]?\(?[\d.,]+\)?%?$")


def clean_table(rows: list[list[str | None]]) -> bool:
    """A table a chart may use: header + >= 3 data rows, text first column, at least one fully numeric column."""
    if len(rows) < 4 or any(len(r) != len(rows[0]) for r in rows) or len(rows[0]) < 2:
        return False
    if any(cell is None or not str(cell).strip() for row in rows for cell in row):
        return False
    body = rows[1:]
    if any(_NUMERIC_CELL.match(str(row[0]).strip()) for row in body):
        return False
    return any(all(_NUMERIC_CELL.match(str(row[c]).strip()) for row in body) for c in range(1, len(rows[0])))


def detect_tables(doc: pymupdf.Document, doc_id: str, number_items: list[dict]) -> tuple[list[Table], list[str]]:
    """Clean tables on pages that number facts cite, holding a cited value. Returns tables and a log."""
    tables, log = [], []
    by_page: dict[int, list[str]] = {}
    for item in number_items:
        by_page.setdefault(item["page_index"], []).append(item["value_as_written"])
    for page_index, values in sorted(by_page.items()):
        try:
            found = doc[page_index].find_tables()
        except Exception as exc:  # noqa: BLE001 - table finding is best effort; no table means no chart
            log.append(f"p{page_index}: find_tables failed ({type(exc).__name__})")
            continue
        for table in found.tables:
            rows = table.extract()
            if not clean_table(rows):
                log.append(f"p{page_index}: table at {tuple(round(v) for v in table.bbox)} rejected (not clean)")
                continue
            cells_text = {str(c).strip() for row in rows for c in row}
            if not any(v in cells_text for v in values):
                log.append(f"p{page_index}: clean table rejected (no cited value in its cells)")
                continue
            x0, y0, x1, y1 = table.bbox
            cells = []
            for r, row in enumerate(rows):
                for c, text in enumerate(row):
                    box = table.rows[r].cells[c] or (x0, y0, x1, y1)
                    cells.append(TableCell(row=r, col=c, text=str(text).strip(), bbox=tuple(box), is_header=r == 0))
            tables.append(Table.create(doc_id=doc_id, page_index=page_index, bbox=(x0, y0, x1, y1), header_rows=(0,),
                                       cells=tuple(cells)))
            log.append(f"p{page_index}: clean table kept ({len(rows)} rows)")
    return tables, log


def convert(gold_id: str, *, render_images: bool = True) -> dict:
    doc_key = DEMO_DOCS[gold_id]
    gold_path = EVAL_DIR / "gold" / "dev" / f"{gold_id}.json"
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    if gold.get("split") != "dev":
        raise AdapterError(f"NOT_DEV_GOLD:{gold_id}")
    entry = _registry_entry(gold_id)
    pdf = EVAL_DIR / entry["file"]
    if _sha256(pdf) != gold["source_sha256"]:
        raise AdapterError(f"PDF_SHA_MISMATCH:{gold_id}")
    doc_id = "sha256-" + gold["source_sha256"]
    meta = metadata("pymupdf")
    extractor = ExtractorInfo(name="pymupdf", version=meta["Version"])
    items = gold["key_points"] + gold["key_numbers"]
    pages_dir = OUT / "pages" / doc_key

    blocks: dict[int, Block] = {}
    facts: list[Fact] = []
    receipts: dict[str, dict] = {}
    with pymupdf.open(pdf) as doc:
        hidden: dict[int, dict[str, list[str]]] = {}
        for item in sorted(items, key=lambda i: (i["page_index"], i["id"])):
            index = item["page_index"]
            page = doc[index]
            if index not in blocks:
                text = page.get_text("text")
                blocks[index] = Block.create(
                    doc_id=doc_id, page_index=index, page_label=item["page_label"],
                    bbox=(page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1), block_type=BlockType.TEXT,
                    text=text, reading_order=0, style=BlockStyle(font_size_pt=None, is_bold=None),
                    extractor=extractor, route=ExtractionRoute.TEXT_LAYER, visibility=Visibility.VISIBLE)
                hidden[index] = hidden_spans(page)
            block = blocks[index]
            quote = item["evidence_quote"]
            evidence = (EvidenceRef(block_id=block.block_id, quote=quote, char_start=None, char_end=None),)
            hidden_image = " ".join(hidden[index]["image"])
            if "value_as_written" in item:
                value, unit = item["value_as_written"], item["unit"]
                statement = number_statement(item["label"], value, unit)
                reasons = check_item(value, quote, block.text, hidden_image, value)
                number_value = NumberFactValue(label=item["label"], value_as_written=value,
                                               unit=display_unit(value, unit), page_label=item["page_label"])
                kind, importance = FactKind.NUMBER, Importance.HEADLINE
            else:
                statement = item["text"]
                reasons = check_item(statement, quote, block.text, hidden_image)
                number_value, kind, importance = None, FactKind(item["kind"]), Importance(item["importance"])
            fact = Fact.create(kind=kind, statement=statement, attributed_to=None, evidence=evidence,
                               importance=importance,
                               status=FactStatus.REJECTED if reasons else FactStatus.VERIFIED,
                               reject_reasons=tuple(reasons), number_value=number_value)
            facts.append(fact)
            images = (render_page_images(doc, index, quote, pages_dir, item["id"].rsplit("-", 2)[-2] + item["id"][-2:])
                      if render_images else {"page_png": None, "crop_png": None, "located": None})
            receipts[fact.fact_id] = {
                "gold_id": item["id"], "kind": kind.value, "importance": int(importance),
                "section_path": item.get("section_path") or [], "page_index": index,
                "physical_page": index + 1, "page_label": item["page_label"], "quote": quote,
                "unit_raw": item.get("unit"), "status": fact.status.value,
                "reject_reasons": [r.value for r in reasons],
                "hidden_vector_on_page": bool(hidden[index]["vector"]), **images,
            }
        tables, table_log = detect_tables(doc, doc_id, gold["key_numbers"])

    source = entry["source"]
    return {
        "schema": "matn-demo-facts/1",
        "doc_key": doc_key, "gold_doc_id": gold_id, "doc_id": doc_id, "split": "dev",
        "title": source["title"], "publisher": source["publisher"], "license": source["license"],
        "page_count": entry["page_count"], "body_pages": gold["body_pages"],
        "extractor": extractor.model_dump(mode="json"),
        "blocks": [b.model_dump(mode="json") for b in blocks.values()],
        "facts": [f.model_dump(mode="json") for f in facts],
        "tables": [t.model_dump(mode="json") for t in tables],
        "table_log": table_log,
        "receipts": receipts,
    }


def write(data: dict) -> Path:
    path = OUT / "facts" / f"{data['doc_key']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--doc", choices=sorted(DEMO_DOCS), action="append", help="gold doc_id (default: all three)")
    parser.add_argument("--no-images", action="store_true")
    args = parser.parse_args(argv)
    for gold_id in args.doc or list(DEMO_DOCS):
        data = convert(gold_id, render_images=not args.no_images)
        path = write(data)
        verified = sum(f["status"] == "verified" for f in data["facts"])
        print(f"{data['doc_key']}: {verified}/{len(data['facts'])} facts verified, {len(data['tables'])} tables "
              f"-> {path.relative_to(REPO).as_posix()}")
        for fid, r in data["receipts"].items():
            if r["status"] != "verified" or not r.get("located", True):
                print(f"  {r['gold_id']}: {r['status']} {r['reject_reasons']} located={r.get('located')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
