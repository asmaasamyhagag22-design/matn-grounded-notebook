"""Offline reconstruction from matching saved structures, never from old handles."""
from copy import deepcopy
import json
from pathlib import Path

from matn_contracts.structure import DocumentStructure
from matn_research.catalogue_audit import availability
from matn_research.workflow import catalogue, require_current_catalogue
from matn_storyboard.core import digest


def rebuild(saved_pack, documents):
    documents = tuple(documents)
    ids = [d.doc_id for d in documents]
    if len(set(ids)) != len(ids):
        raise ValueError('DUPLICATE_DOCUMENT_SNAPSHOT')
    if set(ids) != set(saved_pack['sources']):
        raise ValueError('CATALOGUE_SOURCE_SET_MISMATCH')
    # Validate full document fingerprints and original handle ranges before
    # trusting the task/source lineage. This does not authorize old omissions.
    # Content units are re-derived under the CURRENT unit policy: a saved pool
    # must not freeze an old eligibility rule (e.g. antecedent-window-v1).
    from matn_storyboard.core import Workflow
    from matn_storyboard.units import discover, subject_bound
    Workflow(documents, saved_pack, None)  # fingerprints and exact handle quotes first
    saved_pool = sum(u.get('state') == 'bounded' for u in saved_pack['content_units'].values())
    before = availability(documents, dict(saved_pack, content_units=discover(documents, saved_pack['handles'], subject=subject_bound(saved_pack))))
    value, _ = catalogue(documents, deepcopy(saved_pack['task']))
    if value['sources'] != saved_pack['sources']:
        raise ValueError('CATALOGUE_SOURCE_METADATA_CHANGED')
    require_current_catalogue(value)
    return value, dict(input=digest(saved_pack), output=digest(value),
        source_order=ids, task_unchanged=value['task']==saved_pack['task'],
        before=dict(handles=len(saved_pack['handles']), saved_pool=saved_pool, availability=before['counts']),
        after=dict(handles=len(value['handles']), availability=value['research_packing']['availability']['counts']),
        interpretation='Rebuilt from the same validated snapshots, not a replay of the historical request. '
            'Availability is not relevance, semantic coverage or acceptance.')


def from_reading_status(saved_pack, path):
    """Use recorded completed independent snapshots; never fall back to old handles."""
    records = json.loads(Path(path).read_bytes())
    rows = [r for r in records if r.get('independent') and r.get('status') == 'complete']
    documents = [DocumentStructure.model_validate_json((Path(r['folder'])/'document.json').read_bytes()) for r in rows]
    return rebuild(saved_pack, documents)
