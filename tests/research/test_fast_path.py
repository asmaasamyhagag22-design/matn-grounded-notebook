"""Matn v2 path with declared fixtures and Fake L4 only; no real network, provider or model calls."""
import json
import time

import pytest

from matn_research import workflow
from matn_research.fast import run_v2, code_draft, select_payload, CONFIG, PLAN_PROMPT, SELECT_PROMPT
from matn_research.shortlist import shortlist, near_duplicate
from eval.research.fixtures import BRIEF, FakeNative, TEXTS, LABEL

URLS = ['https://www.example.gov/guide', 'https://shop.example.com/offer', 'https://fixture.example.org/copy']
HTML = '<html><body><main>' + ''.join('<p>' + t + '</p>' for t in TEXTS) + '</main></body></html>'
VENDOR = ('<html><body><main><p>Tree shade should be evaluated at the intended seating area.</p>'
          '<p>Book a free consultation with our arborists today.</p></main></body></html>')


class Provider:
    name = 'fixture-search'
    def __init__(self, fail=()):
        self.calls = []; self.fail = fail
    def search(self, query):
        self.calls.append(query)
        if any(f in query for f in self.fail):
            raise ConnectionResetError('fixture transport failure')
        return dict(provider=self.name, query=query, at=time.time(), response=dict(results=[
            dict(url=u, content='SNIPPET_NOT_EVIDENCE') for u in URLS]))


def fetch(url, **kwargs):
    body = VENDOR if 'shop' in url else HTML
    return dict(body=body.encode(), final_url=url, content_type='text/html; charset=utf-8', fetched_at=time.time(), redirects=[])


class Generator:
    """Plan: four axes. Select: the candidate equal to TEXTS[i] for axis i (fit full). Synthesis: none."""
    def __init__(self, fail_select=0, pick_none=(), two=False):
        self.calls = []; self.fail_select = fail_select; self.pick_none = pick_none; self.two = two
    def generate(self, body):
        self.calls.append(body)
        props = body['format']['properties']
        if 'facets' in props:
            value = dict(facets=[dict(id='axis' + str(i), label=label,
                         success='Explain ' + word + ' from the material read', searches=[label.lower()])
                         for i, (label, word) in enumerate([('Shade', 'shade'), ('Soil', 'soil'), ('Care', 'watering care'),
                                                           ('Evaluation', 'how shade is evaluated')])])
        elif body['prompt'].startswith(SELECT_PROMPT[:40]):
            if self.fail_select:
                self.fail_select -= 1
                raise ConnectionResetError('RemoteDisconnected fixture')
            data = json.loads(body['prompt'].split('\n', 1)[1]); value = {}
            for r in data['requirements']:
                i = int(r['id'].removeprefix('r')) - 1
                letters = [k for k, t in r['candidates'].items() if t.strip() == TEXTS[i]]
                if self.two:
                    letters = (letters + [k for k in r['candidates'] if k not in letters])[:2]
                axis = 'axis' + str(i)
                value[r['id']] = dict(pick=[] if axis in self.pick_none else letters[:2 if self.two else 1],
                                      fit='none' if axis in self.pick_none or not letters else 'full')
        else:
            value = dict(sentences=[])
        return dict(done=True, done_reason='stop', response=json.dumps(value), thinking='')


def journey(tmp_path, monkeypatch, provider=None, generator=None, **config):
    monkeypatch.setitem(workflow.FEATURES, 'context_display', False)
    monkeypatch.setitem(workflow.FEATURES, 'fast_path', False)
    return run_v2(tmp_path, BRIEF, provider=provider or Provider(), generator=generator or Generator(), native=FakeNative(),
                  counter=lambda t: len(t) // 4, fetch=fetch, classification=LABEL, config=config)


def test_one_plan_and_one_selection_call_then_code_writer(tmp_path, monkeypatch):
    g = Generator()
    outcome = journey(tmp_path, monkeypatch, generator=g, gap=False, synthesis=False)
    assert outcome['status'] == 'AI_REVIEW_REQUIRED' and outcome['verified_units'] == 4
    assert [c['prompt'][:30] for c in g.calls] == [PLAN_PROMPT[:30], SELECT_PROMPT[:30]]
    draft = json.loads((tmp_path / 'code-draft-0.json').read_bytes())
    assert draft['writer'] == 'code-verbatim-v1'
    assert sorted(u['text'] for s in draft['draft']['slides'] for u in s['units']) == sorted(TEXTS)
    state = json.loads((tmp_path / 'state.json').read_bytes())
    assert state['first_verified_seconds'] is not None and (tmp_path / 'index.html').exists()


def test_selection_output_is_ids_and_enums_only(tmp_path, monkeypatch):
    journey(tmp_path, monkeypatch, gap=False, synthesis=False)
    request = json.loads((tmp_path / 'payloads' / 'select-0.json').read_bytes())['request']
    branch = next(iter(request['format']['properties'].values()))
    assert set(branch['properties']) == {'pick', 'fit'} and branch['properties']['pick']['items']['enum'][0] == 'a'
    assert request['options']['num_ctx'] == 2048 and request['options']['num_predict'] == 256
    # Fixed instructions first, byte-identical; variable data after the first newline.
    assert request['prompt'].split('\n', 1)[0] + '\n' == SELECT_PROMPT


def test_vendor_source_is_shortlisted_last_not_excluded(tmp_path, monkeypatch):
    journey(tmp_path, monkeypatch, gap=False, synthesis=False, k=3)
    sl = json.loads((tmp_path / 'select-0-shortlist.json').read_bytes())
    assert 'commercial-vendor' in sl['source_types'].values()
    ranking = sl['ranking']['axis3']
    vendor = [s for s in ranking if sl['source_types'][s] == 'commercial-vendor']
    assert vendor  # never hard-excluded


def test_search_failure_and_transport_retry_degrade_not_fail(tmp_path, monkeypatch):
    g = Generator(fail_select=1)
    outcome = journey(tmp_path, monkeypatch, provider=Provider(fail=('soil',)), generator=g, gap=False, synthesis=False)
    state = json.loads((tmp_path / 'state.json').read_bytes())
    assert state['retries'][0]['job'] == 'select-0' and state['retries'][0]['failed']['status'] == 'failed'
    assert state['search_errors'] and outcome['verified_units'] == 4


def test_selection_failure_after_retry_still_writes_a_page(tmp_path, monkeypatch):
    outcome = journey(tmp_path, monkeypatch, generator=Generator(fail_select=2), gap=False, synthesis=False)
    assert outcome['status'] == 'INCOMPLETE' and outcome['stop_reason'].startswith('selection_failed')
    assert (tmp_path / 'index.html').exists() and (tmp_path / 'gaps.json').exists()


def test_gap_round_targets_unpicked_requirement_only(tmp_path, monkeypatch):
    outcome = journey(tmp_path, monkeypatch, generator=Generator(pick_none=('axis3',)), synthesis=False)
    log = json.loads((tmp_path / 'gap-round.json').read_bytes())
    assert log['targets'] == ['axis3']
    assert all(q['requirement'] == 'axis3' for q in log['queries'])
    assert outcome['verified_units'] == 3  # no new readable source: the gap stays explicit
    assert json.loads((tmp_path / 'gaps.json').read_bytes())['model_fit']['axis3'] == 'none'


def test_search_cap_is_never_exceeded_and_resume_replays_without_calls(tmp_path, monkeypatch):
    g = Generator()
    journey(tmp_path, monkeypatch, generator=g, search_cap=3, gap=False, synthesis=False)
    state = json.loads((tmp_path / 'state.json').read_bytes())
    assert state['search_attempts'] == 3
    before = len(g.calls)
    journey(tmp_path, monkeypatch, generator=g, search_cap=3, gap=False, synthesis=False)
    assert len(g.calls) == before


def test_code_draft_omits_html_numbers_and_respects_slots():
    pack = dict(task=dict(facets=[dict(id='f1')], required_points=[dict(id='f1', facet='f1')]),
                content_plan=dict(items=[dict(facet='f1', state='reviewed', support=k) for k in ('a', 'b', 'c')]),
                content_units={'a': dict(support=dict(quote='Waits fell by 30%.', page_label='HTML')),
                               'b': dict(support=dict(quote='Queues can be shortened.', page_label='HTML')),
                               'c': dict(support=dict(quote='Staff may be reallocated.', page_label='p.2'))})
    draft, omitted = code_draft(pack)
    assert [u['text'] for u in draft['slides'][0]['units']] == ['Queues can be shortened.', 'Staff may be reallocated.']
    assert omitted == [dict(facet='f1', support='a', reason='unlinked_html_number')]


def test_shortlist_diversity_and_near_duplicates():
    wire = dict(sources=[dict(handle=h, support_segment=h, context=[]) for h in ('s1', 's2', 's3', 's4')],
                segments=[dict(id='s1', source='d1', text='Staff can be moved to busy counters.'),
                          dict(id='s2', source='d1', text='Appointments reduce peak queues.'),
                          dict(id='s3', source='d2', text='Staff can be moved to busy counters!'),
                          dict(id='s4', source='d3', text='Signage helps visitors find counters.')])
    ranking = dict(r1=[('s1', .5), ('s2', .4), ('s3', .3), ('s4', .2)])
    assert shortlist({}, wire, ranking, k=3) == dict(r1=['s1', 's4', 's2'])
    assert near_duplicate('Staff can be moved to busy counters.', 'Staff can be moved to busy counters!')
    prior = shortlist({}, wire, dict(r1=[('s1', .016), ('s4', .0159)]), k=1, source_type=dict(s1='commercial-vendor', s4='government'))
    assert prior == dict(r1=['s4'])


def test_select_payload_lists_only_shortlisted_candidates():
    task = dict(goal='g', audience='a', required_points=[dict(id='long_requirement_id', facet='f1', description='d1')])
    wire = dict(sources=[dict(handle='s1', support_segment='x', context=[])], segments=[dict(id='x', source='d1', text='T')])
    prompt, schema = select_payload(task, wire, dict(long_requirement_id=['s1']))
    assert json.loads(prompt.split('\n', 1)[1])['requirements'][0]['candidates'] == {'a': 'T'}
    assert schema['properties']['r1']['properties']['pick']['maxItems'] == 1 and list(schema['properties']) == ['r1']


def test_default_config_is_recorded():
    assert CONFIG['k'] == 5 and CONFIG['retry'] == 1 and CONFIG['search_cap'] <= 12


def test_progressive_pages_refresh_and_final_page_equals_batch_render(tmp_path, monkeypatch):
    from matn_research.preview import render
    journey(tmp_path, monkeypatch, gap=False, synthesis=False)
    final = (tmp_path / 'index.html').read_text(encoding='utf-8')
    version = json.loads((tmp_path / 'v1.json').read_bytes())
    assert 'http-equiv="refresh"' not in final and final == render(tmp_path, version)
    timeline = json.loads((tmp_path / 'state.json').read_bytes())['timeline']
    assert [t['stage'] for t in timeline] == ['first_pass', 'final'] and timeline[0]['verified_units'] == 4


def test_two_picks_per_requirement_fill_axis_slots(tmp_path, monkeypatch):
    outcome = journey(tmp_path, monkeypatch, generator=Generator(two=True), gap=False, synthesis=False)
    analysis = json.loads((tmp_path / 'analysis.json').read_bytes())
    per = {}
    for i in analysis['items']:
        per[i['facet']] = per.get(i['facet'], 0) + bool(i['support'])
    assert max(per.values()) == 2 and outcome['status'] == 'AI_REVIEW_REQUIRED'
    supports = [i['support'] for i in analysis['items'] if i['support']]
    assert len(supports) == len(set(supports))


class ClosingNative(FakeNative):
    """Mimics the L4 worker: alive after a check until close()."""
    def __init__(self):
        super().__init__(); self.alive = False
    def check(self, text, evidence, target):
        self.alive = True; return super().check(text, evidence, target)
    def close(self):
        self.alive = False


def test_no_generation_call_while_the_l4_worker_is_alive(tmp_path, monkeypatch):
    native = ClosingNative(); seen = []
    class Watch(Generator):
        def generate(self, body):
            seen.append(native.alive); return super().generate(body)
    monkeypatch.setitem(workflow.FEATURES, 'context_display', False)
    class GapProvider(Provider):
        def search(self, query):
            value = super().search(query)
            if 'from the material read' in query:  # the code-built gap query only
                value['response']['results'].append(dict(url='https://www.example.gov/extra', content='SNIPPET_NOT_EVIDENCE'))
            return value
    def gap_fetch(url, **kw):
        if url.endswith('/extra'):
            html = '<html><body><main><p>Tree shade should be evaluated at the intended seating area.</p></main></body></html>'
            return dict(body=html.encode(), final_url=url, content_type='text/html; charset=utf-8', fetched_at=time.time(), redirects=[])
        return fetch(url, **kw)
    run_v2(tmp_path, BRIEF, provider=GapProvider(), generator=Watch(pick_none=('axis3',)), native=native,
           counter=lambda t: len(t) // 4, fetch=gap_fetch, classification=LABEL, config=dict(synthesis=False))
    assert len(seen) == 3 and not any(seen) and not native.alive  # plan, select-0, select-gap after verify-0


def test_plan_output_diet_schema():
    from matn_research.fast import plan_schema, PlanV2
    axis = plan_schema()['properties']['facets']['items']
    assert set(axis['required']) == {'id', 'label', 'success', 'searches'} and axis['properties']['searches']['maxItems'] == 1
    # Owner-edited plans may still carry a question and two phrases.
    PlanV2.model_validate(dict(facets=[dict(id='a' + str(i), label='Label', question='Why?', success='Explain it well',
                                            searches=['x', 'y']) for i in range(4)]))
