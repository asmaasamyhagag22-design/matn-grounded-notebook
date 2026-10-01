from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Any

import streamlit as st

from matn_presentation.book_demo import PROJECT_ROOT, load_primary_demo
from matn_presentation.live import generate_live_local


st.set_page_config(page_title="Matn", page_icon="M", layout="wide", initial_sidebar_state="collapsed")

CSS = """
<style>
  :root { --ink:#173038; --muted:#607276; --teal:#176e69; --amber:#b7832f; --line:#d9dfdc; }
  .stApp { background:#fdfcf8; color:var(--ink); }
  .block-container { max-width:1180px; padding-top:2.1rem; padding-bottom:3rem; }
  .matn-header { border-bottom:1px solid var(--line); padding-bottom:1.3rem; margin-bottom:1.5rem; }
  .matn-wordmark { color:var(--teal); font-size:1rem; font-weight:800; letter-spacing:.16em; text-transform:uppercase; }
  .matn-heading { color:var(--ink); font-size:2.55rem; font-weight:720; letter-spacing:-.035em; line-height:1.08; margin:.35rem 0 .45rem; }
  .matn-subheading { color:var(--muted); font-size:1.06rem; margin:0; }
  .section-label { color:var(--teal); font-size:.76rem; font-weight:800; letter-spacing:.12em; text-transform:uppercase; margin-bottom:.45rem; }
  .source-summary { border-left:3px solid var(--amber); padding:.45rem 0 .45rem 1rem; margin:.45rem 0 1rem; }
  .source-title { color:var(--ink); font-size:1.03rem; font-weight:700; }
  .source-detail { color:var(--muted); font-size:.88rem; margin-top:.25rem; }
  .prepared-note { color:var(--muted); font-size:.84rem; margin:.3rem 0 .85rem; }
  .slide-row { padding:.25rem 0 .9rem; border-bottom:1px solid var(--line); margin-bottom:.95rem; }
  .slide-index { color:var(--teal); font-size:.72rem; font-weight:800; letter-spacing:.1em; }
  .slide-title { color:var(--ink); font-size:1.08rem; font-weight:710; margin:.16rem 0 .45rem; }
  .slide-copy { color:#30464c; font-size:.9rem; }
  .slide-source { color:var(--muted); font-size:.76rem; margin-top:.45rem; }
  div[data-testid="stButton"] button[kind="primary"], div[data-testid="stDownloadButton"] button { border-radius:7px; font-weight:680; }
  div[data-testid="stButton"] button[kind="primary"] { background:var(--teal); border-color:var(--teal); }
  div[data-testid="stTabs"] button { font-weight:650; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


@st.cache_resource(show_spinner=False)
def prepared_sample() -> dict[str, Any]:
    return load_primary_demo()


def _book_source_line(pages: list[int]) -> str:
    printed = sorted({page - 22 for page in pages})
    if not printed:
        return "Source: Raschka, Chapter 2"
    if len(printed) == 1:
        return f"Source: Raschka, Chapter 2, p. {printed[0]}"
    return f"Source: Raschka, Chapter 2, pp. {printed[0]}–{printed[-1]}"


def _citation_line(slide: dict[str, Any], current: dict[str, Any]) -> str:
    pages = sorted({page for item in slide.get("citations", []) for page in item["pdf_pages"]})
    if current.get("sample_kind") == "book":
        return _book_source_line(pages)
    if not pages:
        pages = current["plan"]["source_scope"]["pdf_pages"]
    page_text = str(pages[0]) if len(pages) == 1 else f"{pages[0]}–{pages[-1]}"
    return f"Source: selected PDF, physical pp. {page_text}"


def _claim_pages(claim: dict[str, Any]) -> list[int]:
    return sorted({int(item["pdf_page"]) for item in claim.get("evidence", [])})


def _preview_sort_key(path: Path) -> tuple[int, str]:
    digits = "".join(character for character in path.stem if character.isdigit())
    return (int(digits) if digits else 10_000, path.name.lower())


def _render_text_slide(slide: dict[str, Any], current: dict[str, Any]) -> None:
    bullets = "".join(f"<li>{html.escape(item['text'])}</li>" for item in slide["bullets"])
    st.markdown(
        f"""<div class="slide-row">
          <div class="slide-index">SLIDE {slide['slide_number']:02d}</div>
          <div class="slide-title">{html.escape(slide['title'])}</div>
          <ul class="slide-copy">{bullets}</ul>
          <div class="slide-source">{html.escape(_citation_line(slide, current))}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def _set_current(value: dict[str, Any] | None) -> None:
    st.session_state.current = value
    st.session_state.last_error = None


if "current" not in st.session_state:
    st.session_state.current = None
if "last_error" not in st.session_state:
    st.session_state.last_error = None
if "last_source_choice" not in st.session_state:
    st.session_state.last_source_choice = "Sample book chapter"

st.markdown(
    """<div class="matn-header">
      <div class="matn-wordmark">Matn</div>
      <div class="matn-heading">Turn PDF content into a clear, referenced presentation.</div>
      <p class="matn-subheading">Choose a prepared sample or select pages from your own PDF.</p>
    </div>""",
    unsafe_allow_html=True,
)

st.markdown('<div class="section-label">Source</div>', unsafe_allow_html=True)
source_choice = st.radio(
    "Choose a source",
    ["Sample book chapter", "Upload a PDF"],
    horizontal=True,
    label_visibility="collapsed",
)
if source_choice != st.session_state.last_source_choice:
    st.session_state.last_source_choice = source_choice
    _set_current(None)

uploaded = None
start_page = end_page = 1
confirmed = True
if source_choice == "Sample book chapter":
    st.markdown(
        """<div class="source-summary">
          <div class="source-title">Build a Large Language Model (From Scratch)</div>
          <div class="source-detail">Chapter 2 · Tokenizing text and converting tokens into token IDs · printed pp. 21–27</div>
        </div>
        <div class="prepared-note">Prepared sample — opens instantly.</div>""",
        unsafe_allow_html=True,
    )
else:
    uploaded = st.file_uploader("PDF", type=["pdf"], help="Use a text-based PDF. Scanned pages require OCR and are outside this MVP.")
    page_columns = st.columns(2)
    start_page = int(page_columns[0].number_input("Start page", min_value=1, value=1, step=1))
    end_page = int(page_columns[1].number_input("End page", min_value=1, value=1, step=1))
    st.caption("Language: English")
    st.info("New PDFs use local CPU processing. A short selection may take several minutes; larger selections can take much longer.")
    confirmed = st.checkbox("I understand the expected local processing time.")

if st.button("Create presentation", type="primary", width="stretch"):
    if source_choice == "Sample book chapter":
        result = prepared_sample()
        _set_current(result)
        if result.get("sample_kind") == "paper_fallback":
            st.session_state.last_error = "The prepared book sample is not ready, so Matn kept the validated paper fallback active."
    elif uploaded is None:
        st.session_state.last_error = "Choose a PDF before creating the presentation."
    elif end_page < start_page:
        st.session_state.last_error = "The end page must be greater than or equal to the start page."
    elif not confirmed:
        st.session_state.last_error = "Confirm the expected local processing time to continue."
    else:
        upload_bytes = uploaded.getvalue()
        upload_hash = hashlib.sha256(upload_bytes).hexdigest()
        upload_dir = PROJECT_ROOT / "tmp" / "phase04a" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        source_path = upload_dir / f"{upload_hash[:16]}.pdf"
        source_path.write_bytes(upload_bytes)
        run_key = hashlib.sha256(f"{upload_hash}:{start_page}-{end_page}".encode()).hexdigest()[:16]
        run_dir = PROJECT_ROOT / "output" / "phase04a-live-runs" / run_key
        with st.status("Creating the presentation locally", expanded=True) as status:
            def progress(stage: str, state: str) -> None:
                labels = {
                    "Source": "Reading the selected pages",
                    "Grounded summary": "Writing a referenced summary",
                    "Deck plan": "Organizing the presentation",
                    "PowerPoint": "Creating the PowerPoint file",
                }
                status.write(labels.get(stage, stage))

            try:
                result = generate_live_local(
                    source_path,
                    list(range(start_page, end_page + 1)),
                    run_dir,
                    source_filename=uploaded.name,
                    progress=progress,
                )
            except Exception as exc:
                st.session_state.last_error = str(exc)
                status.update(label="Presentation creation stopped", state="error", expanded=True)
            else:
                result["sample_kind"] = "uploaded_pdf"
                result["load_run_details"] = result.get("run_details", {})
                _set_current(result)
                status.update(label="Presentation ready", state="complete", expanded=False)

if st.session_state.last_error:
    st.warning(st.session_state.last_error)

current = st.session_state.current
if current is not None:
    plan = current["plan"]
    claims = current.get("claims", [])
    st.divider()
    overview_tab, presentation_tab, sources_tab = st.tabs(["Overview", "Presentation", "Sources"])

    with overview_tab:
        st.subheader(plan["deck_title"])
        overview_points = current.get("summary_points") or []
        if overview_points:
            for point in overview_points:
                text = point["text"] if isinstance(point, dict) else str(point)
                st.markdown(f"- {text}")
        else:
            for slide in plan["slides"][1:4]:
                for bullet in slide["bullets"][:2]:
                    st.markdown(f"- {bullet['text']}")
        if current.get("sample_kind") == "book":
            st.caption("Prepared and validated before the demonstration. New PDFs use the same local workflow and take longer on CPU.")

    with presentation_tab:
        preview_dir = current.get("preview_dir")
        previews = sorted(Path(preview_dir).glob("*.png"), key=_preview_sort_key) if preview_dir and Path(preview_dir).is_dir() else []
        if previews:
            columns = st.columns(2, gap="large")
            for index, preview in enumerate(previews):
                columns[index % 2].image(str(preview), caption=f"Slide {index + 1}", width="stretch")
        else:
            for slide in plan["slides"]:
                _render_text_slide(slide, current)

    with sources_tab:
        used_ids = {
            claim_id
            for slide in plan["slides"]
            for bullet in slide["bullets"]
            for claim_id in bullet["claim_ids"]
        }
        claim_map = {claim["claim_id"]: claim for claim in claims}
        for claim_id in sorted(used_ids, key=lambda value: (_claim_pages(claim_map[value]) if value in claim_map else [9999], value)):
            claim = claim_map.get(claim_id)
            if not claim:
                continue
            pages = _claim_pages(claim)
            label = _book_source_line(pages) if current.get("sample_kind") == "book" else f"Physical PDF page {', '.join(map(str, pages))}"
            with st.expander(label):
                st.write(claim["claim_text"])
                quotes = [item.get("short_quote", "") for item in claim.get("evidence", []) if item.get("short_quote")]
                if quotes:
                    st.caption("Evidence: " + " | ".join(quotes))

    st.divider()
    pptx_path = Path(current["pptx_path"])
    st.download_button(
        "Download PowerPoint",
        pptx_path.read_bytes(),
        file_name=pptx_path.name,
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        type="primary",
        width="stretch",
    )

    with st.expander("Advanced processing details"):
        provenance = plan.get("provenance", {})
        load_details = current.get("load_run_details", current.get("run_details", {}))
        st.json(
            {
                "prepared_state": load_details.get("prepared_sample", False),
                "model_calls_while_opening": load_details.get("model_generation_calls", 0),
                "preparation_model_calls": provenance.get("model_generation_calls"),
                "cache_status": load_details.get("cache_status", provenance.get("cache_status")),
                "endpoint": provenance.get("inference_endpoint"),
                "cloud_fallback_enabled": provenance.get("cloud_fallback_enabled", False),
                "claim_ids": sorted({claim_id for slide in plan["slides"] for bullet in slide["bullets"] for claim_id in bullet["claim_ids"]}),
                "validation": current.get("validation"),
            }
        )
        plan_bytes = json.dumps(plan, ensure_ascii=False, indent=2).encode("utf-8")
        st.download_button("Download deck plan", plan_bytes, file_name="deck-plan.json", mime="application/json")
