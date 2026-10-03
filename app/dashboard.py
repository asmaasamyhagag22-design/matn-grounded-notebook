"""متن | Matn — the demo dashboard (overnight demo, Part 2).

Run: run_dashboard.ps1 (or .venv\\Scripts\\python.exe -m streamlit run app/dashboard.py). It binds 127.0.0.1 only
(.streamlit/config.toml) and reads everything from the local cache (out/demo/, design/templates/, out/gallery/), so it
works fully offline even when PowerPoint or Ollama are unavailable. "Generate live" re-renders through the renderer
and PowerPoint; on any failure it falls back to the cached deck. No external URLs, fonts or CDNs.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from matn_deck import demo_data as data  # noqa: E402

APP_NAME = "متن | Matn"
TAGLINE = "من المستند للعرض، وكل رقم بمصدره"
DOC_NAMES = {
    "wb_eem_2021_12": "البنك الدولي: مرصد الاقتصاد المصري، ديسمبر 2021",
    "gao_21_519sp": "GAO: إطار المساءلة للذكاء الاصطناعي",
    "2601.14525v1": "ورقة بحثية: Execution-Grounded AI Research",
}
PAGES = ["الرئيسية", "معرض القوالب", "اعمل عرض", "نفس الحقايق، أي قالب", "الإيصالات", "الجودة", "الطريق"]

CSS = """
<style>
  :root { --matn-ink:#14232b; --matn-muted:#5b6b70; --matn-teal:#0f6b66; --matn-gold:#b98a2e; --matn-line:#dfe4e2; }
  .rtl { direction: rtl; text-align: right; font-family: "Segoe UI", Tahoma, "Arial", sans-serif; }
  .rtl * { direction: rtl; text-align: right; }
  .matn-hero { padding: .4rem 0 1rem 0; border-bottom: 1px solid var(--matn-line); margin-bottom: 1rem; }
  .matn-name { font-size: 2.6rem; font-weight: 800; color: var(--matn-teal); line-height: 1.1; }
  .matn-tag { font-size: 1.25rem; color: var(--matn-muted); margin-top: .3rem; }
  .matn-story { font-size: 1.1rem; line-height: 1.9; }
  .pill { display:inline-block; padding:.45rem .9rem; margin:.25rem; border-radius:999px; font-weight:600;
          background:#e8f2f0; color:#0b4f4b; border:1px solid #bcd9d5; }
  .badge { display:inline-block; padding:.1rem .55rem; margin:0 .2rem; border-radius:6px; font-size:.8rem;
           font-weight:700; background:#eef0f0; color:#33454b; }
  .badge.dark { background:#1d2a33; color:#f1e6c8; }
  .badge.default { background:var(--matn-gold); color:#fff; }
  .badge.soon { background:#f3efe4; color:#8a6a1f; }
  .quote { border-right: 4px solid var(--matn-gold); padding: .4rem .8rem; background: #faf7ef; color:#2b2b2b;
           font-style: italic; direction:ltr; text-align:left; }
  .claim { font-weight: 600; direction:ltr; text-align:left; }
  .kpi { font-size: 1.8rem; font-weight: 800; color: var(--matn-teal); direction:ltr; text-align:left; }
  .ok { color:#16794a; font-weight:700; }
  .bad { color:#a12a2a; font-weight:700; }
  .small { color: var(--matn-muted); font-size:.85rem; }
</style>
"""


def rtl(text: str, cls: str = "") -> None:
    """An Arabic text block, right-to-left; widgets keep their own layout."""
    st.markdown(f'<div class="rtl {cls}">{text}</div>', unsafe_allow_html=True)


def esc(text: object) -> str:
    return html.escape(str(text))


@st.cache_data(show_spinner=False)
def _manifest() -> dict:
    return data.load_manifest()


@st.cache_data(show_spinner=False)
def _slides(pptx: str, mtime: float) -> list:
    return data.deck_slides(Path(pptx))


@st.cache_data(show_spinner=False)
def _numbers(pptx: str, mtime: float) -> list[str]:
    return data.deck_numbers(Path(pptx))


def slides_of(pptx: Path):
    return _slides(str(pptx), pptx.stat().st_mtime)


def numbers_of(pptx: Path) -> list[str]:
    return _numbers(str(pptx), pptx.stat().st_mtime)


def doc_label(key: str) -> str:
    return DOC_NAMES.get(key, key)


def template_label(template_id: str) -> str:
    entry = next((e for e in data.gallery_entries() if e["id"] == template_id), None)
    if entry is None:
        return template_id
    mode = "داكن" if entry["mode"] == "dark" else "فاتح"
    star = " ★ الافتراضي" if entry["default"] else ""
    return f"{entry.get('name_ar') or template_id} · {entry['name_en']} ({mode}){star}"


def cached_decks(doc_key: str) -> dict:
    return _manifest().get("documents", {}).get(doc_key, {}).get("decks", {})


def slide_strip(pngs: list[Path], key: str) -> None:
    """A large view of one slide plus a strip of every slide."""
    if not pngs:
        st.info("مفيش صور للشرايح دي في الـ cache (PowerPoint export ناقص). الـ PPTX موجود للتحميل.")
        return
    index = st.slider("الشريحة", 1, len(pngs), 1, key=f"{key}-slider") - 1
    st.image(str(pngs[index]), width="stretch")
    cols = st.columns(6)
    for i, png in enumerate(pngs):
        cols[i % 6].image(str(png), caption=f"{i + 1}", width="stretch")


def download_buttons(deck: dict, name: str, key: str) -> None:
    c1, c2 = st.columns(2)
    pptx = data.rel(deck["pptx"])
    if pptx.is_file():
        c1.download_button("⬇ تحميل PPTX (قابل للتعديل)", pptx.read_bytes(), file_name=f"{name}.pptx",
                           mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                           key=f"{key}-pptx", width="stretch")
    if deck.get("pdf") and data.rel(deck["pdf"]).is_file():
        c2.download_button("⬇ تحميل PDF", data.rel(deck["pdf"]).read_bytes(), file_name=f"{name}.pdf",
                           mime="application/pdf", key=f"{key}-pdf", width="stretch")
    else:
        c2.caption("PDF مش موجود في الـ cache")


# ---- pages ----------------------------------------------------------------------------------------------------------

def page_home() -> None:
    rtl(f'<div class="matn-hero"><div class="matn-name">{APP_NAME}</div>'
        f'<div class="matn-tag">{TAGLINE}</div></div>')
    rtl('<div class="matn-story">'
        '١. بتدّي متن مستند PDF، بيطلع منه الحقايق المهمة، وكل حقيقة معاها الاقتباس والصفحة.<br>'
        '٢. بتختار قالب من المعرض، ومتن بيبني عرض PowerPoint قابل للتعديل: الكود هو اللي بينقل الأرقام، مش الموديل.<br>'
        '٣. أي رقم على أي شريحة تقدر ترجعه لمكانه في المستند في ثانية: ده "الإيصال".</div>')
    rtl('<span class="pill">🔒 أوفلاين بالكامل</span><span class="pill">✔ أرقام متحقق منها</span>'
        '<span class="pill">📝 PPTX قابل للتعديل</span><span class="pill">🎨 معرض قوالب</span>')
    s = data.stats()
    st.write("")
    c = st.columns(4)
    c[0].metric("قوالب في المعرض (Templates)", s["templates"])
    c[1].metric("حقايق متحقق منها (Verified facts)", s["verified_facts"])
    c[2].metric("عروض جاهزة (Demo decks)", s["decks"])
    tests = s["tests"]
    c[3].metric("اختبارات ناجحة (Tests)", tests.get("passed", "—"),
                help=f"آخر تشغيل مسجل للـ full suite: {tests.get('passed')} passed, {tests.get('skipped', 0)} "
                     f"skipped, {tests.get('failed', 0)} failed ({tests.get('source', '')})")
    rtl('<p class="small">الأرقام دي بتتقري من الـ repo نفسه وقت فتح الصفحة. الحقايق في الديمو جاية من '
        'المرجع المتحقق منه (dev gold) لـ 3 مستندات عامة؛ الـ pipeline اللي بيطلّع الحقايق من الـ PDF بالموديل '
        'هي المرحلة الجاية.</p>')


def page_gallery() -> None:
    rtl("<h2>معرض القوالب</h2>")
    entries = data.gallery_entries()
    c1, c2 = st.columns(2)
    families = c1.multiselect("العيلة (family)", sorted({e["family"] for e in entries}),
                              default=sorted({e["family"] for e in entries}))
    mode = c2.radio("الوضع (mode)", ["الكل", "داكن", "فاتح"], horizontal=True)
    wanted = {"الكل": {"dark", "light"}, "داكن": {"dark"}, "فاتح": {"light"}}[mode]
    shown = [e for e in entries if e["family"] in families and e["mode"] in wanted]
    rtl(f'<p class="small">{len(shown)} قالب. القوالب الداكنة الأول، و Modulo هو الافتراضي. '
        'كل قالب هنا عدّى بوابة الجمال (beauty gate ≥ 0.90) من غير أي hard violation.</p>')
    cols = st.columns(3)
    for i, e in enumerate(shown):
        with cols[i % 3]:
            if e["thumbnail"].is_file():
                st.image(str(e["thumbnail"]), width="stretch")
            badges = (f'<span class="badge {"dark" if e["mode"] == "dark" else ""}">'
                      f'{"داكن" if e["mode"] == "dark" else "فاتح"}</span>'
                      f'<span class="badge">{esc(e["family"])}</span>'
                      + ('<span class="badge default">★ الافتراضي</span>' if e["default"] else ""))
            rtl(f'<b>{esc(e.get("name_ar") or "")}</b> · <span dir="ltr">{esc(e["name_en"])}</span><br>{badges}<br>'
                f'<span class="small" dir="ltr">{esc(e["mood"])} — {esc(e["audience"])}</span>')
            st.write("")
    excluded = data.excluded_templates()
    if excluded:
        with st.expander("قوالب اتشالت من المعرض وليه"):
            for x in excluded:
                st.markdown(f"- `{x['id']}`: {x['reason']}")


def _pick_doc(key: str) -> str:
    found = _manifest().get("documents", {})
    docs = [k for k in DOC_NAMES if k in found] + [k for k in found if k not in DOC_NAMES]
    return st.selectbox("المستند (dev فقط)", docs, format_func=doc_label, key=f"{key}-doc")


def page_make() -> None:
    rtl("<h2>اعمل عرض</h2>")
    doc_key = _pick_doc("make")
    decks = cached_decks(doc_key)
    all_ids = [e["id"] for e in data.gallery_entries()]
    options = list(decks) + [t for t in all_ids if t not in decks]
    template_id = st.selectbox("القالب", options, format_func=lambda t: template_label(t) +
                               ("" if t in decks else " — مش في الـ cache (Generate live)"), key="make-template")
    audience = st.radio("الجمهور", ["القيادة (Leadership)", "تقني (Technical) — قريباً", "محاضرة (Lecture) — قريباً"],
                        horizontal=True, key="make-audience")
    if "قريباً" in audience:
        st.info("قريباً: النسخة دي بتبني عرض القيادة بس. اختيار الجمهور هيغيّر الـ skeleton في Step 9.")
    live_key = f"live::{doc_key}::{template_id}"
    if st.button("⚡ Generate live", help="يعيد الرسم بالـ renderer دلوقتي؛ لو أي حاجة فشلت بيرجع للـ cache"):
        with st.spinner("بنرسم العرض بالـ renderer و PowerPoint..."):
            st.session_state[live_key] = generate_live(doc_key, template_id)
    live = st.session_state.get(live_key)
    deck = None
    if live and live.get("ok"):
        st.success(f"اترسم live في {live['seconds']:.1f} ثانية: {live['slides']} شريحة، "
                   f"{live['overflows']} overflow." + ("" if live["pngs"] else " (PowerPoint export فشل؛ الصور من الـ cache)"))
        deck = live["deck"]
    elif live and not live.get("ok"):
        st.warning(f"الرسم live فشل ({live.get('error')}). بنعرض النسخة المحفوظة في الـ cache.")
    if deck is None:
        deck = decks.get(template_id)
    if deck is None:
        st.info("القالب ده مش في الـ cache. دوسي Generate live.")
        return
    pngs = [data.rel(p) for p in deck.get("pngs", [])]
    if live and live.get("ok") and not live["pngs"] and template_id in decks:
        pngs = [data.rel(p) for p in decks[template_id].get("pngs", [])]
    slide_strip(pngs, "make")
    download_buttons(deck, f"matn_{doc_key}_{template_id}", "make")


def generate_live(doc_key: str, template_id: str) -> dict:
    """Render now through the renderer (+ PowerPoint export); never raises: failures return ok=False."""
    import time  # noqa: PLC0415

    from matn_deck import demo_build  # noqa: PLC0415
    from matn_deck.demo_planner import load_demo_doc, plan_deck  # noqa: PLC0415

    started = time.monotonic()
    try:
        doc = load_demo_doc(data.OUT / "facts" / f"{doc_key}.json")
        demo = plan_deck(doc)  # deterministic text only, like the cached decks (demo_build default)
        out_dir = data.OUT / "live" / doc_key / template_id
        record = demo_build.render_deck(doc, demo, template_id, out_dir)
        ok, _log = demo_build.export([out_dir], timeout=300)
        pngs = sorted((out_dir / "png").glob("slide_*.png")) if ok else []
        deck = {"pptx": (out_dir / "deck.pptx").relative_to(data.ROOT).as_posix(),
                "pdf": (out_dir / "deck.pdf").relative_to(data.ROOT).as_posix() if ok else None,
                "pngs": [p.relative_to(data.ROOT).as_posix() for p in pngs]}
        return {"ok": True, "deck": deck, "pngs": bool(pngs), "slides": record["slides"],
                "overflows": len(record["overflows"]), "seconds": time.monotonic() - started}
    except Exception as exc:  # noqa: BLE001 - the demo must fall back to the cache on any failure
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}


def page_same() -> None:
    rtl("<h2>نفس الحقايق، أي قالب</h2>")
    rtl('<p class="small">نفس الـ deck plan بيترسم في قالبين. التصميم بيتغير، والمحتوى والأرقام لأ.</p>')
    doc_key = _pick_doc("same")
    decks = cached_decks(doc_key)
    if len(decks) < 2:
        st.info("المستند ده محتاج قالبين على الأقل في الـ cache.")
        return
    ids = list(decks)
    c1, c2 = st.columns(2)
    a = c1.selectbox("القالب الأول", ids, index=0, format_func=template_label, key="same-a")
    b = c2.selectbox("القالب التاني", ids, index=1, format_func=template_label, key="same-b")
    pa, pb = data.rel(decks[a]["pptx"]), data.rel(decks[b]["pptx"])
    na, nb = numbers_of(pa), numbers_of(pb)
    fa, fb = data.deck_fact_ids(pa), data.deck_fact_ids(pb)
    same_numbers, same_facts = na == nb, fa == fb
    rtl(f'<p>الأرقام في الجمل والعناوين والـ KPIs: <span class="{"ok" if same_numbers else "bad"}">'
        f'{"متطابقة ✔" if same_numbers else "مختلفة ✘"}</span> ({len(na)} رقم) · الحقايق المستشهد بيها: '
        f'<span class="{"ok" if same_facts else "bad"}">{"متطابقة ✔" if same_facts else "مختلفة ✘"}</span> '
        f'({len(fa)} حقيقة)</p>'
        '<p class="small">بعض الـ layouts بتعرض اقتباس الحقيقة الأولى بالحرف في كارت جنبي، فالاقتباس ده مش داخل في '
        'المقارنة (موجود في الإيصالات). عدد الشرايح ممكن يختلف لأن القالب الأضيق بيقسم الشريحة لاتنين، من غير ما يقص '
        'أي حقيقة.</p>')
    if not same_numbers:
        st.write({"only in A": sorted(set(na) - set(nb)), "only in B": sorted(set(nb) - set(na))})
    with st.expander("الأرقام اللي اتقارنت"):
        st.code(" · ".join(na))
    left, right = st.columns(2)
    for col, tid in ((left, a), (right, b)):
        with col:
            st.caption(template_label(tid) + f" — {len(decks[tid]['pngs'])} شريحة")
            for png in decks[tid]["pngs"]:
                st.image(str(data.rel(png)), width="stretch")


def page_receipts() -> None:
    rtl("<h2>الإيصالات</h2>")
    rtl('<p class="small">كل رقم وكل جملة على الشريحة، ومعاها الاقتباس بالحرف، ورقم الصفحة، وصورة الصفحة '
        'نفسها مع تظليل الاقتباس. الصور اتعملت مسبقاً من الـ PDF (eval tooling)، والـ dashboard مبيفتحش الـ PDF.</p>')
    doc_key = _pick_doc("receipts")
    decks = cached_decks(doc_key)
    if not decks:
        st.info("مفيش deck في الـ cache.")
        return
    template_id = st.selectbox("القالب", list(decks), format_func=template_label, key="receipts-template")
    deck = decks[template_id]
    slides = slides_of(data.rel(deck["pptx"]))
    cited = [s for s in slides if s.fact_ids]
    all_ids = sorted({f for s in slides for f in s.fact_ids})
    receipts = {r["fact_id"]: r for r in data.receipts_for(doc_key, all_ids)}
    verified = sum(r["status"] == "verified" for r in receipts.values())
    rtl(f'<p>الـ deck ده بيستشهد بـ <b>{len(all_ids)}</b> حقيقة؛ <span class="ok">{verified} منهم verified</span> '
        f'(الاقتباس موجود في صفحته بالظبط، وكل رقم في الجملة موجود في الاقتباس).</p>')
    first_kpi = next((i for i, s in enumerate(cited) if s.layout.startswith("matn:kpi")), 0)
    number = st.selectbox("الشريحة", [s.number for s in cited], index=first_kpi,
                          format_func=lambda n: f"{n}: {next(s.title for s in slides if s.number == n)}",
                          key="receipts-slide")
    slide = next(s for s in slides if s.number == number)
    pngs = deck.get("pngs", [])
    left, right = st.columns([5, 6])
    with left:
        if number - 1 < len(pngs):
            st.image(str(data.rel(pngs[number - 1])), width="stretch")
    with right:
        for fid in slide.fact_ids:
            r = receipts.get(fid)
            if r is None:
                continue
            page = f"صفحة PDF {r['physical_page']}" + (f" · رقم الصفحة المطبوع {esc(r['page_label'])}"
                                                       if r["page_label"] else "")
            status = '<span class="ok">✔ verified</span>' if r["status"] == "verified" else \
                f'<span class="bad">{esc(r["status"])}</span>'
            value = (f'<div class="kpi">{esc(r["value"])}{esc(" " + r["unit"] if r["unit"] and r["unit"] != "%" else (r["unit"] or ""))}</div>'
                     if r["value"] else "")
            rtl(f'{value}<div class="claim">{esc(r["claim"])}</div>'
                f'<div class="quote">“{esc(r["quote"])}”</div>'
                f'<div class="small">{page} · {status} · <span dir="ltr">{esc(r["section"])}</span></div>')
            if r["crop_png"] and r["crop_png"].is_file():
                st.image(str(r["crop_png"]), width="stretch")
            if r["page_png"] and r["page_png"].is_file():
                with st.expander(f"الصفحة كاملة (PDF p. {r['physical_page']})"):
                    st.image(str(r["page_png"]), width="stretch")
            st.divider()


def page_quality() -> None:
    rtl("<h2>الجودة</h2>")
    rtl('<p><b>بصراحة:</b> الـ beauty score بيقيس إن اختيار الـ layout أحسن من الاختيار العشوائي على نفس المحتوى '
        '(مسافات، توازن، تدرّج، كثافة)؛ مش مقياس مطلق للجمال، ولا بيحكم على الألوان أو الذوق. '
        'الـ hard violations (overflow، تداخل، contrast) لازم تكون صفر.</p>')
    rows = data.scores_table()
    if rows:
        keep = ["Template", "Beauty", "Hard", "Splits", "Sizes", "2b-style", "Arbitrary", "Gate"]
        st.dataframe([{k: r.get(k) for k in keep if k in r} for r in rows], width="stretch",
                     hide_index=True)
    else:
        st.info("out/gallery/scores.md مش موجود.")
    rtl("<h3>التطور: 2b ← 2c ← 2c.1 ← 2d ← تلميع الليلة</h3>")
    for step, path, caption in data.evolution_images():
        rtl(f"<b>{esc(step)}</b> · {esc(caption)}")
        st.image(str(path), width="stretch")


def page_roadmap() -> None:
    rtl("<h2>الطريق</h2>")
    rtl("""
<h4>✔ اتعمل</h4>
<ul>
<li>Step 0: الأساس: قواعد، git hooks، مرجع تقييم مجمّد لـ 5 مستندات عامة (3 dev، 2 test مقفولين).</li>
<li>Step 1: الـ contracts: Pydantic models، IDs ثابتة، فحص الأرقام ضد الاقتباس.</li>
<li>Step 2 → 2d: معرض قوالب، generate-and-score للـ layout، 16 قالب عدّوا بوابة الجمال.</li>
<li>الديمو ده: عروض حقيقية من الحقايق المتحقق منها، وإيصال لكل رقم.</li>
</ul>
<h4>◐ دلوقتي</h4>
<ul>
<li>العروض النهارده مبنية من <b>حقايق مرجعية متحقق منها</b> (dev gold)، مش من الموديل.</li>
<li>Step 2d.2: أيقونات للكروت.</li>
</ul>
<h4>→ الجاي (Steps 3-10)</h4>
<ul>
<li>Step 3: تقسيم المستند لأقسام. Step 4: الموديل يطلّع الحقايق (JSON، أوفلاين).</li>
<li>Step 5: فحص كل حقيقة بالكود. Step 6: تجميع وترتيب. Step 7: الملخص.</li>
<li>Step 8: مراجعة بشرية للحقايق. Step 9: الموديل يخطط العرض (وكل عنوان يتفحص). Step 10: القوالب على جهاز الإنتاج.</li>
<li>بعدها: العربي (RTL)، والـ infographic، والرسوم التحليلية.</li>
</ul>
<p class="small"><b>المرحلة الجاية هي الـ pipeline اللي بيعمل الملخص من الـ PDF بالموديل.</b>
النهارده الحقايق جاية من المرجع، فالديمو بيوري الشكل والتحقق والإيصالات، مش جودة الاستخراج بالموديل.</p>
""")


PAGE_FUNCS = {
    "الرئيسية": page_home, "معرض القوالب": page_gallery, "اعمل عرض": page_make, "نفس الحقايق، أي قالب": page_same,
    "الإيصالات": page_receipts, "الجودة": page_quality, "الطريق": page_roadmap,
}


def main() -> None:
    st.set_page_config(page_title="Matn", page_icon="📄", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    with st.sidebar:
        rtl(f'<div class="matn-name" style="font-size:1.6rem">{APP_NAME}</div><div class="small">{TAGLINE}</div>')
        page = st.radio("الصفحة", PAGES, key="page")
        rtl('<p class="small">🔒 شغال على 127.0.0.1 بس، من غير إنترنت.</p>')
    PAGE_FUNCS[page]()


main()
