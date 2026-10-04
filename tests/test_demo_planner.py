"""Demo planner v0 (overnight demo): deterministic rules, the title number check, item abridgment and model checks."""
from __future__ import annotations

from matn_contracts.enums import FactKind, FactStatus, SlideType
from matn_deck.demo_planner import (
    ITEM_MAX,
    DemoDoc,
    abridge,
    chunk,
    item_problems,
    plan_deck,
    slide_key,
    strip_attribution,
    title_problems,
)
from matn_deck.specimen import SPECIMEN_DOC_ID, sample_fact

GROWTH = sample_fact("Sample: adoption grew 18 percent in 2025.",
                     "Sample text: adoption of the sample service rose 18% in 2025.", 2,
                     number=("Sample adoption growth in 2025", "18", "%"))
RURAL = sample_fact("Rural offices may adopt the service more slowly than urban offices.",
                    "Sample text: rural offices may adopt the service more slowly than urban offices.", 7)


def _doc(facts) -> DemoDoc:
    receipts = {}
    for i, f in enumerate(facts):
        receipts[f.fact_id] = {"page_index": 2 + i, "section_path": [f"Section {i % 3}"], "unit_raw": None}
    return DemoDoc(doc_key="sample", doc_id=SPECIMEN_DOC_ID, title="Sample document title", publisher="Sample Office",
                   license="CC BY 4.0", facts=tuple(facts), tables=(), blocks=(), receipts=receipts)


def test_title_numbers_must_be_cited():
    assert title_problems("Adoption grew 18% in 2025", (GROWTH,)) == []
    assert "NUMBER_NOT_CITED:19" in title_problems("Adoption grew 19% in 2025", (GROWTH,))
    assert title_problems("Adoption grew 18% in 2025", (RURAL,))  # numbers cited by another slide do not count


def test_title_spelled_numbers_and_glued_digits_are_checked():
    assert "SPELLED_NUMBER_NOT_CITED:three" in title_problems("Adoption tripled in three regions", (GROWTH,))
    assert "SPELLED_NUMBER_NOT_CITED:doubled" in title_problems("Adoption doubled", (GROWTH,))
    assert "DIGITS_NOT_CITED:3" in title_problems("Adoption rose in Q3", (GROWTH,))


def test_title_length_limit():
    assert any(p.startswith("TOO_LONG") for p in title_problems("x" * 91, (GROWTH,)))


def test_abridge_keeps_words_and_marks_the_cut():
    text = ("The report finds that simplifying and streamlining government processes, along with automating and "
            "digitalizing them, are pre-conditions for better governance results across every governorate.")
    short, cut = abridge(text)
    assert cut and short.endswith("…") and len(short) <= ITEM_MAX
    assert short.startswith("Simplifying")
    assert short[:-1].lower() in text.lower()  # only drops words, never changes them


def test_abridge_leaves_short_text_and_strips_attribution():
    assert abridge("Short sentence.") == ("Short sentence.", False)
    assert strip_attribution("GAO says entities should test AI systems.") == "Entities should test AI systems."


def test_item_problems_keep_hedges_and_reject_new_numbers():
    assert item_problems("Rural offices may adopt more slowly than urban offices.", RURAL) == []
    assert "HEDGE_DROPPED:may" in item_problems("Rural offices adopt more slowly than urban offices.", RURAL)
    assert "DIGITS_NOT_CITED:2" in item_problems("Rural offices may adopt 2x slower.", RURAL)
    assert any(p.startswith("NEW_WORDS") for p in item_problems("Rural offices may badly fail compared with "
                                                                "wealthy urban offices.", RURAL))


def test_chunk_is_even_and_bounded():
    assert [len(g) for g in chunk(list(range(5)))] == [3, 2]
    assert [len(g) for g in chunk(list(range(9)))] == [3, 3, 3]
    assert chunk([]) == []


def _facts():
    points = [sample_fact(f"Sample finding number {w} about the sample service.",
                          f"Sample text: finding number {w} about the sample service is stated here in full.", i)
              for i, w in enumerate(["one", "two", "three", "four", "five", "six"])]
    rec = sample_fact("Sample: extend training to rural offices first.",
                      "Sample text: we recommend extending training to rural offices first.", 10,
                      kind=FactKind.RECOMMENDATION)
    caveat = sample_fact("Sample: the survey covered few regions.",
                         "Sample text: the survey covered few sample regions only.", 11, kind=FactKind.CAVEAT)
    rejected = sample_fact("Sample: a rejected claim.", "Sample text: a rejected claim appears here.", 12,
                           status=FactStatus.REJECTED)
    return points + [rec, caveat, GROWTH, rejected]


def test_plan_follows_the_fixed_skeleton_and_cites_verified_facts_only():
    facts = _facts()
    demo = plan_deck(_doc(facts))
    types = [s.slide_type for s in demo.plan.slides]
    assert types[:3] == [SlideType.TITLE, SlideType.EXECUTIVE_SUMMARY, SlideType.KPI]
    assert types[-2:] == [SlideType.CLOSING, SlideType.SOURCES]
    assert SlideType.FINDING in types and SlideType.IMPLICATIONS in types and SlideType.LIMITATIONS in types
    rejected = facts[-1].fact_id
    cited = {fid for s in demo.plan.slides for i in s.items for fid in i.fact_ids} | {
        fid for s in demo.plan.slides for fid in s.kpi_fact_ids}
    assert rejected not in cited
    kpi = demo.plan.slides[2]
    assert kpi.kpi_fact_ids == (GROWTH.fact_id,)
    for slide in demo.plan.slides:
        assert len(slide.items) <= 4 and len(slide.title) <= 90


def test_plan_is_deterministic():
    doc = _doc(_facts())
    assert plan_deck(doc).plan == plan_deck(doc).plan


def test_cached_model_title_is_rechecked_at_plan_time():
    doc = _doc(_facts())
    first = plan_deck(doc)
    index = next(i for i, s in enumerate(first.plan.slides) if s.slide_type is SlideType.FINDING)
    cited = first.meta[index].fact_ids
    key = "title:" + slide_key(SlideType.FINDING, tuple(cited))
    assert key in first.requests
    good = plan_deck(doc, {key: "Sample findings describe the sample service"})
    bad = plan_deck(doc, {key: "Sample findings describe 81 sample services"})
    assert good.plan.slides[index].title == "Sample findings describe the sample service"
    assert good.meta[index].title_source == "model" and good.meta[index].fact_ids == cited
    assert bad.plan.slides[index].title == first.plan.slides[index].title
    assert any("NUMBER_NOT_CITED:81" in r for r in bad.meta[index].rejections)


def test_kpi_slides_never_take_a_model_title():
    doc = _doc(_facts())
    first = plan_deck(doc)
    assert not any(r.get("slide_type") == "kpi" for r in first.requests.values())
