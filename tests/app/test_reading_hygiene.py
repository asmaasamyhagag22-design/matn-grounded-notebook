"""General region rules plus a separately stored real-page development sample."""
import json
from pathlib import Path
import pytest
from matn_app.reading_hygiene import regions,allowed


def test_normal_questions_cannot_retrieve_footnotes_or_references():
    assert allowed('body','What are the findings?')
    for kind in ('footnote','reference_list','toc','acknowledgement','boilerplate'):
        assert not allowed(kind,'What are the main findings?')
    assert allowed('footnote','What does footnote 31 say?')
    assert allowed('reference_list','Which references does the report cite?')


def test_real_page_development_examples():
    root=Path(__file__).resolve().parents[2].parent/'work/qa/real-region-examples.json'
    if not root.exists():pytest.skip('Optional private local development pages are not exported')
    from matn_contracts.structure import DocumentStructure
    from hashlib import sha256
    documents={}
    for row in json.loads(root.read_bytes())['examples']:
        path=Path(row['document']);assert sha256(path.read_bytes()).hexdigest()==row['document_sha256']
        if str(path) not in documents:documents[str(path)]=DocumentStructure.model_validate_json(path.read_bytes())
        assert regions(documents[str(path)])[row['block_id']]==row['expected'],row['text'][:100]


def test_app_handle_filter_preserves_explicit_footnote_questions():
    from matn_app.answer_engine import AppChatEngine
    engine=object.__new__(AppChatEngine)
    engine.region_labels=dict(main='body',note='footnote')
    handles={'s1':dict(text='Agencies should assess operational risks.',citations=[dict(block_id='main')]),
             's2':dict(text='Agencies should review cited prior work.',citations=[dict(block_id='note')])}
    assert list(engine.select_body_handles('What should agencies assess?',handles))==['s1']
    assert set(engine.select_body_handles('What does the footnote say?',handles))=={'s1','s2'}


def test_deterministic_veto_avoids_native_without_changing_earlier_checks():
    from tests.verification.test_rules import doc,request
    from matn_verification.scope import verify_scope
    from matn_verification.contracts import Check
    from matn_app.verification import deterministic_first
    d=doc('According to the Commission, agencies should audit sensitive systems.',
          'Agencies should audit high-risk systems.')
    # Use the same existing request helper and original intervals.
    req=request(d,'Agencies should audit sensitive systems.',indices=(0,1))
    class Native:
        calls=0
        def check(self,text,evidence,target):
            self.calls+=1
            return Check(target=target,layer='L4',verdict='pass')
    old=Native();new=Native()
    before=verify_scope((d,),req,old);after=deterministic_first((d,),req,new)
    assert before.status==after.status and after.status!='verified'
    assert [c for c in before.checks if c.layer!='L4']==[c for c in after.checks if c.layer!='L4']
    assert old.calls>0 and new.calls==0


def test_successful_unit_still_requires_unchanged_native_verification():
    from tests.verification.test_rules import doc,request
    from matn_verification.contracts import Check
    from matn_verification.scope import verify_scope
    from matn_app.verification import deterministic_first
    d=doc('Agencies should assess operational risks.')
    req=request(d,'Agencies should assess operational risks.')
    class Native:
        calls=0
        def check(self,text,evidence,target):
            self.calls+=1
            return Check(target=target,layer='L4',verdict='reject',reasons=('entailment_failed',))
    old=Native();new=Native()
    assert deterministic_first((d,),req,new)==verify_scope((d,),req,old)
    assert new.calls==old.calls>0


def test_heading_is_not_an_antecedent_for_a_lowercase_continuation():
    from tests.verification.test_rules import doc
    from matn_app.reading_hygiene import eligible_handles
    d=doc('Appendix A: Oversight Framework','documentation should include training data and model assumptions.')
    first=d.elements[0].model_copy(update={'role':'heading'})
    d=d.model_copy(update={'elements':(first,*d.elements[1:])})
    refs=[dict(block_id=e.block.block_id,quote=e.block.text) for e in d.elements]
    handles={'s1':dict(text=' '.join(e.block.text for e in d.elements),citations=refs),
             's2':dict(text=d.elements[1].block.text,citations=refs[1:])}
    assert eligible_handles(handles,d)=={}


def test_real_repeated_header_and_list_of_figures_are_not_body_evidence():
    root=Path(__file__).resolve().parents[2].parent/'work/qa/real-region-examples.json'
    if not root.exists():pytest.skip('Optional private local development pages are not exported')
    from matn_contracts.structure import DocumentStructure
    from matn_chat.reliable import build_reliable_handles
    from matn_rag.ingest import prepare
    from matn_app.reading_hygiene import eligible_handles
    paths=list(dict.fromkeys(row['document'] for row in json.loads(root.read_bytes())['examples']))
    gao=DocumentStructure.model_validate_json(Path(paths[0]).read_bytes())
    labels=regions(gao)
    heading=next(e for e in gao.elements if e.block.page_index==81 and e.block.text.startswith('Appendix II: Insights'))
    assert labels[heading.block.block_id]=='boilerplate'
    handles=eligible_handles(build_reliable_handles((gao,),prepare(gao)[1]),gao)
    assert not any(h['text'].startswith('Appendix II: Insights') for h in handles.values())
    wb=DocumentStructure.model_validate_json(Path(paths[1]).read_bytes())
    figures=next(e for e in wb.elements if e.block.page_index==3 and e.block.text.startswith('Figure 1.20'))
    assert regions(wb)[figures.block.block_id]=='toc'


def test_bibliography_continues_across_pages_until_an_appendix_heading():
    from tests.verification.test_rules import doc
    d=doc('References','Smith, A. A cited paper. 2024.','Jones, B. Another cited paper. 2025.','A. Additional Results','The experiment reports a clear result.')
    elements=[]
    for i,e in enumerate(d.elements):
        page=0 if i<2 else 1 if i==2 else 2
        elements.append(e.model_copy(update=dict(block=e.block.model_copy(update=dict(page_index=page)),role='heading' if i in (0,3) else 'body')))
    d=d.model_copy(update=dict(elements=tuple(elements)));labels=regions(d)
    assert labels[elements[2].block.block_id]=='reference_list'
    assert labels[elements[4].block.block_id]=='body'
