"""Migration comparison must reject evidence changes while accepting ID references."""
from copy import deepcopy
import pytest
from eval.rag.section_rebuild import id_only


def pair():
    before={'producer_versions':{'sections':'r-lite-2'},'sections':[{'section_id':'old-section','parent_id':None,'child_ids':[],'producer_version':'r-lite-2','block_ids':['unchanged-block']}],'chunks':[{'chunk_id':'old-chunk','section_id':'old-section','next_chunk_id':None,'text':'Unchanged evidence.','primary':[{'block_id':'unchanged-block','start':0,'end':19}]}]}
    after=deepcopy(before);after['producer_versions']['sections']='section-identity-v2';after['sections'][0].update(section_id='new-section',producer_version='section-identity-v2');after['chunks'][0].update(chunk_id='new-chunk',section_id='new-section')
    return before,after


def test_id_migration_accepts_only_ids_references_and_version():
    before,after=pair()
    assert len(id_only(before,after))==2


def test_id_migration_rejects_changed_evidence_boundary():
    before,after=pair();after['chunks'][0]['primary'][0]['end']=18
    with pytest.raises(ValueError,match='NON_ID_DIFFERENCE:chunks'):id_only(before,after)
