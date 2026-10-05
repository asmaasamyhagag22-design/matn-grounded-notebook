"""Close-out regressions: semantic regions must override correlated OCR agreement."""
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
from PIL import Image

from matn_reading.cli import write_reading
from matn_reading.ocr.route import read_scan_page
from .test_route import CONFIG, FakeGlm, FakeWorker, _line, _page
from matn_reading.triage import Route


class RegionsWorker(FakeWorker):
    def __init__(self, lines, regions):
        super().__init__(lines)
        self.regions = regions

    def read(self, path):
        return {**super().read(path), "layout": self.regions}


def read(lines, regions, answers, tmp_path):
    return read_scan_page(_page(), page_index=0, page_label=None, cropbox=(0, 0, 612, 792),
                          route=Route.SCANNED, reasons=[], doc_id="sha256-" + "0" * 64,
                          worker=RegionsWorker(lines, regions), glm=FakeGlm(answers),
                          config=replace(CONFIG, targets=frozenset({"all"})), crop_dir=tmp_path)


def test_scatter_dots_agreed_as_8_are_excluded_from_prose(tmp_path):
    page = read([_line([("8", .99993)], 500)],
                [{"class": "chart", "bbox": [200, 400, 1000, 800], "score": .9}], {"a": "8"}, tmp_path)
    assert page.ocr["tokens"][0]["flagged"]
    assert page.ocr["tokens"][0]["role"] == "figure_text"
    assert page.blocks[0].block_type == "figure"
    write_reading([page], "dots", tmp_path / "reading.md")
    assert "8" not in (tmp_path / "reading.md").read_text(encoding="utf-8").split("<!-- end of prose -->")[0]


def test_header_footer_and_caption_are_kept_out_of_body_or_preserved(tmp_path):
    lines = [_line([("Page", .99), ("ii", .99)], 100), _line([("Figure", .99), ("1", .99)], 800)]
    regions = [{"class": "footer", "bbox": [250, 90, 800, 180], "score": .9},
               {"class": "figure_title", "bbox": [250, 790, 1000, 870], "score": .9}]
    page = read(lines, regions, {"a": "Figure 1"}, tmp_path)
    assert [b.block_type for b in page.blocks] == ["footer", "caption"]
    write_reading([page], "test", tmp_path / "reading.md")
    prose = (tmp_path / "reading.md").read_text(encoding="utf-8").split("<!-- end of prose -->")[0]
    assert "Page ii" not in prose and "Figure 1" in prose


def test_code_columns_do_not_trigger_text_table_alarm(tmp_path):
    lines = [_line([("ratio", .99)], 400), _line([("0.25", .99)], 400, x=1200),
             _line([("ratio", .99)], 460), _line([("0.15", .99)], 460, x=1200),
             _line([("ratio", .99), ("0.35", .99)], 800)]
    page = read(lines, [{"class": "text", "bbox": [0, 0, 2550, 3300], "score": .9}],
                {"a": "0.25", "b": "0.15", "c": "ratio 0.35"}, tmp_path)
    assert page.ocr["tables"] == []
    assert not any(f["kind"] == "text_table_mismatch" for f in page.flags)


def test_noise_adaptive_filter_leaves_clean_page_identical():
    from matn_reading.ocr.preprocess import PreprocessConfig, preprocess
    clean = Image.new("L", (100, 100), 255)
    out, record = preprocess(clean, PreprocessConfig(deskew=False))
    assert np.array_equal(np.asarray(clean), np.asarray(out))
    assert record["steps"][1]["filtered"] is False


def test_holdout2_disjoint_from_previous_synthetic_pages():
    root = Path(__file__).resolve().parents[3]
    old = json.loads((root / "eval/reading/synthetic/pages.json").read_text(encoding="utf-8"))["pages"]
    new = json.loads((root / "eval/reading/synthetic/holdout2.json").read_text(encoding="utf-8"))["pages"]
    keys = lambda rows: {(p["doc_id"], p["page_index"]) for p in rows}
    assert len(new) == len(keys(new)) == 30 and not keys(old) & keys(new)
    assert len({p["seed"] for p in new}) == 30


def test_rotated_stamp_and_axis_agreement_cannot_bypass_orientation(tmp_path):
    fixtures = Path(__file__).with_name("fixtures")
    for name, token in [("arxiv_stamp", "2"), ("wb_dec20", "20")]:
        image = Image.open(fixtures / (name + ".png"))
        w, h = image.size
        x = 2 if name == "arxiv_stamp" else 30
        quad = [[x, 40], [x+15, 40], [x+15, 40+h-50], [x, 40+h-50]]
        lines = [{"text": token, "score": .99993, "box": quad, "words": []}]
        regions = [{"class": "vertical_text" if name == "arxiv_stamp" else "chart",
                    "bbox": [0,0,w,h], "score": .9}]
        page = read_scan_page(image, page_index=0, page_label=None, cropbox=(0,0,w*72/300,h*72/300),
                             route=Route.SCANNED, reasons=[], doc_id="sha256-"+"0"*64,
                             worker=RegionsWorker(lines, regions), glm=FakeGlm({"a":token}),
                             config=replace(CONFIG,targets=frozenset({"all"})),crop_dir=tmp_path)
        assert page.ocr["tokens"][0]["flagged"]
        assert "rotation" in page.ocr["tokens"][0]
        assert page.blocks[0].block_type == "figure"


def test_scatter_crop_with_agreed_8_is_flagged(tmp_path):
    im = Image.open(Path(__file__).with_name("fixtures") / "wb_scatter_dots.png")
    w,h = im.size
    line = _line([("8",.99993)],10,x=10,height=h-20)
    page = read_scan_page(im,page_index=0,page_label=None,cropbox=(0,0,w*72/300,h*72/300),
                          route=Route.SCANNED,reasons=[],doc_id="sha256-"+"0"*64,
                          worker=RegionsWorker([line],[{"class":"chart","bbox":[0,0,w,h],"score":.9}]),
                          glm=FakeGlm({"a":"8"}),config=replace(CONFIG,targets=frozenset({"all"})))
    assert page.ocr["tokens"][0]["flagged"]


def test_repeated_margin_furniture_does_not_enter_prose(tmp_path):
    from matn_reading.ocr.regions import repeat_furniture
    pages = [read([_line([("Annual",.99),("report",.99),(str(i),.99)],10)],[],{"a":str(i)},tmp_path) for i in (1,2)]
    pages[1].page_index=1
    repeat_furniture(pages)
    assert all(p.blocks[0].block_type == "header" for p in pages)
    write_reading(pages,"test",tmp_path / "repeat.md")
    assert "Annual report" not in (tmp_path / "repeat.md").read_text(encoding="utf-8")


def test_scan_overlay_preserves_character_pixels_and_keeps_legend(tmp_path):
    from matn_reading.overlay import draw_overlay, BAND
    page = read([_line([("Staff",.99),("20",.99)],400)],[],{"a":"Staff 20"},tmp_path)
    image = Image.new("RGB", (612,792), "white")
    overlay = draw_overlay(page,image,1.0)
    # The box interior remains unchanged; numbers are outlined, never covered by a coloured fill.
    assert overlay.getpixel((76,102+BAND)) == (255,255,255)
    assert overlay.height >= 650


def test_undetected_vertical_layout_region_is_rotated_and_second_read(tmp_path):
    page=read([], [{"class":"vertical_text","bbox":[20,300,60,1000],"score":.9}],
              {"a":"arXiv 2601.14525"},tmp_path)
    assert page.ocr["second_reads"]["lines"]==1
    assert any(f["kind"]=="possible_drop" and f["reader2"]==["2601.14525"] for f in page.flags)


def test_short_upright_digit_is_not_rotated_due_to_glyph_height():
    from matn_reading.ocr.regions import orientation
    assert orientation([[0,0],[35,0],[35,40],[0,40]],(0,0,35,40),"text")==0.0


def test_nonmargin_rotated_number_requires_agreement_after_rotation(tmp_path):
    quad=[[500,400],[530,400],[530,800],[500,800]]
    lines=[{"text":"12","score":.99,"box":quad,"words":[]}]
    page=read(lines,[{"class":"vertical_text","bbox":[490,390,540,810],"score":.9}],{"a":"12"},tmp_path)
    assert page.ocr["tokens"][0]["rotation"]["agreed_after_rotation"]
    assert not page.ocr["tokens"][0]["flagged"]
    assert page.ocr["tokens"][0]["role"]=="text"


def test_score_one_still_gets_the_default_second_read(tmp_path):
    from .test_route import _read
    from matn_reading.ocr.route import OcrConfig
    glm=FakeGlm({"a":"Staff 12"})
    page=_read([_line([("Staff",1.0),("12",1.0)],400)],glm,config=OcrConfig(),tmp_path=tmp_path)
    assert len(glm.asked)==1 and page.ocr["tokens"][0]["status"]=="agreed"


def test_horizontal_fragment_of_vertical_margin_stamp_is_not_accepted(tmp_path):
    # Final dev-tune arXiv p0: the detector splits the rotated stamp into tall letters and an upright-looking 2.
    stamp={"text":"S","score":.99,"box":[[60,1700],[120,1700],[120,1950],[60,1950]],"words":[]}
    fragment={"text":"2","score":.98253,"box":[[77,2100],[138,2100],[138,2152],[77,2152]],"words":[]}
    body=_line([("12",.99)],2100,x=500,height=52)
    page=read([stamp,fragment,body],[],{"a":"S","b":"2","c":"12"},tmp_path)
    two,twelve=page.ocr['tokens']
    assert two['role']=='marginalia' and two['flagged']
    assert twelve['role']=='text' and not twelve['flagged']


def test_duplicate_detection_of_a_year_digit_cannot_be_accepted_twice(tmp_path):
    # Dev-tune WB p10: 21 in FY2020/21, then its final 1 detected again on an overlapping line.
    lines=[_line([('21',.99494)],1750,x=931,height=55),
           _line([('1',.87915)],1748,x=965,height=53),
           _line([('12',.999)],1900,x=500)]
    page=read(lines,[],{'a':'21','b':'1','c':'12'},tmp_path)
    twenty_one,one,twelve=page.ocr['tokens']
    assert twenty_one['flagged'] and one['flagged']
    assert 'overlapping_number_detections' in one['reasons']
    assert not twelve['flagged']
