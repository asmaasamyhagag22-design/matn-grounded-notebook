"""Actual local reader integration: image PDF, verified real scan, PowerShell wrapper."""
import os
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont
import pypdfium2 as pdfium

from eval.reading.real.verify import require_verified
from matn_reading.cli import run
from matn_reading.ocr.glm import GlmRead
from .pdf_fixtures import write_pdf
from .test_cli import DIGITAL

REPO=Path(__file__).resolve().parents[2]


class FailedReader2:
    def read_line(self,png):
        return GlmRead(None,False,0,"intentional-offline-test-failure","simulated second-reader failure")


def check_outputs(folder):
    assert (folder / "report.md").is_file()
    assert (folder / "blocks.jsonl").stat().st_size>0
    assert list((folder / "overlays").glob("*.png"))


def test_generated_image_pdf_real_worker_marks_failed_second_read(tmp_path):
    image=Image.new("RGB",(2550,3300),"white")
    ImageDraw.Draw(image).text((300,400),"Staff 1,240 million in 2020",font=ImageFont.truetype("arial.ttf" if os.name == "nt" else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",50),fill="black")
    pdf=tmp_path / "image-only.pdf";image.save(pdf,"PDF",resolution=300)
    out=tmp_path / "image-read"
    summary=run(pdf,out,glm=FailedReader2())
    check_outputs(out)
    assert summary["ocr_pages"]==[0]
    assert "⚠[uncertain number:" in (out / "reading.md").read_text(encoding="utf-8")
    assert not summary["ocr_failed_pages"]


def test_verified_real_scan_and_powershell_wrapper(tmp_path):
    source=require_verified("nbs_circular_31_e4_1956")
    opened=pdfium.PdfDocument(str(source));single=pdfium.PdfDocument.new()
    single.import_pages(opened,[7]);pdf=tmp_path / "nbs-p7.pdf";single.save(str(pdf));single.close();opened.close()
    out=tmp_path / "real-read";summary=run(pdf,out)
    check_outputs(out)
    assert summary["ocr_pages"]==[0] and summary["numbers_flagged"]>0
    assert "⚠[" in (out / "reading.md").read_text(encoding="utf-8")
    digital=write_pdf(tmp_path / "digital.pdf",DIGITAL)
    wrapper_out=tmp_path / "wrapper-read"
    if os.name == "nt":
        shell=shutil.which("pwsh") or shutil.which("powershell")
        assert shell, "An installed PowerShell is required to test read_pdf.ps1"
        command=[shell,"-NoProfile","-File",str(REPO / "read_pdf.ps1"),str(digital),"-Out",str(wrapper_out)]
    else:
        command=["bash",str(REPO / "read_pdf.sh"),str(digital),"--out",str(wrapper_out)]
    result=subprocess.run(command,cwd=REPO,capture_output=True,
                          env={**os.environ,"PYTHONUTF8":"1"},timeout=180)
    assert result.returncode==0, result.stdout+result.stderr
    check_outputs(wrapper_out)
    assert str(wrapper_out).encode() in result.stdout
