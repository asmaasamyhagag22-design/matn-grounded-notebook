"""Per-page text extraction for the evaluation set.

Library: PyMuPDF (import name `pymupdf`), the PDF library already installed in .venv. Its license (installed METADATA)
is "Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License". Nothing else is installed or downloaded.

Text is taken with page.get_text("text") (installed pymupdf/utils.py:459-466: option="text", sort=False, i.e. content
stream order). Output: <root>/pages/<doc_id>/pNNNN.txt (0-based page index, UTF-8). eval/pages/ is git-ignored;
the sha256 of every page file is pinned in registry.json.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def page_file(root: Path, doc_id: str, page_index: int) -> Path:
    return root / "pages" / doc_id / f"p{page_index:04d}.txt"


def extract(pdf_path: Path, root: Path, doc_id: str) -> dict:
    """Write one text file per page; return page count, labels, text-layer flags and page-text hashes."""
    out_dir = root / "pages" / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    labels, hashes, without_text = [], [], []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            text = page.get_text("text")
            data = text.encode("utf-8")
            page_file(root, doc_id, page.number).write_bytes(data)
            hashes.append(sha256_bytes(data))
            labels.append(page.get_label())  # "" when the PDF defines no /PageLabels (pymupdf/__init__.py:11971-11975)
            if not text.strip():
                without_text.append(page.number)
        return {"page_count": doc.page_count, "page_labels": labels, "page_text_sha256": hashes,
                "pages_without_text": without_text}
