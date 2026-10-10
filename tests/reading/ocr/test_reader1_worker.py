"""Reader 1 worker (RapidOCR PP-OCRv5 in .venv-ocr-rapid): offline, local models only, nothing dropped."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from matn_reading.ocr import reader1

REPO = Path(__file__).resolve().parents[3]
FONT = (Path(r"C:\Windows\Fonts\arial.ttf") if os.name == "nt" else
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))


def test_settings_keep_every_model_inside_the_local_model_folder():
    settings = reader1.load_settings()
    paths = {k: v for k, v in settings["params"].items() if k.endswith(("model_path", "rec_keys_path", "model_root_dir"))}
    assert set(paths) == {"Det.model_path", "Rec.model_path", "Cls.model_path", "Rec.rec_keys_path",
                          "Global.model_root_dir"}
    assert all(Path(p).as_posix().startswith("models/ocr/rapidocr") for p in paths.values())
    assert settings["params"]["Global.text_score"] == 0.0        # never drop low-confidence text
    assert settings["params"]["Global.use_cls"] is False


def test_model_check_refuses_a_file_whose_hash_differs(tmp_path):
    settings = reader1.load_settings()
    (tmp_path / "ch_PP-OCRv5_det_mobile.onnx").write_bytes(b"not the model")
    problems = reader1.check_models(settings, model_dir=tmp_path)
    assert any("ch_PP-OCRv5_det_mobile.onnx" in p and "sha256" in p for p in problems)
    assert any("ppocrv5_dict.txt" in p and "missing" in p for p in problems)


needs_worker = pytest.mark.skipif(
    not reader1.WORKER_PYTHON.is_file() or reader1.check_models(reader1.load_settings()) or not FONT.is_file(),
    reason="reader 1 not installed here (.venv-ocr-rapid, models/ocr/rapidocr/ with matching sha256, fixture font)")


@needs_worker
def test_worker_reads_a_generated_line_offline_from_local_models(tmp_path):
    image = Image.new("L", (1400, 220), 255)
    ImageDraw.Draw(image).text((40, 60), "Total revenue 1,240 in 2020", fill=0, font=ImageFont.truetype(str(FONT), 64))
    path = tmp_path / "line.png"
    image.save(path)
    with reader1.RapidOcrWorker() as worker:
        assert worker.ready["egress_guard"] is True
        assert all(Path(p).as_posix().startswith("models/ocr/rapidocr") for p in worker.ready["models"].values())
        result = worker.read(path)
    text = " ".join(line["text"] for line in result["lines"])
    assert "1,240" in text and "2020" in text
    line = result["lines"][0]
    assert len(line["box"]) == 4 and 0.0 <= line["score"] <= 1.0
    assert any(word["text"] == "1,240" and len(word["box"]) == 4 for word in line["words"])
    json.dumps(result)  # plain JSON all the way
