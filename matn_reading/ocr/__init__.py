"""Step 4c OCR route: scanned pages -> contract Blocks with route = ocr, every uncertain number flagged.

Reader 1 is PP-OCRv5 mobile through RapidOCR on onnxruntime, in its own venv (``.venv-ocr-rapid``), called as a
worker process (``worker.py``). Reader 2 is GLM-OCR through Ollama on 127.0.0.1, on number-bearing line crops only.
This package must not import pdfplumber at module level from ``worker.py``: the worker venv does not have it.
"""
