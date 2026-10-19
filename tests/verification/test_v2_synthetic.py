from eval.verification.synthetic import mutations,family_split


def test_operators_require_clear_preconditions_and_one_edit():
    changes=mutations('Revenue increased by 12 percent in 2021.',neighbor_entities=())
    assert changes['number_change']['new']!='12'
    assert changes['direction_flip']['new']=='decreased'
    assert 'modality_shift' not in changes and 'entity_swap' not in changes
    for change in changes.values():
        text='Revenue increased by 12 percent in 2021.'
        assert change['text']==text[:change['start']]+change['new']+text[change['end']:]
    assert 'negation' not in mutations('Not all systems are reliable.',())


def test_family_split_is_source_balanced_and_seeded():
    rows=[{'source':s,'family_id':f'{s}:{i}'} for s in ['a','b'] for i in range(12)]
    a=family_split(rows);b=family_split(list(reversed(rows)))
    assert a==b
    assert sum(v=='tune' for v in a.values())==8


def test_source_sentences_do_not_split_decimal_or_keep_fragments():
    from eval.verification.synthetic import source_sentences
    rows=list(source_sentences('Revenue was 7.5 percent in 2021. This fragment'))
    assert [q for a,z,q in rows]==['Revenue was 7.5 percent in 2021.']


def test_selection_can_use_other_eligible_families_without_forcing_mutation():
    from eval.verification.synthetic import choose_items
    parents=[{'family_id':str(i),'source':'a','split':'tune','text':('Revenue increased by 12 percent.' if i else 'Systems are reliable.'),'neighbors':[]} for i in range(8)]
    rows=choose_items(parents)
    numbers=[r for r in rows if r['type']=='number_change']
    assert len(numbers)==7 and len({r['family_id'] for r in numbers})==7
    assert not any(r['type']=='modality_shift' for r in rows)
