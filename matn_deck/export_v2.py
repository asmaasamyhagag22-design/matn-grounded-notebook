"""Deck export for v2: preflight, PDF through LibreOffice headless, PNG thumbnails and a contact sheet.

LibreOffice runs with a fresh `-env:UserInstallation` profile per export, so concurrent or crashed runs never share
a lock. The PDF uses the same metric-compatible OFL files as measurement (fontconfig maps the Office names).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PINNED_LIBREOFFICE = "24.2.7.2"  # Ubuntu 24.04 libreoffice-core 4:24.2.7-0ubuntu0.24.04.7
OFFICE_FACES = {"Calibri": "Carlito", "Arial": "Liberation Sans", "Times New Roman": "Liberation Serif"}
THUMB_W = 640


def soffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def libreoffice_version() -> str | None:
    exe = soffice()
    if not exe:
        return None
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60).stdout
    match = re.search(r"LibreOffice (\d+(?:\.\d+)+)", out)
    return match.group(1) if match else None


def preflight(fonts: str = "office") -> dict:
    """GO only when LibreOffice, the pinned fonts, PDFium and pdfplumber are ready, plus the Office-name
    substitutions when the office font profile (ADR-0020) is asked for."""
    from .measure import font_file, verify_fonts
    checks = {}
    version = libreoffice_version()
    checks["libreoffice"] = {"ok": version is not None, "version": version, "pinned": PINNED_LIBREOFFICE,
                             "matches_pin": version == PINNED_LIBREOFFICE}
    problems = verify_fonts()
    checks["fonts_manifest"] = {"ok": not problems, "problems": problems}
    substitutions = {}
    for office, ofl in OFFICE_FACES.items():
        matched = None
        if shutil.which("fc-match"):
            matched = subprocess.run(["fc-match", "-f", "%{family}", office], capture_output=True, text=True,
                                     timeout=30).stdout.split(",")[0]
        measured = font_file(office)
        substitutions[office] = {"fontconfig": matched, "measured_file": str(measured) if measured else None,
                                 "ok": matched == ofl and measured is not None}
    checks["office_substitution"] = {"ok": all(v["ok"] for v in substitutions.values()), "faces": substitutions}
    for module in ("pdfplumber", "pypdfium2"):
        try:
            __import__(module)
            checks[module] = {"ok": True}
        except ImportError as exc:
            checks[module] = {"ok": False, "error": str(exc)}
    required = [k for k in checks if k != "office_substitution" or fonts == "office"]
    go = all(checks[k]["ok"] for k in required)
    return {"go": go, "fonts": fonts, "checks": checks,
            "notes": [] if checks["libreoffice"]["matches_pin"] else
            [f"LibreOffice {version} differs from the pinned {PINNED_LIBREOFFICE}; re-run the QA gate before delivery."]}


def export_pdf(pptx: Path, pdf: Path, *, timeout: float = 300) -> Path:
    exe = soffice()
    if not exe:
        raise RuntimeError("LIBREOFFICE_MISSING")
    pptx = Path(pptx).resolve(strict=True)
    pdf = Path(pdf)
    pdf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="matn-lo-") as work:
        profile = Path(work) / "profile"
        subprocess.run([exe, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--convert-to",
                        "pdf:impress_pdf_Export", "--outdir", work, str(pptx)],
                       check=True, capture_output=True, text=True, timeout=timeout)
        converted = Path(work) / (pptx.stem + ".pdf")
        if not converted.is_file() or not converted.stat().st_size:
            raise RuntimeError(f"LIBREOFFICE_NO_PDF:{pptx.name}")
        shutil.copyfile(converted, pdf)
    return pdf


def thumbnails(pdf: Path, out_dir: Path, *, width: int = THUMB_W) -> list[Path]:
    import pypdfium2 as pdfium
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("slide_*.png"):
        old.unlink()
    paths = []
    document = pdfium.PdfDocument(str(pdf))
    try:
        for index in range(len(document)):
            page = document[index]
            bitmap = page.render(scale=width / page.get_width())
            path = out_dir / f"slide_{index + 1:02d}.png"
            bitmap.to_pil().convert("RGB").save(path)
            bitmap.close()
            page.close()
            paths.append(path)
    finally:
        document.close()
    return paths


def _font(size: int) -> ImageFont.FreeTypeFont:
    from .measure import font_file
    path = font_file("Carlito") or font_file("Liberation Sans") or font_file("Noto Sans")
    return ImageFont.truetype(str(path), size) if path else ImageFont.load_default()


def contact_sheet(pngs: list[Path], out: Path, *, title: str, labels: list[str] | None = None, per_row: int = 4,
                  thumb_w: int = 360) -> Path:
    gap, head, cap = 14, 44, 22
    thumb_h = thumb_w * 9 // 16
    rows = max(1, (len(pngs) + per_row - 1) // per_row)
    sheet = Image.new("RGB", (per_row * (thumb_w + gap) + gap, head + rows * (thumb_h + cap + gap) + gap), "#f2f4f6")
    draw = ImageDraw.Draw(sheet)
    draw.text((gap, 10), title, fill="#183342", font=_font(22))
    small = _font(14)
    for i, path in enumerate(pngs):
        x = gap + (i % per_row) * (thumb_w + gap)
        y = head + (i // per_row) * (thumb_h + cap + gap)
        with Image.open(path) as image:
            sheet.paste(image.convert("RGB").resize((thumb_w, thumb_h), Image.LANCZOS), (x, y + cap))
        draw.rectangle((x - 1, y + cap - 1, x + thumb_w, y + cap + thumb_h), outline="#9aa7b0")
        draw.text((x, y + 2), labels[i] if labels else f"{i + 1}", fill="#183342", font=small)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return Path(out)


def write_json(path: Path, value: dict) -> None:
    Path(path).write_text(json.dumps(value, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
