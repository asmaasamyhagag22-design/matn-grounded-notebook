"""Labeled contact sheets of slide PNGs (PIL only), for choosing and reviewing gallery templates.

`python scripts/contact_sheet.py themes` builds out/gallery/office_themes_contact_sheet.png from the PNGs that
design/templates/src/preview_office_themes.ps1 exported.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from matn_deck.measure import font_file  # noqa: E402
GALLERY_OUT = ROOT / "out" / "gallery"
_BACKGROUND = (246, 246, 244)
_INK = (30, 30, 30)
_FRAME = (200, 200, 200)


def _label_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_file("Segoe UI Semibold") or font_file("Segoe UI")), size)


def build_sheet(
    groups: list[tuple[str, list[Path]]],
    out_path: Path,
    *,
    per_row: int,
    thumb_w: int = 320,
    gap: int = 16,
    label_size: int = 22,
) -> Path:
    """One labeled group per (label, PNGs); groups flow left to right, `per_row` groups per row."""
    thumbs_per_group = max(len(paths) for _, paths in groups)
    thumb_h = thumb_w * 9 // 16
    label_h = label_size + 14
    group_w = thumbs_per_group * thumb_w + (thumbs_per_group - 1) * gap // 2
    rows = (len(groups) + per_row - 1) // per_row
    width = per_row * group_w + (per_row + 1) * gap
    height = rows * (label_h + thumb_h) + (rows + 1) * gap
    sheet = Image.new("RGB", (width, height), _BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    font = _label_font(label_size)
    for index, (label, paths) in enumerate(groups):
        x = gap + (index % per_row) * (group_w + gap)
        y = gap + (index // per_row) * (label_h + thumb_h + gap)
        draw.text((x, y), label, fill=_INK, font=font)
        for n, path in enumerate(paths):
            with Image.open(path) as image:
                thumb = image.convert("RGB").resize((thumb_w, thumb_h), Image.LANCZOS)
            tx = x + n * (thumb_w + gap // 2)
            sheet.paste(thumb, (tx, y + label_h))
            draw.rectangle((tx - 1, y + label_h - 1, tx + thumb_w, y + label_h + thumb_h), outline=_FRAME)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # PowerPoint/image previews can briefly retain a read handle on the previous sheet on Windows.  Encode to a
    # sibling first, then replace the completed image atomically so a transient handle never leaves a partial PNG.
    handle, temporary = tempfile.mkstemp(prefix=f".{out_path.stem}-", suffix=out_path.suffix,
                                         dir=out_path.parent)
    os.close(handle)
    temporary_path = Path(temporary)
    try:
        sheet.save(temporary_path)
        os.replace(temporary_path, out_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return out_path


def office_themes_sheet(themes_dir: Path = GALLERY_OUT / "themes",
                        out_path: Path = GALLERY_OUT / "office_themes_contact_sheet.png") -> Path:
    themes = json.loads(themes_dir.joinpath("themes.json").read_text(encoding="utf-8-sig"))
    groups = [(f"{n}. {t['name']}", [themes_dir / f"{t['name']}_1.png", themes_dir / f"{t['name']}_2.png"])
              for n, t in enumerate(themes, start=1)]
    return build_sheet(groups, out_path, per_row=3)


if __name__ == "__main__":
    if sys.argv[1:] == ["themes"]:
        print(office_themes_sheet())
    else:
        sys.exit("usage: python scripts/contact_sheet.py themes")
