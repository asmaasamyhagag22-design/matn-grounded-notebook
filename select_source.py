"""List indexed sections or create a page/section-scoped source selection."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from document_store import read_json, select_source
from inspect_pdf import InspectionError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Select evidence from a Matn document store.")
    parser.add_argument("--document-store", required=True, type=Path)
    selectors = parser.add_mutually_exclusive_group(required=True)
    selectors.add_argument("--list-sections", action="store_true")
    selectors.add_argument("--pages", help="1-based PDF pages, e.g. 2-5,8")
    selectors.add_argument("--sections", help="Comma-separated explicit section IDs")
    parser.add_argument("--allow-unconfirmed", action="store_true")
    parser.add_argument("--out", type=Path, help="Selection JSON output; required for selection")
    return parser


def _store_path(path: Path) -> Path:
    return path / "document-store.json" if path.is_dir() else path


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = read_json(_store_path(args.document_store))
        if args.list_sections:
            print("section_id\tlevel\tpages\tstatus\ttitle")
            for section in store["sections"]:
                print(
                    f"{section['section_id']}\t{section['level']}\t"
                    f"{section['first_pdf_page']}-{section['last_pdf_page']}\t"
                    f"{section['confirmation_status']}\t{section['title']}"
                )
            return 0
        if args.out is None:
            raise ValueError("--out is required so source content is not printed to logs")
        if args.out.exists():
            raise ValueError("output path already exists; refusing to overwrite")
        section_ids = [item.strip() for item in args.sections.split(",")] if args.sections else None
        selection = select_source(
            store,
            pages=args.pages,
            section_ids=section_ids,
            allow_unconfirmed=args.allow_unconfirmed,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.out.with_name(args.out.name + ".tmp")
        temporary.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(args.out)
        print(
            f"Published {selection['selection_scope']} selection: "
            f"chunks={len(selection['included_chunk_ids'])}; "
            f"pdf_pages={selection['resolved_pdf_pages']}; "
            f"confirmation={selection['confirmation_status']}"
        )
        return 0
    except (InspectionError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
