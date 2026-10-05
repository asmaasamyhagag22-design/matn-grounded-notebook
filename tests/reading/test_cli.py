"""One-command reader for the owner: python -m matn_reading read <pdf> --out <folder>."""
from __future__ import annotations

import hashlib
import json

import pytest

from matn_contracts.domain import Block
from matn_reading import cli
from matn_reading.ocr.glm import GlmRead
from matn_reading.ocr.route import OcrConfig

from .pdf_fixtures import write_pdf

DIGITAL = b"""BT /F2 16 Tf 72 720 Td (Annual results) Tj ET
BT /F1 11 Tf 72 690 Td (Revenue reached 1,240 million in 2020.) Tj ET
BT 3 Tr /F1 11 Tf 72 660 Td (Hidden note 999) Tj ET
"""
IMAGE = (b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8 "
         b"/Length 1 >>\nstream\n\x80\nendstream")


def _quad(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


class FakeWorker:
    """Reads one line 'Staff 1,240' with a doubtful number."""

    def __init__(self):
        self.ready = {"ready": True}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def read(self, path):
        words = [{"text": "Staff", "score": 0.99, "box": _quad(300, 400, 420, 440)},
                 {"text": "1,240", "score": 0.70, "box": _quad(440, 400, 560, 440)}]
        return {"ok": True, "seconds": 0.1, "lines": [{"text": "Staff 1,240", "score": 0.7,
                                                       "box": _quad(300, 400, 560, 440), "words": words}]}


class FakeGlm:
    def read_line(self, png):
        return GlmRead("Staff 1,248", False, 0.2, "k0")


def test_a_digital_pdf_gives_all_four_outputs(tmp_path, capsys):
    pdf = write_pdf(tmp_path / "digital.pdf", DIGITAL)
    out = tmp_path / "out"
    assert cli.main(["read", str(pdf), "--out", str(out)]) == 0
    reading = (out / "reading.md").read_text(encoding="utf-8")
    assert "[p. 1]" in reading and "Revenue reached 1,240 million in 2020." in reading
    assert "Hidden note 999" not in reading.split("<!-- end of prose -->")[0]   # hidden text is not in the prose
    assert "Hidden note 999" in reading.split("<!-- end of prose -->")[1]       # but it is listed at the end
    blocks = [Block.model_validate_json(line) for line in (out / "blocks.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(b.text.startswith("Revenue") for b in blocks)
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "digital_healthy" in report and "الوقت" in report and "مخفي" in report
    assert (out / "overlays" / "p0000.png").is_file()
    printed = capsys.readouterr().out
    assert str(out) in printed and "reading.md" in printed


def test_a_scanned_page_goes_through_ocr_and_shows_flags_inline(tmp_path):
    content = b"q 612 0 0 792 0 0 cm /Im1 Do Q\n"
    pdf = write_pdf(tmp_path / "scan.pdf", content, extra_resources=b"/XObject << /Im1 7 0 R >>", extra_objects=(IMAGE,))
    out = tmp_path / "out"
    summary = cli.run(pdf, out, worker_factory=FakeWorker, glm=FakeGlm(), ocr_config=OcrConfig(confidence_bar=0.9))
    reading = (out / "reading.md").read_text(encoding="utf-8")
    assert "⚠[uncertain number: 1,240 / 1,248]" in reading
    assert summary["ocr_pages"] == [0] and summary["numbers_flagged"] == 1
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "OCR" in report and "0.845" in report                                   # mean confidence of the page
    assert (out / "overlays" / "p0000.png").is_file()
    assert any(json.loads(line)["route"] == "ocr" for line in (out / "blocks.jsonl").read_text(encoding="utf-8").splitlines())


def test_test_split_files_are_refused_unless_milestone(tmp_path, monkeypatch):
    pdf = write_pdf(tmp_path / "sealed.pdf", DIGITAL)
    monkeypatch.setattr(cli, "test_split_hashes", lambda: {hashlib.sha256(pdf.read_bytes()).hexdigest()})
    assert cli.main(["read", str(pdf), "--out", str(tmp_path / "out")]) == 3
    assert not (tmp_path / "out" / "reading.md").exists()
    assert cli.main(["read", str(pdf), "--out", str(tmp_path / "out"), "--milestone"]) == 0


def test_the_real_registry_lists_the_sealed_test_documents():
    assert len(cli.test_split_hashes()) == 2
