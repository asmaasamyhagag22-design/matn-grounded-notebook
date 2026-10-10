"""Offline Linux slide export through LibreOffice and PDFium; Windows keeps COM."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from xml.sax.saxutils import escape

import pypdfium2 as pdfium


def export_deck(pptx: Path, out_dir: Path, pdf: Path, *, width: int = 1280,
                height: int = 720, timeout: float = 1800) -> None:
    executable = shutil.which('libreoffice')
    if not executable:
        raise RuntimeError('LibreOffice Impress is required for Linux PNG/PDF export')
    if width <= 0 or height <= 0:
        raise ValueError('Export dimensions must be positive')
    pptx = pptx.resolve(strict=True)
    pdf.parent.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Retain each isolated profile and conversion output for inspection; never remove old exports.
    work = Path(tempfile.mkdtemp(prefix='lo-export-', dir=pdf.parent.resolve()))
    profile = work / 'profile'
    environment = os.environ.copy()
    if environment.get('MATN_FONT_DIR'):
        fonts = Path(environment['MATN_FONT_DIR']).resolve(strict=True)
        if not fonts.is_dir():
            raise NotADirectoryError(fonts)
        config = work / 'fonts.conf'
        base = environment.get('FONTCONFIG_FILE', '/etc/fonts/fonts.conf')
        config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">'
                          '<fontconfig><include>' + escape(base) + '</include><dir>' +
                          escape(str(fonts)) + '</dir></fontconfig>', encoding='utf-8')
        environment['FONTCONFIG_FILE'] = str(config)
    subprocess.run([executable, f'-env:UserInstallation={profile.as_uri()}', '--headless',
                    '--convert-to', 'pdf:impress_pdf_Export', '--outdir', str(work), str(pptx)],
                   check=True, capture_output=True, text=True, timeout=timeout, env=environment)
    converted = work / (pptx.stem + '.pdf')
    if not converted.is_file() or not converted.stat().st_size:
        raise RuntimeError(f'LibreOffice produced no PDF for {pptx}')
    document = pdfium.PdfDocument(str(converted))
    try:
        count = len(document)
        if not count:
            raise RuntimeError('Exported PDF has no slides')
        old_slides = list(out_dir.glob('slide_*.png'))
        if old_slides:
            archive = Path(tempfile.mkdtemp(prefix='previous-slides-', dir=out_dir))
            for old in old_slides:
                shutil.move(str(old), str(archive / old.name))
        for index in range(count):
            page = document[index]
            bitmap = page.render(scale=width / page.get_width())
            try:
                image = bitmap.to_pil().convert('RGB')
                if abs(image.height - height) > 1:
                    raise ValueError('Requested PNG dimensions do not match the deck aspect ratio')
                image.resize((width, height)).save(out_dir / f'slide_{index + 1:02d}.png')
            finally:
                bitmap.close()
                page.close()
    finally:
        document.close()
    if pdf.exists():
        shutil.move(str(pdf), str(work / ("previous-" + pdf.name)))
    shutil.copyfile(converted, pdf)
    print(f'exported {pptx}: {count} slides')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pptx', action='append', required=True)
    parser.add_argument('--out-dir', action='append', required=True)
    parser.add_argument('--pdf', action='append', required=True)
    parser.add_argument('--width', type=int, default=1280)
    parser.add_argument('--height', type=int, default=720)
    args = parser.parse_args()
    if not len(args.pptx) == len(args.out_dir) == len(args.pdf):
        parser.error('PPTX, PNG folder and PDF counts differ')
    for pptx, out_dir, pdf in zip(args.pptx, args.out_dir, args.pdf):
        export_deck(Path(pptx), Path(out_dir), Path(pdf), width=args.width, height=args.height)


if __name__ == '__main__':
    main()
