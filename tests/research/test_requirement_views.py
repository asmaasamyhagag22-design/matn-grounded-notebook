"""Evidence-starvation fixes: furniture filter, requirement-first views, slots.

Structural/offline only. Retrieval order is opportunity, never semantic coverage.
"""
import pytest

from matn_research.facets import requirement_view, local_schema, slots, expand_bundle, IDAnalysis
from matn_research.view_rank import boilerplate
from matn_storyboard.units import unit_slots


@pytest.mark.parametrize('text,reason', [
    ('Call our Plano branch at (972) 555-0142 for a quote.', 'phone_number'),
    ('Learn essential techniques to create thriving urban landscapes.', 'call_to_action_or_navigation'),
    ('► Learn essential techniques to create thriving urban landscapes.', 'call_to_action_or_navigation'),
    ('Applying the filters below will filter all articles by topic.', 'call_to_action_or_navigation'),
    ('Not sure where to find something?', 'call_to_action_or_navigation'),
    ('s maintenance and compost program.', 'truncated_fragment'),
    ('Comfort in the canopy: How urban treescapes affect human thermal comfort', 'link_list_or_fragment'),
    ('Role of Urban Trees in Enhancing the Thermal Comfort of Rapidly Urbanizing Cities in Tropical Asia', 'heading_or_title'),
    ('#2: Trees boost our mental and physical health.', 'heading_or_list_marker'),
    ('The Conservancy turns 75!', 'promotion'),
    ('Appendix table of field days (PDF 99.4 kb)', 'link_list_or_fragment'),
])
def test_page_furniture_is_flagged_by_generic_rules(text, reason):
    assert boilerplate(text) == reason


@pytest.mark.parametrize('text', [
    'Shade increased thermal comfort significantly in the spring, summer, and fall.',
    'Check soil moisture during establishment and adjust run times.',
    'Ask the design team to identify usable soil volume, not merely nominal pit dimensions.',
    'Review the irrigation design with the planting plan before the layout is fixed.',
])
def test_ordinary_prose_and_source_guidance_are_kept(text):
    assert boilerplate(text) is None


def wire(texts):
    segments = [dict(id='r'+str(i+1), source='d1', block='b'+str(i+1), text=t) for i, t in enumerate(texts)]
    sources = [dict(handle='s'+str(i+1), support_segment='r'+str(i+1), context=[]) for i in range(len(texts))]
    return dict(sources=sources, segments=segments)


FACET = dict(id='care', label='Care', query='What maintenance should a project plan for?', points=[
    dict(id='p1', facet='care', description='Explain establishment watering needs.'),
    dict(id='p2', facet='care', description='Plan pruning inspection.'),
])


def test_each_requirement_gets_a_candidate_before_broad_fill_and_furniture_is_excluded():
    texts = ['Call us today at (972) 555-0142 for maintenance plans.',
             'Maintenance projects plan maintenance budgets for maintenance crews.',
             'Establishment watering needs vary with soil moisture.',
             'Pruning inspection should follow the first growing season.']
    view, audit = requirement_view([FACET], wire(texts), max_characters=2000)
    sent = [s['handle'] for s in view['sources']]
    order = [d['handle'] for d in audit['care']['candidates']]
    assert order[:2] == ['s3', 's4'] and set(sent) == {'s2', 's3', 's4'}
    legs = {d['handle']: d['leg'] for d in audit['care']['candidates']}
    assert legs['s3'] == 'required_point:p1' and legs['s4'] == 'required_point:p2'
    assert audit['care']['furniture'] == {'phone_number': 1}


def test_zero_overlap_prose_still_fills_residual_capacity():
    view, _ = requirement_view([FACET], wire(['Bark colour changes with age.']), max_characters=2000)
    assert [s['handle'] for s in view['sources']] == ['s1']


def test_slots_follow_requirements_not_axes():
    points = [dict(id='p'+str(i), facet='f'+str(i % 4), description='x') for i in range(16)]
    task = dict(facets=[dict(id='f'+str(i)) for i in range(4)], required_points=points)
    assert unit_slots(task) == {'f0': 4, 'f1': 4, 'f2': 4, 'f3': 4}
    assert unit_slots(dict(facets=task['facets'], required_points=points[:4])) == {'f0': 2, 'f1': 2, 'f2': 2, 'f3': 2}
    facets = [dict(id=f['id'], points=[p for p in points if p['facet'] == f['id']]) for f in task['facets']]
    assert sum(map(slots, facets)) == 16
    view = dict(sources=[dict(handle='s1', support_segment='r1', context=[])], segments=[])
    assert local_schema(facets, view)['properties']['items']['maxItems'] == 16
    assert IDAnalysis.model_fields['items'].metadata[-1].max_length == 16


def test_saved_pack_rebuilds_under_a_newer_unit_policy():
    from copy import deepcopy
    from eval.research.rebuild_catalogue import rebuild
    from matn_research.workflow import catalogue
    from tests.research.test_evidence_contract import long_document, task
    d = long_document(); pack, _ = catalogue([d], task())
    old = deepcopy(pack)
    for unit in old['content_units'].values():  # emulate the pre-window policy
        if unit.get('reason') == 'antecedent_window':
            unit['state'] = 'unresolved'
    rebuilt, report = rebuild(old, [d])
    assert report['before']['saved_pool'] == 4 and report['after']['availability']['pool'] == 6
    assert rebuilt['content_units'] == pack['content_units']
    changed = deepcopy(old); next(iter(changed['handles'].values()))['citations'][0]['quote'] = 'Changed'
    with pytest.raises(ValueError, match='PACK_SPAN'):
        rebuild(changed, [d])
