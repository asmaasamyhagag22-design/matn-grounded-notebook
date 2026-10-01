# Matn pre-demo checklist

## Before the room opens

- Confirm the book PDF exists under `documents/`. Do not commit or share it from this repository.
- Confirm `output/book-demo/validation-receipt.json` reports `BOOK_DEMO_PREPARED_AND_VISUALLY_VERIFIED`.
- Confirm these files open locally:
  - `output/book-demo/matn-working-with-text-data-v2.pptx`
  - `output/book-demo/matn-working-with-text-data-v2.pdf`
- Keep these local fallbacks available:
  - Research-paper PowerPoint: `output/phase04a-english-demo/matn-phase04a-english-demo.pptx`
  - Research-paper validated bundle: `output/phase04a-english-demo/`

## Launch

```powershell
cd C:\Users\asmaa\Documents\notebooklm\matn
.\.venv\Scripts\python.exe -m streamlit run .\app.py
```

Open the `Local URL` printed by Streamlit. It is normally `http://localhost:8501`; use the printed port if 8501 is already occupied.

## Book-demo clicks and expected values

1. Leave `Sample book chapter` selected and click `Create presentation`.
2. Confirm the line `Prepared sample — opens instantly.` is visible before the click.
3. In `Overview`, confirm the title is `Working with Text Data`.
4. In `Presentation`, confirm all 10 slide previews render and the process arrows point left-to-right.
5. In `Sources`, confirm the citations use Chapter 2 printed pages 21–27.
6. Download the PowerPoint using the primary button.
7. Open `Advanced processing details` only if asked; confirm opening the prepared sample made zero model calls, preparation used seven local calls, the endpoint is loopback, and cloud fallback is disabled.

No audience-facing panel should show an absolute local path, traceback, or debug output.

## Recovery

- If Streamlit fails before opening, stop that attempt and relaunch. If port 8501 is busy, use the `Local URL` Streamlit prints.
- If the download fails, open `output/book-demo/matn-working-with-text-data-v2.pptx` directly. If PowerPoint is unavailable, present the matching PDF.
- If the book bundle is unavailable, Matn automatically falls back to the existing research-paper demo.
- Do not start a cold uploaded-PDF run during the presentation. Use the prepared book sample for the 60–90 second flow.
