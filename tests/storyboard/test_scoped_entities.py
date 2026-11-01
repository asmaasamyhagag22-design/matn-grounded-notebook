"""Evidence scopes, not model grounding: these tests use an explicit fake L4."""
from copy import deepcopy

import pytest

from matn_storyboard.units import UnitWorkflow, upgrade_pack
from matn_storyboard.unit_composition import ComposedWorkflow
from tests.storyboard.test_units import setup, atom, draft
from tests.chat.test_engine import Pass


def fixture():
    d, p = setup('National Audit Council (NAC) may review plans. '
                 'National Audit Council may review plans. Firms may invest.')
    return d, upgrade_pack([d], p, selected_display=True)


class Capture(Pass):
    def __init__(self):
        self.calls = []

    def check(self, text, evidence, target):
        self.calls.append((target, text, tuple(evidence)))
        return super().check(text, evidence, target)


@pytest.mark.parametrize('context,sources', [
    ('National Audit Council (NAC) may review plans.', [0]),
    ('NAC may review plans.', [1]),
])
def test_context_alias_is_bound_to_its_own_sources(context, sources):
    d, p = fixture()
    a = atom(p, 'Firms may invest.', list(p['handles'])[-1])
    a['context'] = dict(text=context, sources=sources)
    native = Capture()
    r = UnitWorkflow([d], p, native).check(a)
    assert r['status'] == 'verified', r['reasons']
    claim_evidence = next(ev for target, _, ev in native.calls if target == 'claim')
    assert len(claim_evidence) == 1
    assert claim_evidence[0].quote == 'Firms may invest.'
    if sources == [1]:
        context_evidence = next(ev for target, _, ev in native.calls if target == 'display-context')
        assert any('(NAC)' in ev.quote for ev in context_evidence)


def test_alias_in_reading_context_cannot_license_an_unrelated_claim():
    d, p = fixture()
    a = atom(p, 'NAC may invest.', list(p['handles'])[-1])
    a['context'] = dict(text='National Audit Council (NAC) may review plans.', sources=[0])
    r = UnitWorkflow([d], p, Pass()).check(a)
    assert r['status'] != 'verified'
    assert 'new_entity' in r['reasons']


@pytest.mark.parametrize('context,sources', [
    ('NAC may review plans.', []),
    ('NAC may review plans.', [0]),
    ('XYZ may review plans.', [1]),
])
def test_context_requires_its_own_selected_evidence(context, sources):
    # The middle case has a literal definition and is valid. The other cases
    # deliberately lack a selected source or introduce a different entity.
    d, p = fixture()
    a = atom(p, 'Firms may invest.', list(p['handles'])[-1])
    a['context'] = dict(text=context, sources=sources)
    r = UnitWorkflow([d], p, Pass()).check(a)
    assert (r['status'] == 'verified') == (sources == [0])


def test_definition_and_context_are_in_composition_not_claim_support():
    d, p = fixture()
    a = atom(p, 'Firms may invest.', list(p['handles'])[-1])
    a['context'] = dict(text='NAC may review plans.', sources=[1])
    native = Capture()
    v = ComposedWorkflow([d], p, native).build(draft(p, a))
    assert all(s['displayed'] for s in v['slides'])
    evidence = v['slides'][0]['composition']['evidence']
    assert any('(NAC)' in ref['quote'] for ref in evidence)
    assert all('NAC' not in ev.quote for target, _, refs in native.calls
               if target == 'claim' for ev in refs)


def test_scoped_aliases_preserve_version_invalidation_and_style_reuse():
    d, p = fixture()
    a = atom(p, 'Firms may invest.', list(p['handles'])[-1])
    a['context'] = dict(text='NAC may review plans.', sources=[1])
    f = ComposedWorkflow([d], p, Capture())
    first = f.build(draft(p, a))
    original = deepcopy(first)
    styled = f.edit(first, [dict(op='style', key='accent', value='blue')])
    assert all(s['displayed'] for s in styled['slides'])
    assert len(styled['reused_receipts']) == 1
    changed = deepcopy(a)
    changed['context']['text'] = 'XYZ may review plans.'
    edited = f.edit(first, [dict(op='replace_unit', slide=0, unit=0, value=changed)])
    assert not edited['slides'][0]['displayed']
    assert first == original
    assert edited['slides'][0]['checks'][0]['binding'] != first['slides'][0]['checks'][0]['binding']
    assert not edited['slides'][0]['checks'][0]['reused']
    # The other three slides still use the old binding; global deduplicated
    # invalidation must not report it as unused everywhere.
    assert all(s['checks'][0]['reused'] for s in edited['slides'][1:])


def test_context_binding_does_not_bypass_native_rejection():
    from matn_verification.contracts import Check

    class RejectContext(Pass):
        def check(self, text, evidence, target):
            if target == 'display-context':
                return Check(target=target, layer='L4', verdict='reject',
                             reasons=('entailment_failed',))
            return super().check(text, evidence, target)

    d, p = fixture()
    a = atom(p, 'Firms may invest.', list(p['handles'])[-1])
    a['context'] = dict(text='NAC may review plans.', sources=[1])
    result = UnitWorkflow([d], p, RejectContext()).check(a)
    assert result['status'] != 'verified'
    assert any(c['verdict'] == 'reject' for c in result['checks'])


def test_scoped_resolver_does_not_import_definition_from_other_document():
    from matn_verification.aliases import definitions, resolve_scoped

    d, p = fixture()
    refs = [p['content_units'][list(p['handles'])[1]]['support']]
    missing, witnesses = resolve_scoped('NAC may review plans.', refs, definitions([d]))
    assert not missing and witnesses
    foreign = [dict(refs[0], doc_id='other-document')]
    missing, witnesses = resolve_scoped('NAC may review plans.', foreign, definitions([d]))
    assert missing == ['NAC'] and not witnesses
