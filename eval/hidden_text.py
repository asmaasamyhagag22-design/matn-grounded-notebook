"""Hidden text: text in a PDF's text layer that a reader cannot see, because something opaque is drawn over it.

PyMuPDF's page.get_text() returns such text too, so a quote can verify against the text layer without being
visible on the page (Step 0: an older executive summary under a later layer in one evaluation document). This is a
fidelity problem and a prompt-injection vector, not only an evaluation issue.

Method (eval tooling, PyMuPDF per ADR-0001): page.get_bboxlog() lists every drawing operation in painting order.
A text span is hidden when its centre lies inside the box of an operation painted LATER:
  image   a "fill-image" box: reliable (an opaque picture over text); verify_gold treats a quote in it as an error;
  vector  a "fill-path" / "fill-shade" box (and no later image): noisier, since a path's box can be larger than its
          shape and fills can be transparent; verify_gold treats a quote in it as a warning.
Each span is matched to the first text operation whose box contains its centre. Output is text for comparison by
the caller; callers report codes and counts only (standing rule 8).
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

IMAGE_KINDS = {"fill-image"}
VECTOR_KINDS = {"fill-path", "fill-shade"}


def _centre(rect: pymupdf.Rect) -> pymupdf.Point:
    return pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)


def hidden_spans(page: pymupdf.Page) -> dict[str, list[str]]:
    """Text of the spans covered by a later image ("image") or a later vector fill only ("vector")."""
    log = [(kind, pymupdf.Rect(box)) for kind, box in page.get_bboxlog()]
    covers = [(i, kind, box) for i, (kind, box) in enumerate(log) if kind in IMAGE_KINDS | VECTOR_KINDS]
    found: dict[str, list[str]] = {"image": [], "vector": []}
    if not covers:
        return found
    text_ops = [(i, box) for i, (kind, box) in enumerate(log) if kind.endswith("-text")]
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                centre = _centre(pymupdf.Rect(span["bbox"]))
                op = next((i for i, box in text_ops if box.contains(centre)), None)
                if op is None:
                    continue
                later = {kind for i, kind, box in covers if i > op and box.contains(centre)}
                text = "".join(ch["c"] for ch in span["chars"])
                if later & IMAGE_KINDS:
                    found["image"].append(text)
                elif later & VECTOR_KINDS:
                    found["vector"].append(text)
    return found


def hidden_text(pdf: Path, pages: set[int] | None = None) -> dict[int, dict[str, str]]:
    """{page index: {"image": text, "vector": text}} for the requested pages (all pages when None)."""
    out = {}
    with pymupdf.open(pdf) as doc:
        for page in doc:
            if pages is not None and page.number not in pages:
                continue
            spans = hidden_spans(page)
            out[page.number] = {kind: " ".join(texts) for kind, texts in spans.items()}
    return out
