"""Tiny hand-written PDFs for reading tests (no PDF library needed to build them)."""
from __future__ import annotations

from pathlib import Path


def write_pdf(path: Path, content: bytes, *, mediabox=(0, 0, 612, 792), cropbox=None, extra_resources=b"",
              extra_objects: tuple[bytes, ...] = ()) -> Path:
    crop = b"" if cropbox is None else b" /CropBox [%d %d %d %d]" % tuple(cropbox)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [%d %d %d %d]" % tuple(mediabox) + crop
        + b" /Resources << /Font << /F1 5 0 R /F2 6 0 R >> " + extra_resources + b">> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        *extra_objects,
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    path.write_bytes(out)
    return path


EDGE_CASES = b"""BT 0 Tr /F1 12 Tf 72 650 Td (Visible 111) Tj ET
BT 3 Tr /F1 12 Tf 72 600 Td (Invisible 222) Tj ET
BT 0 Tr /F1 12 Tf 72 750 Td (OutsideCrop 333) Tj ET
BT 0 Tr /F1 0.01 Tf 72 550 Td (TinyFont 444) Tj ET
BT 0 Tr /F1 12 Tf 700 300 Td (OffPage 555) Tj ET
"""
