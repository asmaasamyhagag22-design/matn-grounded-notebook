"""OCR route on fake readers: targeted line second reads, consensus, confidence flags, checks, contract Blocks."""
from __future__ import annotations

from dataclasses import replace

from PIL import Image, ImageDraw

from matn_contracts.enums import ExtractionRoute
from matn_reading.ocr.glm import GlmRead
from matn_reading.ocr.preprocess import PreprocessConfig
from matn_reading.ocr.route import OcrConfig, read_scan_page
from matn_reading.triage import Route

SCALE = 300 / 72


def _quad(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _line(words: list[tuple[str, float]], y: float, x: float = 300.0, height: float = 40.0) -> dict:
    out, cursor = [], x
    for text, score in words:
        width = 24 * len(text)
        out.append({"text": text, "score": score, "box": _quad(cursor, y, cursor + width, y + height)})
        cursor += width + 20
    return {"text": " ".join(t for t, _ in words), "score": min(s for _, s in words),
            "box": _quad(x, y, cursor - 20, y + height), "words": out}


class FakeWorker:
    def __init__(self, lines):
        self.lines, self.calls = lines, 0

    def read(self, path):
        self.calls += 1
        return {"ok": True, "lines": self.lines, "seconds": 0.1, "size": [2550, 3300]}


class FakeGlm:
    def __init__(self, answers: dict[str, str | None]):
        self.answers, self.asked = answers, []

    def read_line(self, png: bytes) -> GlmRead:
        index = len(self.asked)
        self.asked.append(png)
        text = list(self.answers.values())[index] if index < len(self.answers) else None
        return GlmRead(text, False, 0.5, f"key{index}", None if text else "no answer")


def _page(ink: bool = True) -> Image.Image:
    image = Image.new("L", (2550, 3300), 255)
    if ink:
        ImageDraw.Draw(image).rectangle((300, 300, 1500, 1400), fill=0)
    return image


CONFIG = OcrConfig(preprocess=PreprocessConfig(deskew=False, denoise=False), confidence_bar=0.95,
                   targets=frozenset({"low_confidence", "table", "kpi", "summary"}))


def _read(lines, glm=None, config=CONFIG, tmp_path=None, **kwargs):
    return read_scan_page(_page(kwargs.pop("ink", True)), page_index=3, page_label="4", cropbox=(0, 0, 612, 792),
                          route=Route.SCANNED, reasons=["test"], doc_id="sha256-" + "0" * 64, worker=FakeWorker(lines),
                          glm=glm, config=config, crop_dir=tmp_path, **kwargs)


def _tokens(page):
    return {t["token"]: t for t in page.ocr["tokens"]}


def test_a_confident_prose_number_is_accepted_on_reader_1_without_a_second_read(tmp_path):
    glm = FakeGlm({})
    page = _read([_line([("Staff", 0.99), ("grew", 0.99), ("to", 0.99), ("1,240", 0.99)], 400)], glm, tmp_path=tmp_path)
    assert glm.asked == []
    token = _tokens(page)["1,240"]
    assert not token["flagged"] and token["status"] == "reader1_only"
    assert all(block.contract.route is ExtractionRoute.OCR for block in page.blocks)
    assert page.blocks[0].contract.text == "Staff grew to 1,240"
    x0, top, x1, bottom = page.blocks[0].contract.bbox
    assert abs(top - 400 / SCALE) < 0.5 and abs(x0 - 300 / SCALE) < 0.5


def test_a_low_confidence_number_is_second_read_and_accepted_only_on_exact_agreement(tmp_path):
    glm = FakeGlm({"a": "Staff grew to 1,240"})
    page = _read([_line([("Staff", 0.99), ("grew", 0.99), ("to", 0.99), ("1,240", 0.80)], 400)], glm, tmp_path=tmp_path)
    assert len(glm.asked) == 1
    token = _tokens(page)["1,240"]
    assert token["status"] == "agreed" and not token["flagged"]


def test_disagreement_is_flagged_with_both_readings_and_the_crop_kept(tmp_path):
    glm = FakeGlm({"a": "Staff grew to 1,248"})
    page = _read([_line([("Staff", 0.99), ("grew", 0.99), ("to", 0.99), ("1,240", 0.80)], 400)], glm, tmp_path=tmp_path)
    token = _tokens(page)["1,240"]
    assert token["flagged"] and token["status"] == "uncertain_number" and token["reader2"] == "1,248"
    flag = next(f for f in page.flags if f["kind"] == "uncertain_number")
    assert (flag["reader1"], flag["reader2"]) == ("1,240", "1,248")
    assert (tmp_path / flag["crop"]).is_file()
    assert page.blocks[0].flagged


def test_numbers_in_table_rows_are_second_read_even_when_confident(tmp_path):
    rows = [_line([("North", 0.99)], 400), _line([("1,240", 0.99)], 400, x=1200), _line([("13.5", 0.99)], 400, x=1600),
            _line([("South", 0.99)], 460), _line([("760", 0.99)], 460, x=1200), _line([("6.5", 0.99)], 460, x=1600)]
    glm = FakeGlm({str(i): text for i, text in enumerate(["1,240", "13.5", "760", "6.5"])})
    page = _read(rows, glm, tmp_path=tmp_path)
    assert len(glm.asked) == 4
    assert all(t["status"] == "agreed" for t in page.ocr["tokens"])


def test_kpi_numbers_are_second_read(tmp_path):
    glm = FakeGlm({"a": "Growth of 9.8% this year"})
    page = _read([_line([("Growth", 0.99), ("of", 0.99), ("9.8%", 0.99), ("this", 0.99), ("year", 0.99)], 400)],
                 glm, tmp_path=tmp_path)
    assert len(glm.asked) == 1 and _tokens(page)["9.8"]["status"] == "agreed"


def test_target_all_second_reads_every_number_line(tmp_path):
    glm = FakeGlm({"a": "Staff grew to 1,240"})
    page = _read([_line([("Staff", 0.99), ("grew", 0.99), ("to", 0.99), ("1,240", 0.99)], 400)], glm,
                 config=replace(CONFIG, targets=frozenset({"all"})), tmp_path=tmp_path)
    assert len(glm.asked) == 1 and _tokens(page)["1,240"]["status"] == "agreed"


def test_without_second_reads_a_low_confidence_number_is_flagged_by_confidence(tmp_path):
    page = _read([_line([("Staff", 0.99), ("to", 0.99), ("1,240", 0.80)], 400)], None,
                 config=replace(CONFIG, second_read=False), tmp_path=tmp_path)
    token = _tokens(page)["1,240"]
    assert token["flagged"] and "low_confidence" in token["reasons"]


def test_a_failed_second_read_flags_the_line(tmp_path):
    page = _read([_line([("Staff", 0.99), ("to", 0.99), ("1,240", 0.80)], 400)], FakeGlm({"a": None}),
                 tmp_path=tmp_path)
    assert _tokens(page)["1,240"]["flagged"]


def test_a_number_only_reader_2_sees_flags_its_line(tmp_path):
    glm = FakeGlm({"a": "Units 45 sold in 2020"})
    page = _read([_line([("Units", 0.99), ("sold", 0.99), ("in", 0.99), ("2020", 0.80)], 400)], glm, tmp_path=tmp_path)
    assert any(f["kind"] == "possible_drop" and f["reader2"] == ["45"] for f in page.flags)


def test_a_table_total_that_does_not_add_up_flags_its_numbers(tmp_path):
    rows = [_line([("North", 0.99)], 400), _line([("1,248", 0.99)], 400, x=1200),
            _line([("South", 0.99)], 460), _line([("760", 0.99)], 460, x=1200),
            _line([("Total", 0.99)], 520), _line([("2,000", 0.99)], 520, x=1200)]
    glm = FakeGlm({str(i): text for i, text in enumerate(["1,248", "760", "2,000"])})
    page = _read(rows, glm, tmp_path=tmp_path)
    tokens = _tokens(page)
    assert all(tokens[t]["flagged"] and "table_total_mismatch" in tokens[t]["reasons"] for t in ("1,248", "760", "2,000"))


def test_low_confidence_non_number_words_are_flagged(tmp_path):
    page = _read([_line([("Staff", 0.60), ("grew", 0.99)], 400)], FakeGlm({}), tmp_path=tmp_path)
    assert any(f["kind"] == "low_confidence" and f["text"] == "Staff" for f in page.flags)


def test_an_inked_page_with_no_text_read_is_flagged_not_silent(tmp_path):
    page = _read([], FakeGlm({}), tmp_path=tmp_path)
    assert any(f["kind"] == "ocr_no_text" for f in page.flags)
    assert not any(f["kind"] == "ocr_no_text" for f in _read([], FakeGlm({}), tmp_path=tmp_path, ink=False).flags)


def test_numbers_that_disagree_with_an_embedded_ocr_layer_are_flagged(tmp_path):
    line = _line([("Staff", 0.99), ("to", 0.99), ("1,240", 0.99)], 400)
    box = line["words"][2]["box"]
    layer = [("1,248", (box[0][0] / SCALE, box[0][1] / SCALE, box[2][0] / SCALE, box[2][1] / SCALE))]
    page = _read([line], FakeGlm({}), tmp_path=tmp_path, text_layer=layer)
    token = _tokens(page)["1,240"]
    assert token["flagged"] and "ocr_layer_disagreement" in token["reasons"]
    assert any(f["kind"] == "ocr_layer_disagreement" and f["layer"] == "1,248" for f in page.flags)


def test_noisy_ocr_line_heights_still_form_one_paragraph(tmp_path):
    lines = [_line([("The", 0.99), ("first", 0.99), ("line", 0.99)], 400, height=40),
             _line([("the", 0.99), ("second", 0.99), ("line", 0.99)], 452, height=46),
             _line([("and", 0.99), ("third", 0.99)], 504, height=36)]
    page = _read(lines, FakeGlm({}), tmp_path=tmp_path)
    assert [b.block_type for b in page.blocks] == ["text"]
    assert page.blocks[0].contract.text == "The first line the second line and third"


def test_a_clearly_larger_ocr_line_is_still_a_heading(tmp_path):
    lines = [_line([("Background", 0.99)], 300, height=70),
             _line([("body", 0.99), ("text", 0.99), ("here", 0.99)], 420, height=40),
             _line([("more", 0.99), ("body", 0.99), ("text", 0.99)], 472, height=40)]
    page = _read(lines, FakeGlm({}), tmp_path=tmp_path)
    assert [b.block_type for b in page.blocks] == ["heading", "text"]
