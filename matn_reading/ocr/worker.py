"""Reader 1 worker process. Runs inside ``.venv-ocr-rapid``: ``python -m matn_reading.ocr.worker`` from the repo root.

Protocol (one JSON object per line): the worker first prints {"ready": true, ...}; then for every request
{"image": "<png path>"} it prints {"ok": true, "lines": [...], "seconds": ...} or {"ok": false, "error": ...}.
Everything runs inside ``checks.egress_guard.block_egress()``; library output is moved to stderr so stdout carries the
protocol only. Each line has its text, score, quadrilateral box (image pixels) and per-word results.
"""
from __future__ import annotations

import json
import sys
import time
import traceback


def _params(settings: dict) -> dict:
    from rapidocr.utils.typings import EngineType, ModelType, OCRVersion

    enums = {"engine_type": EngineType, "ocr_version": OCRVersion, "model_type": ModelType}
    params = {}
    for key, value in settings["params"].items():
        kind = enums.get(key.rsplit(".", 1)[-1])
        params[key] = kind(value) if kind else value
    return params


def _plain(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _lines(output) -> list[dict]:
    if output is None or output.txts is None:
        return []
    word_results = output.word_results or ()
    words_by_line = word_results if len(word_results) == len(output.txts) else [()] * len(output.txts)
    lines = []
    for text, score, box, words in zip(output.txts, output.scores, output.boxes, words_by_line):
        lines.append({
            "text": text, "score": float(score), "box": _plain(box),
            "words": [{"text": w[0], "score": float(w[1]), "box": _plain(w[2])} for w in (words or ())
                      if len(w) == 3 and w[2] is not None],
        })
    return lines


def main() -> int:
    protocol = sys.stdout
    sys.stdout = sys.stderr                      # any library print goes to stderr, never into the protocol
    from checks.egress_guard import block_egress
    from matn_reading.ocr.reader1 import check_models, load_settings

    settings = load_settings()
    problems = check_models(settings)
    if problems:
        protocol.write(json.dumps({"ready": False, "error": problems}) + "\n")
        protocol.flush()
        return 2
    with block_egress():
        import numpy as np
        import onnxruntime
        from PIL import Image
        from rapidocr import RapidOCR

        engine = RapidOCR(params=_params(settings))
        from matn_reading.ocr.regions import RULES as layout_rules
        from matn_reading.ocr.reader1 import REPO, _sha256
        model = REPO / layout_rules["layout_model"]
        if not model.is_file() or model.stat().st_size != layout_rules["layout_bytes"] or _sha256(model) != layout_rules["layout_sha256"]:
            protocol.write(json.dumps({"ready": False, "error": "layout model missing or hash/size mismatch"}) + "\n")
            protocol.flush()
            return 2
        from rapid_layout import RapidLayout
        layout = RapidLayout(model_type="pp_doc_layoutv2", model_dir_or_path=str(model),
                             conf_thresh=layout_rules["layout_confidence"], engine_cfg={"use_cuda": False, "use_dml": False})
        models = {k: v for k, v in settings["params"].items() if k.endswith(("model_path", "rec_keys_path"))}
        protocol.write(json.dumps({"ready": True, "egress_guard": True, "models": models,
                                   "versions": {"rapidocr": "3.9.2", "onnxruntime": onnxruntime.__version__}}) + "\n")
        protocol.flush()
        for raw in sys.stdin:
            if not raw.strip():
                continue
            try:
                request = json.loads(raw)
                started = time.perf_counter()
                image = np.asarray(Image.open(request["image"]).convert("RGB"))
                output = engine(image)
                regions = []
                layout_seconds = 0.0
                if request.get("layout", True):
                    detected = layout(image)
                    regions = [{"class": name, "bbox": _plain(box), "score": float(score)}
                               for name, box, score in zip(detected.class_names if detected.class_names is not None else (),
                                                          detected.boxes if detected.boxes is not None else (),
                                                          detected.scores if detected.scores is not None else ())]
                    layout_seconds = detected.elapse
                reply = {"layout": regions, "layout_seconds": layout_seconds, "ok": True, "lines": _lines(output), "seconds": round(time.perf_counter() - started, 3),
                         "size": [int(image.shape[1]), int(image.shape[0])]}
            except Exception as error:  # report, never crash silently
                reply = {"ok": False, "error": f"{type(error).__name__}: {error}",
                         "trace": traceback.format_exc()[-2000:]}
            protocol.write(json.dumps(reply, ensure_ascii=False) + "\n")
            protocol.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
