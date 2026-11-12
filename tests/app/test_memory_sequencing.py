import json

from matn_app.runtime import wait_for_memory
from matn_chat.memory import MIN_AVAILABLE
from tests.app.test_document_quality import Counter

GiB = 1024 ** 3


def test_memory_wait_reports_then_proceeds_without_moving_the_threshold():
    values = iter([GiB, GiB, 2 * GiB])
    seen = []
    waited = wait_for_memory(lambda free, need: seen.append((free, need)), sample=lambda: dict(available_bytes=next(values)),
                             sleep=lambda _: None)
    assert waited == 4 and seen == [(GiB, MIN_AVAILABLE)] * 2


def test_memory_wait_is_bounded_and_leaves_refusal_to_the_guard():
    waited = wait_for_memory(lambda free, need: None, limit=6, sample=lambda: dict(available_bytes=GiB), sleep=lambda _: None)
    assert waited == 6


import pytest


@pytest.mark.parametrize('enough', [False, True])
def test_generator_unloads_between_calls_only_below_guard_threshold(tmp_path, monkeypatch, enough):
    from tests.reading.pdf_fixtures import write_pdf
    from matn_app.answer_profile import load_answer_profile
    from matn_app.evidence import ingest, answer
    from matn_chat.streaming import StreamingGenerator
    from matn_chat.engine import MiniCheck
    from matn_verification.contracts import Check
    events = []
    monkeypatch.setattr('matn_app.runtime.drain_generator', lambda _: events.append('unload'))
    monkeypatch.setattr('eval.chat.token_budget.TokenCounter', Counter)
    monkeypatch.setattr('matn_app.runtime.memory_allows', lambda sample=None: enough)
    # Hermetic retrieval: no real embedder load/unload on the test machine.
    monkeypatch.setattr('matn_app.answer_retrieval.HybridSearch._vectors', lambda self, texts: [[1.0, 0.0]] * len(texts))
    monkeypatch.setattr('matn_app.answer_retrieval.HybridSearch._release', staticmethod(lambda: None))
    monkeypatch.setattr('matn_app.runtime.wait_for_memory', lambda report, **kwargs: events.append('memory_checked') or 0.)
    monkeypatch.setattr('matn_storyboard.runtime.sample_memory', lambda: dict(available_bytes=4 * GiB, l4_worker_rss_bytes=0))
    monkeypatch.setattr(MiniCheck, 'check', lambda self, text, evidence, target: Check(target=target, layer='L4', verdict='pass'))
    pdf = write_pdf(tmp_path / 'source.pdf', b'BT /F1 12 Tf 72 600 Td (Workers should receive training before operating equipment.) Tj ET\n')
    source = ingest(dict(inputs=[str(pdf)], workdir=str(tmp_path / 'ingest'), fake=True))

    def generate(self, body, emit, **kwargs):
        events.append(('generate', body['options']['num_ctx']))
        handle = body['format']['properties']['sentences']['items']['properties']['handles']['items']['enum'][0]
        if 'answer_type' in body['format']['properties']:
            return dict(done=True, done_reason='stop', thinking='', response=json.dumps(dict(answer_type='direct', sentences=[dict(handles=[handle], part=0)])))
        return dict(done=True, done_reason='stop', thinking='',
                    response=json.dumps(dict(sentences=[dict(claim='Workers should receive training before they operate equipment.', handles=[handle], part=0)])))
    monkeypatch.setattr(StreamingGenerator, 'generate_stream', generate)
    result = answer(dict(question='What should workers receive?', catalogs=[source['catalog']], notebooks=[source['notebook']],
                         workdir=str(tmp_path / 'answer'),answer_profile=dict(load_answer_profile(),answer_path='v2')))
    assert result['status'] == 'answered', result['failures']
    events = [e for e in events if e != 'memory_checked']
    generations = [i for i, e in enumerate(events) if e != 'unload']
    assert len(generations) == 2 and ('unload' in events[generations[0]:generations[1]]) is not enough
    assert all(e[1] == 2048 for e in events if e != 'unload')


def test_repair_prompt_explains_failed_checks_in_plain_words():
    from matn_app.answer_engine import compact_payload
    handles = {'s1': dict(source_title='T', text='In some cases, entities may consider scaling the system.')}
    body = compact_payload('What may entities consider?', handles,
                           [dict(slot=0, text='Entities should scale it.', handles=['s1'], failure_codes=['modality_mismatch', 'scope_unknown'])],
                           plan=dict(answer_type='direct', sentences=[dict(part=0, handles=['s1'])]))
    assert 'exact modal or hedge words' in body['prompt'] and 'qualifiers' in body['prompt']
    assert 'Repeating a failed sentence unchanged fails again' in body['prompt']
