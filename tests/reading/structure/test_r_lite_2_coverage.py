"""Flag-only visible coverage; DocumentStructure v2 and count invariants."""
import pytest
from .conftest import record,snapshot
from matn_reading.structure.document import assemble


def test_coverage_records_exclusion_words_and_unlinked_without_changing_citability():
    records=[record('Ordinary visible body.'),record('Possible ordinary prose inside figure.','figure',order=1),record('Hidden body has four words.','text','hidden',order=2)]
    d=assemble(snapshot(records))
    assert d.schema_version==2
    p=d.coverage[0]
    assert p.excluded_words_by_reason['figure_text']==5
    assert p.excluded_words_by_reason['hidden']==5
    assert p.possible_prose_in_figure_count==1
    assert p.possible_prose_in_figure_block_ids==(records[1]['block']['block_id'],)
    assert d.coverage_summary.excluded_words_by_reason==p.excluded_words_by_reason
    assert len([e for e in d.elements if e.citable])==1
    assert all(records[1]['block']['block_id']!=m.block_id for c in d.chunks for m in c.primary)
    bad=d.model_dump();bad['coverage'][0]['possible_prose_in_figure_count']=2
    with pytest.raises(ValueError):type(d).model_validate(bad)


def test_coverage_flags_remaining_same_baseline_fragments():
    rows=[record('The paragraph starts normally.',order=0),record('ledger',order=1)]
    # Distinct source blocks on one justified line, metadata unavailable. Persist
    # paragraph context so this is not a column formed by multiline blocks.
    rows[0]['lines']=[{'words':[{'text':'The','bbox':[10.,30.,25.,41.],'size':11.,'bold':False}]}]
    rows[1]['lines']=[{'words':[{'text':'ledger','bbox':[44.,30.,70.,41.],'size':11.,'bold':False}]}]
    d=assemble(snapshot(rows));p=d.coverage[0]
    assert p.suspected_order_break_count==2
    assert set(p.suspected_order_break_block_ids)=={r['block']['block_id'] for r in rows}
    assert all(e.citable for e in d.elements)


def test_document_coverage_requires_all_pages_and_exact_summary():
    d=assemble(snapshot([record()]))
    assert d.schema_version==2
    missing=d.model_dump();missing['coverage']=[]
    with pytest.raises(ValueError):type(d).model_validate(missing)
    mismatch=d.model_dump();mismatch['coverage_summary']['suspected_order_break_count']=1
    with pytest.raises(ValueError):type(d).model_validate(mismatch)


def test_coverage_cannot_invent_loss_counts_even_with_matching_summary():
    d=assemble(snapshot([record('Excluded visible prose.','figure')]))
    bad=d.model_dump();bad['coverage'][0]['excluded_words_by_reason']={'figure_text':99}
    bad['coverage_summary']['excluded_words_by_reason']={'figure_text':99}
    with pytest.raises(ValueError):type(d).model_validate(bad)
