"""Step 4b layout on word boxes (PDF points, top-left origin): lines, blocks, columns, order, hyphens, furniture."""
from __future__ import annotations

from matn_reading.layout import (
    Word,
    detect_furniture,
    group_blocks,
    group_lines,
    join_hyphenation,
    order_blocks,
)

PAGE_W, PAGE_H = 612.0, 792.0


def _line(text: str, x0: float, top: float, size: float = 10.0, bold: bool = False) -> list[Word]:
    words, x = [], x0
    for token in text.split():
        width = 0.5 * size * len(token)
        words.append(Word(token, x, top, x + width, top + size, size, bold))
        x += width + 0.3 * size
    return words


def _para(lines: list[str], x0: float, top: float, size: float = 10.0, leading: float = 12.0) -> list[Word]:
    return [w for i, text in enumerate(lines) for w in _line(text, x0, top + i * leading, size)]


def _texts(blocks) -> list[str]:
    return [b.text for b in blocks]


def test_words_on_one_baseline_become_one_line_and_a_gutter_splits_it():
    words = _line("left column words", 72, 100) + _line("right column words", 320, 100)
    lines = group_lines(words)
    assert [line.text for line in lines] == ["left column words", "right column words"]


def test_lines_group_into_paragraph_blocks_by_gap_and_style():
    words = (_line("A Heading", 72, 80, size=16, bold=True)
             + _para(["first line of the paragraph", "second line of the paragraph"], 72, 110)
             + _para(["a new paragraph after a gap"], 72, 160))
    blocks = group_blocks(group_lines(words))
    assert _texts(blocks) == ["A Heading", "first line of the paragraph second line of the paragraph",
                              "a new paragraph after a gap"]
    assert blocks[0].size == 16 and blocks[0].bold


def test_two_columns_read_left_column_first_then_right():
    words = (_line("Title across the page", 72, 60, size=18, bold=True)
             + _para(["left one", "left two"], 72, 120) + _para(["left three", "left four"], 72, 170)
             + _para(["right one", "right two"], 320, 120) + _para(["right three", "right four"], 320, 170))
    ordered = order_blocks(group_blocks(group_lines(words)), PAGE_W)
    assert _texts(ordered) == ["Title across the page", "left one left two", "left three left four",
                               "right one right two", "right three right four"]


def test_a_full_width_block_between_column_sections_keeps_its_place():
    words = (_para(["top left a", "top left b"], 72, 100) + _para(["top right a", "top right b"], 320, 100)
             + _line("a full width figure caption that crosses the gutter between the two columns", 72, 200)
             + _para(["low left a", "low left b"], 72, 260) + _para(["low right a", "low right b"], 320, 260))
    ordered = order_blocks(group_blocks(group_lines(words)), PAGE_W)
    assert _texts(ordered)[0:2] == ["top left a top left b", "top right a top right b"]
    assert _texts(ordered)[2].startswith("a full width figure caption")
    assert _texts(ordered)[3:] == ["low left a low left b", "low right a low right b"]


def test_side_headings_in_a_narrow_margin_column_interleave_with_the_body():
    body = ["the body text of this section runs across a wide column", "and keeps going on a second line",
            "then ends here on the third line"]
    words = (_line("Background", 40, 100, bold=True) + _para(body, 200, 100)
             + _line("Scope", 40, 200, bold=True) + _para(body, 200, 200))
    ordered = order_blocks(group_blocks(group_lines(words)), PAGE_W)
    assert [t[:12] for t in _texts(ordered)] == ["Background", "the body tex", "Scope", "the body tex"]
    assert ordered[1].top < ordered[2].top <= ordered[3].top


def test_hyphenation_is_joined_and_the_raw_text_is_kept():
    joined, raw = join_hyphenation(["the govern-", "ment budget", "self-", "Driving"])
    assert joined == "the government budget self-Driving"
    assert raw == "the govern-\nment budget\nself-\nDriving"


def test_hyphen_before_a_digit_or_capital_is_kept_and_joined_without_a_space():
    joined, _ = join_hyphenation(["fiscal years 2019-", "2021 and COVID-", "19 cases"])
    assert joined == "fiscal years 2019-2021 and COVID-19 cases"


def test_repeated_headers_and_footers_are_detected_across_pages():
    pages = []
    for page in range(5):
        words = (_line("GAO-21-519SP AI Accountability Framework", 72, 20, size=8)
                 + _para([f"body text of page {page}", "more body"], 72, 200)
                 + _line(f"Page {page + 3}", 290, 760, size=8))
        pages.append(group_lines(words))
    furniture = detect_furniture(pages, PAGE_H)
    assert all(furniture[p] == {0: "header", 3: "footer"} for p in range(5))


def test_unique_text_near_the_top_is_not_furniture():
    pages = [group_lines(_line("Chapter one: a unique opening line", 72, 20) + _para(["body"], 72, 200))]
    pages += [group_lines(_line(f"Running head {i}", 72, 20) + _para(["body"], 72, 200)) for i in range(1, 4)]
    furniture = detect_furniture(pages, PAGE_H)
    assert furniture[0] == {}
    assert furniture[1] == {0: "header"}  # digits are normalized, so a numbered running head still repeats
