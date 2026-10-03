from pathlib import Path

from PIL import Image

from scripts.contact_sheet import build_sheet


def test_contact_sheet_replaces_an_existing_png_atomically(tmp_path: Path):
    slide = tmp_path / "slide.png"
    output = tmp_path / "sheet.png"
    Image.new("RGB", (160, 90), "navy").save(slide)
    Image.new("RGB", (1, 1), "red").save(output)

    assert build_sheet([("template", [slide])], output, per_row=1, thumb_w=160) == output
    with Image.open(output) as sheet:
        assert sheet.size[0] > 160
        assert sheet.size[1] > 90
    assert not list(tmp_path.glob(".sheet-*.png"))
