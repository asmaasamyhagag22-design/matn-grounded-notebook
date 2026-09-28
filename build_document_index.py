"""Build a Phase 02 canonical document store."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from document_store import build_document_store
from inspect_pdf import InspectionError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a local Matn Phase 02 document index.")
    parser.add_argument("--pdf", required=True, type=Path, help="Original PDF (read-only evidence)")
    parser.add_argument("--raw-run", required=True, type=Path, help="Completed Phase 01 raw run")
    parser.add_argument("--structured-run", required=True, type=Path, help="Completed Phase 01 structured run")
    parser.add_argument("--manual-corrections", type=Path, help="Optional reviewed correction JSON")
    parser.add_argument("--out", required=True, type=Path, help="New output directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = build_document_store(
            args.pdf,
            args.raw_run,
            args.structured_run,
            args.out,
            manual_corrections=args.manual_corrections,
        )
    except (InspectionError, OSError, ValueError, KeyError) as exc:
        print(f"error: {type(exc).__name__}: {exc}; no final document store was published.", file=sys.stderr)
        return 2
    print(
        f"Published document store: pages={len(store['pages'])}; "
        f"chunks={len(store['chunks'])}; sections={len(store['sections'])}; "
        f"outline_present={store['outline']['present']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

