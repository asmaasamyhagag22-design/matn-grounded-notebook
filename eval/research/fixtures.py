"""Offline demonstration doubles. No real model, provider or network calls."""
import json
from pathlib import Path
import time
from matn_chat.readiness import write
from matn_verification.contracts import Check
from matn_storyboard.core import save_version
from matn_storyboard.units import style_version
from matn_storyboard.unit_composition import ComposedWorkflow
from matn_contracts.structure import DocumentStructure
from matn_research.preview import publish
from matn_research.workflow import run

BRIEF = dict(topic='Urban trees for comfortable public seating', audience='Municipal public-space planners',
             goal='Explain shade, soil, care and evaluation for a small planting project',
             scope='Synthetic demonstration, not real tree guidance', language='English', public_topic=True)
TEXTS = ['Shade can reduce direct sunlight on outdoor seating.',
         'Tree roots need suitable soil to establish.',
         'Young trees may need watering and inspection during dry weather.',
         'Tree shade should be evaluated at the intended seating area.']
HTML = '<html><body><main>' + ''.join('<p>' + t + '</p>' for t in TEXTS) + '</main></body></html>'
LABEL = 'OFFLINE FIXTURE · Fake provider, Fake generation and Fake L4 · no live discovery or native evidence'


class Provider:
    name = 'fixture-search'
    def __init__(self): self.calls = []
    def search(self, query):
        self.calls.append(query)
        return dict(provider=self.name, query=query, at=time.time(), response=dict(results=[
            dict(url='file:///unsuitable', content='SNIPPET_NOT_EVIDENCE'),
            dict(url='https://fixture.example/guide', content='SNIPPET_NOT_EVIDENCE'),
            dict(url='https://fixture.example/copy', content='SNIPPET_NOT_EVIDENCE')]))


class Generator:
    def __init__(self, *, unknown=False): self.calls = []; self.unknown = unknown
    def generate(self, body):
        self.calls.append(body)
        props = body['format']['properties']
        if 'facets' in props:
            value = dict(facets=[dict(id='axis' + str(i), label=label,
                         question='What should planners know about ' + label.lower() + '?',
                         searches=[label.lower(), label.lower() + ' limitations', label.lower() + ' examples'],
                         success='Explain ' + label.lower() + ' from the material read')
                         for i, label in enumerate(['Shade', 'Soil', 'Care', 'Evaluation'])])
        elif 'items' in props:
            data = json.loads(body['prompt'].split('\n', 1)[1]); catalog = data['sources']; items = []
            texts = {r['id']: r['text'] for r in data['segments']}
            for facet in data['facets']:
                i = int(facet['id'].removeprefix('axis')); text = TEXTS[i]
                c = next(c for c in catalog if texts[c['support_segment']].strip() == text)
                deps = []
                if 'during dry weather' in text:
                    start = text.index('during dry weather')
                    deps = [dict(segment=c['support_segment'], start=start, end=start+len('during dry weather'),
                                 dimension='condition', reason='Explicit developer-reviewed fixture condition span')]
                items.append(dict(facet=facet['id'], support=c['handle'], state='unknown' if self.unknown and i == 3 else 'reviewed',
                                  points=[p['id'] for p in facet['points']],
                                  reason='Explicit synthetic fixture selection for this question', context_sources=[], dependencies=deps, conflict=''))
            value = dict(items=items)
        else:
            # Source support handles are enums in the existing writing schema.
            catalog = json.loads(body['prompt'].split('\n', 1)[1].split('\nExactly', 1)[0])
            # planning.payload serializes sources as a list of selected items.
            rows = catalog['content']
            value = dict(slides=[dict(facet='axis' + str(i), units=[dict(text=text,
                         support=next(r['plan']['support'] for r in rows if r['support'].strip() == text),
                         context=dict(text='', sources=[]))]) for i, text in enumerate(TEXTS)])
        return dict(done=True, done_reason='stop', response=json.dumps(value), thinking='')


class FakeNative:
    """Always pass by design; cannot establish factual/semantic support."""
    def __init__(self): self.calls = []
    def check(self, text, evidence, target):
        self.calls.append((text, evidence, target))
        return Check(target=target, layer='L4', verdict='pass')


def fetch(url, **kwargs):
    return dict(body=HTML.encode(), final_url=url, content_type='text/html; charset=utf-8',
                fetched_at=time.time(), redirects=[])


def demo(folder):
    provider = Provider(); generator = Generator(); native = FakeNative()
    result = run(folder, BRIEF, provider=provider, generator=generator, native=native,
                 counter=lambda text: len(text) // 4, fetch=fetch, classification=LABEL)
    folder = Path(folder); version = json.loads((folder / 'v1.json').read_bytes())
    pack = json.loads((folder / 'evidence-pack.json').read_bytes())
    documents = list({d.doc_id: d for d in [DocumentStructure.model_validate_json(p.read_bytes()) for p in (folder / 'sources').glob('*/document.json')]}.values())
    flow = ComposedWorkflow(documents, pack, native)
    operations = [dict(op='edit_claim', slide=2, unit=0, text='Young trees may need watering during dry weather.')]
    factual = flow.edit(version, operations)
    count = len(native.calls); style = style_version(factual, [dict(op='style', key='density', value='compact')])
    assert len(native.calls) == count and style['slides'] == factual['slides']
    for name, v in [('v1', version), ('factual', factual), ('style', style)]:
        save_version(folder / 'versions', v); write(folder / (name + '.json'), v)
        publish(folder, v, name=name + '.html', label=LABEL)
    write(folder / 'edit-operations.json', operations)
    write(folder / 'outcome.json', dict(result, classification=LABEL, native=0, generation=0, live_search=0,
          fake_provider_attempts=len(provider.calls), fake_generation_attempts=len(generator.calls), fake_l4_roles=len(native.calls),
          style_inference=0, full_journey_accepted=False))
    publish(folder, version, label=LABEL)
    print(str((folder / 'index.html').resolve()))


if __name__ == '__main__':
    import sys
    demo(sys.argv[1])
