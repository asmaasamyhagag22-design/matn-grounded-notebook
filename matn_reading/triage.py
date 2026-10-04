"""Page triage: exactly one route per page, decided from measured signals, with the reasons written down.

Routes:
- digital_healthy: a clean text layer; read it directly.
- digital_broken: the text layer exists but cannot be trusted (U+FFFD, private-use glyphs, "(cid:N)" artifacts, or
  the two extractors disagree). Its text is never passed as clean; Step 4c sends it to OCR.
- scanned: a page image covers most of the page and there is little or no text layer (also a blank page, so that
  nothing is silently treated as "no content").
- scanned_with_ocr_layer: invisible text (render mode 3) over a page image. A legitimate OCR layer, not an attack;
  its text is still re-read by our own OCR before any number is trusted.
- mixed: real digital text plus a large image that may hold text the layer does not have.

Thresholds are named constants so a reviewer can see and question each one.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum

SCANNED_IMAGE_COVERAGE = 0.60      # a page image at least this large makes the page a scan candidate
MIXED_IMAGE_COVERAGE = 0.30        # digital text plus an image this large -> mixed
LITTLE_TEXT_CHARS = 200            # fewer visible characters than this counts as "little text"
OCR_LAYER_INVISIBLE_SHARE = 0.50   # at least this share of characters in render mode 3 -> OCR layer
BROKEN_GLYPH_SHARE = 0.002         # more than 0.2% broken glyphs (or more than BROKEN_GLYPH_MIN) -> broken
BROKEN_GLYPH_MIN = 3
MIN_AGREEMENT = 0.97               # pdfplumber vs pypdfium2 text agreement below this -> broken

_CID = re.compile(r"\(cid:\d+\)")


class Route(str, Enum):
    DIGITAL_HEALTHY = "digital_healthy"
    DIGITAL_BROKEN = "digital_broken"
    SCANNED = "scanned"
    SCANNED_WITH_OCR_LAYER = "scanned_with_ocr_layer"
    MIXED = "mixed"


@dataclass(frozen=True)
class PageSignals:
    chars: int              # characters in the text layer (all render modes)
    visible_chars: int      # characters painted visibly (render mode != 3)
    invisible_chars: int    # characters in render mode 3 (invisible)
    broken_glyphs: int      # U+FFFD + private-use + "(cid:N)" occurrences
    text_coverage: float    # share of the page covered by character boxes
    image_coverage: float   # share of the page covered by images (union, clipped to the page)
    agreement: float        # 0..1 text agreement between pdfplumber and pypdfium2


def glyph_issues(text: str) -> dict[str, int]:
    return {
        "replacement_char": text.count("�"),
        "private_use": sum(1 for ch in text if 0xE000 <= ord(ch) <= 0xF8FF or 0xF0000 <= ord(ch) <= 0x10FFFD),
        "cid": len(_CID.findall(text)),
    }


def text_agreement(a: str, b: str) -> float:
    """Character-multiset agreement with whitespace removed: 1.0 means both extractors produced the same characters.
    Order is ignored on purpose (the two libraries order text differently); missing or extra characters count."""
    ca, cb = Counter("".join(a.split())), Counter("".join(b.split()))
    total = sum(ca.values()) + sum(cb.values())
    return 1.0 if total == 0 else 2 * sum((ca & cb).values()) / total


def decide_route(s: PageSignals) -> tuple[Route, list[str]]:
    measured = (f"chars={s.chars}", f"visible_chars={s.visible_chars}", f"invisible_chars={s.invisible_chars}",
                f"broken_glyphs={s.broken_glyphs}", f"text_coverage={s.text_coverage:.3f}",
                f"image_coverage={s.image_coverage:.3f}", f"agreement={s.agreement:.3f}")
    reasons: list[str] = []

    if s.chars == 0 and s.image_coverage < SCANNED_IMAGE_COVERAGE:
        reasons.append("no_text: the page has no text layer at all; routed to OCR so it is never treated as empty")
        return Route.SCANNED, reasons + list(measured)

    if s.image_coverage >= SCANNED_IMAGE_COVERAGE:
        if s.chars and s.invisible_chars / s.chars >= OCR_LAYER_INVISIBLE_SHARE:
            reasons.append(f"render_mode_3: {s.invisible_chars}/{s.chars} characters are invisible over a page image "
                           f"(image_coverage {s.image_coverage:.2f} >= {SCANNED_IMAGE_COVERAGE}); legitimate OCR layer")
            return Route.SCANNED_WITH_OCR_LAYER, reasons + list(measured)
        if s.visible_chars < LITTLE_TEXT_CHARS:
            reasons.append(f"image_coverage {s.image_coverage:.2f} >= {SCANNED_IMAGE_COVERAGE} and only "
                           f"{s.visible_chars} visible characters (< {LITTLE_TEXT_CHARS})")
            return Route.SCANNED, reasons + list(measured)

    broken_limit = max(BROKEN_GLYPH_MIN, BROKEN_GLYPH_SHARE * max(s.chars, 1))
    if s.broken_glyphs > broken_limit or s.agreement < MIN_AGREEMENT:
        if s.broken_glyphs > broken_limit:
            reasons.append(f"broken_glyphs {s.broken_glyphs} > {broken_limit:.1f} (U+FFFD, private-use or cid)")
        if s.agreement < MIN_AGREEMENT:
            reasons.append(f"agreement {s.agreement:.3f} < {MIN_AGREEMENT} between pdfplumber and pypdfium2")
        return Route.DIGITAL_BROKEN, reasons + list(measured)

    if s.image_coverage >= MIXED_IMAGE_COVERAGE:
        reasons.append(f"digital text plus image_coverage {s.image_coverage:.2f} >= {MIXED_IMAGE_COVERAGE}: "
                       "the image may hold text the layer does not have")
        return Route.MIXED, reasons + list(measured)

    if s.broken_glyphs:
        reasons.append(f"healthy with {s.broken_glyphs} broken glyph(s) under the limit {broken_limit:.1f}; "
                       "the words that hold them are flagged")
    else:
        reasons.append("healthy: clean glyphs, extractors agree, no large image")
    return Route.DIGITAL_HEALTHY, reasons + list(measured)
