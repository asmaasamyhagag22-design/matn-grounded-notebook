"""Step 4 PDF reading: page triage, digital extraction into matn_contracts Blocks, hidden-text and figure handling.

Permissive stack only: pdfplumber (MIT) and pypdfium2 (Apache-2.0/BSD-3). PyMuPDF (AGPL) must never be imported here;
checks/test_agpl_boundary.py enforces it.
"""
