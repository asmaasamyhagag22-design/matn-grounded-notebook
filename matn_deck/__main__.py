"""Verifiable decks from saved results (deck v2). Zero model calls, zero network.

  python -m matn_deck from-result RESULT_FOLDER [--template ID] [--fonts template|office] [--out DIR]
  python -m matn_deck from-notebook NOTEBOOK.db --storyboard FOLDER [--reading 00_reading.json ...] [--pdf-source PDF ...]
  python -m matn_deck from-json FILE.json
  python -m matn_deck preflight
  python -m matn_deck gallery DECKS_FOLDER

Common options: --detail summary|standard|detailed, --target-slides N, --audience TEXT, --date YYYY-MM-DD,
--no-pdf. Outputs: deck.pptx, deck.pdf, thumbs/, contact-sheet.png, deck_qa.json, deck_qa.html, storyboard.json,
catalog.json, deck-manifest.json.
"""
from __future__ import annotations

import argparse
from datetime import date
from html import escape
import json
from pathlib import Path
import sys

DEFAULT_ROOT = Path("out/deck-v2")


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--template", help="gallery template id (default: the owner's default)")
    parser.add_argument("--fonts", default="office", choices=("template", "office"),
                        help="office: declare Calibri/Arial/Times New Roman, measure with metric twins (ADR-0020)")
    parser.add_argument("--detail", default="standard", choices=("summary", "standard", "detailed"))
    parser.add_argument("--target-slides", type=int)
    parser.add_argument("--audience")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--out", help="output folder (default: out/deck-v2/<name>)")
    parser.add_argument("--no-pdf", action="store_true", help="skip LibreOffice export and the PDF gates")


def _make(catalog, name: str, args: argparse.Namespace) -> int:
    from .make_deck import make_deck
    from .storyboard_v2 import Controls
    from .templates import GALLERY_DIR, default_template_id
    template = GALLERY_DIR / (args.template or default_template_id()) / "template.pptx"
    out = Path(args.out) if args.out else DEFAULT_ROOT / name
    controls = Controls(detail=args.detail, target_slides=args.target_slides, audience=args.audience, date=args.date)
    qa = make_deck(catalog, template, out, controls=controls, fonts=args.fonts, pdf=not args.no_pdf, label=name)
    failed = [g for g, v in qa["gates"].items() if not v["pass"]]
    print(json.dumps({"deck": str(out / "deck.pptx"), "pdf": str(out / "deck.pdf") if not args.no_pdf else None,
                      "qa": qa["status"], "failed_gates": failed, "delivery": qa["delivery"]["status"],
                      "report": str(out / "deck_qa.html")}, indent=1))
    return 0 if qa["status"] == "QA_PASS" else 3


def gallery(root: Path) -> Path:
    """An offline page listing every deck under `root` with its PDF, PPTX, contact sheet and QA report."""
    rows = []
    for qa_path in sorted(Path(root).glob("*/deck_qa.json")):
        folder = qa_path.parent
        qa = json.loads(qa_path.read_bytes())
        catalog = json.loads((folder / "catalog.json").read_bytes())
        links = " · ".join(f"<a href='{escape(folder.name)}/{name}'>{label}</a>"
                           for name, label in (("deck.pdf", "PDF"), ("deck.pptx", "PPTX"),
                                               ("deck_qa.html", "QA report"), ("contact-sheet.png", "contact sheet"))
                           if (folder / name).exists())
        sheet = (f"<img src='{escape(folder.name)}/contact-sheet.png' alt='contact sheet of {escape(folder.name)}'>"
                 if (folder / "contact-sheet.png").exists() else "")
        rows.append(f"<section><h2>{escape(folder.name)} — {escape(catalog['plan']['topic'])}</h2>"
                    f"<p><b>{escape(qa['status'])}</b> · {qa['slides']} slides · fonts {escape(str(qa['fonts']))} · "
                    f"{escape(qa['delivery']['status'])}</p><p>{links}</p>{sheet}</section>")
    page = ("<!doctype html><html lang='en'><meta charset='utf-8'><title>Matn decks</title><style>"
            "body{font-family:sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#183342}"
            "img{max-width:100%;border:1px solid #9aa7b0}section{margin:28px 0}</style>"
            "<h1>Matn · verifiable decks (offline)</h1>" + "".join(rows) + "</html>")
    out = Path(root) / "index.html"
    out.write_text(page, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m matn_deck", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    result = sub.add_parser("from-result", help="a Topic→Research result folder")
    result.add_argument("folder")
    _common(result)
    notebook = sub.add_parser("from-notebook", help="the document path: a storyboard over a notebook")
    notebook.add_argument("notebook")
    notebook.add_argument("--storyboard", required=True, help="storyboard folder whose input.json names the notebook")
    notebook.add_argument("--version", help="saved version file (default: the newest v<N>.json)")
    notebook.add_argument("--reading", action="append", default=[], help="reader page cache (00_reading.json)")
    notebook.add_argument("--pdf-source", action="append", default=[], help="original PDF (sha256 = doc_id)")
    _common(notebook)
    from_json = sub.add_parser("from-json", help="a saved catalog or a JSON source bundle")
    from_json.add_argument("file")
    _common(from_json)
    check = sub.add_parser("preflight", help="LibreOffice, fonts and readers ready for export")
    check.add_argument("--fonts", default="office", choices=("template", "office"))
    listing = sub.add_parser("gallery", help="write an offline index.html of the decks in a folder")
    listing.add_argument("folder", nargs="?", default=str(DEFAULT_ROOT))
    args = parser.parse_args(argv)

    from . import catalog_adapters as adapters
    if args.command == "preflight":
        from .export_v2 import preflight
        report = preflight(args.fonts)
        print(json.dumps(report, indent=1))
        return 0 if report["go"] else 2
    if args.command == "gallery":
        print(gallery(Path(args.folder)))
        return 0
    if args.command == "from-result":
        folder = Path(args.folder)
        return _make(adapters.from_research(folder), folder.name, args)
    if args.command == "from-notebook":
        catalog = adapters.from_storyboard(Path(args.storyboard), notebook=Path(args.notebook),
                                           version=Path(args.version) if args.version else None,
                                           readings=[Path(p) for p in args.reading],
                                           pdfs=[Path(p) for p in args.pdf_source])
        return _make(catalog, Path(args.storyboard).name, args)
    if args.command == "from-json":
        return _make(adapters.from_json(Path(args.file)), Path(args.file).stem, args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
