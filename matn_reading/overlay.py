"""Debug overlays for the owner's visual review: one PNG per page, block boxes coloured by block type with their
reading-order number, figure regions dashed, flagged blocks marked "!", a band coloured by the page route, and a
legend panel on the right."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .read import PageReading
from .triage import Route

TYPE_COLOURS = {
    "heading": (214, 39, 40), "text": (31, 119, 180), "list_item": (23, 190, 207), "caption": (148, 103, 189),
    "table": (255, 127, 14), "figure": (127, 127, 127), "footnote": (140, 86, 75), "header": (188, 189, 34),
    "footer": (188, 189, 34),
}
ROUTE_COLOURS = {
    Route.DIGITAL_HEALTHY: (44, 160, 44), Route.DIGITAL_BROKEN: (214, 39, 40), Route.SCANNED: (64, 64, 64),
    Route.SCANNED_WITH_OCR_LAYER: (227, 119, 194), Route.MIXED: (255, 187, 0),
}
LEGEND_WIDTH = 260
BAND = 18


def _font(size: int):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _dashed_rect(draw: ImageDraw.ImageDraw, box, colour, dash: int = 8, width: int = 2) -> None:
    x0, y0, x1, y1 = box
    for start, end, fixed, horizontal in ((x0, x1, y0, True), (x0, x1, y1, True), (y0, y1, x0, False),
                                          (y0, y1, x1, False)):
        position = start
        while position < end:
            stop = min(position + dash, end)
            if horizontal:
                draw.line((position, fixed, stop, fixed), fill=colour, width=width)
            else:
                draw.line((fixed, position, fixed, stop), fill=colour, width=width)
            position += 2 * dash


def draw_overlay(page: PageReading, image: Image.Image, scale: float, crop_origin=(0.0, 0.0)) -> Image.Image:
    """``image`` is the pypdfium2 render of the CropBox at ``scale``; ``crop_origin`` is the CropBox top-left in
    reader coordinates."""
    ox, oy = crop_origin
    canvas = Image.new("RGB", (image.width + LEGEND_WIDTH, image.height + BAND), "white")
    canvas.paste(image, (0, BAND))
    draw = ImageDraw.Draw(canvas, "RGBA")
    small, label = _font(11), _font(13)

    def to_px(box):
        return ((box[0] - ox) * scale, (box[1] - oy) * scale + BAND, (box[2] - ox) * scale, (box[3] - oy) * scale + BAND)

    route_colour = ROUTE_COLOURS[page.route]
    draw.rectangle((0, 0, image.width, BAND - 1), fill=route_colour)
    draw.text((6, 2), f"p{page.page_index} ({page.page_label or '-'})  route: {page.route.value}", fill="white",
              font=label)
    for region in page.figure_regions:
        _dashed_rect(draw, to_px(region), (90, 90, 90))
    for order, block in enumerate(page.blocks):
        colour = TYPE_COLOURS[block.block_type]
        x0, y0, x1, y1 = to_px(block.layout.bbox)
        draw.rectangle((x0 - 1, y0 - 1, x1 + 1, y1 + 1), outline=colour + (255,), fill=colour + (28,), width=2)
        tag = f"{order}{' !' if block.flagged else ''}"
        draw.rectangle((x0 - 1, y0 - 13, x0 + 7 * len(tag) + 4, y0 - 1), fill=colour + (230,))
        draw.text((x0 + 1, y0 - 13), tag, fill="white", font=small)

    lx, ly = image.width + 12, BAND + 8
    draw.text((lx, ly), "Block types", fill="black", font=label)
    ly += 20
    for name, colour in TYPE_COLOURS.items():
        if name == "footer":
            continue
        draw.rectangle((lx, ly + 2, lx + 14, ly + 14), fill=colour + (200,), outline=colour)
        draw.text((lx + 20, ly), "header / footer" if name == "header" else name, fill="black", font=small)
        ly += 18
    ly += 6
    draw.text((lx, ly), "Page route (top band)", fill="black", font=label)
    ly += 20
    for route, colour in ROUTE_COLOURS.items():
        draw.rectangle((lx, ly + 2, lx + 14, ly + 14), fill=colour)
        draw.text((lx + 20, ly), route.value, fill="black", font=small)
        ly += 18
    ly += 6
    for line in ("number = reading order", "! = flagged / non-prose", "dashed = figure region",
                 "hidden/uncertain excluded", "reasons in run JSON"):
        draw.text((lx, ly), line, fill="black", font=small)
        ly += 16
    ly += 6
    draw.text((lx, ly), "Reasons", fill="black", font=label)
    ly += 18
    for reason in page.reasons[:2]:
        words, row = reason.split(), ""
        for word in words:
            if len(row) + len(word) > 34:
                draw.text((lx, ly), row, fill=(60, 60, 60), font=small)
                ly, row = ly + 14, ""
            row = f"{row} {word}".strip()
        draw.text((lx, ly), row, fill=(60, 60, 60), font=small)
        ly += 18
    return canvas


def write_overlays(pages: list[PageReading], renders, out_dir: Path, scale: float) -> list[Path]:
    """``renders`` yields (page_index, PIL image, crop_origin) for each page in ``pages``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    by_index = {p.page_index: p for p in pages}
    for page_index, image, origin in renders:
        path = out_dir / f"p{page_index:04d}.png"
        draw_overlay(by_index[page_index], image, scale, origin).save(path, optimize=True)
        written.append(path)
    return written
