"""Source-to-pool availability, not relevance or semantic acceptance.

The audit keeps hashes/locators only. It never adds evidence, changes unit
boundaries, or treats a context occurrence as a selectable support sentence.
"""
from collections import Counter

from matn_storyboard.core import Workflow, digest
from matn_storyboard.units import ANAPHORA, discover, subject_bound, context_bound
from matn_verification.contracts import Citation
from matn_verification.prose import sentence_spans, unresolved_opening
from matn_verification.rules import eligibility, interval_covered


VERSION = 'research-source-availability-v1'


def unit_reasons(unit, element):
    if unit['state'] == 'bounded':
        return []
    if 'support' not in unit:
        return [unit['reason']]
    support = unit['support']; context = unit['context']; limits = unit['limits']
    reasons = []
    previous = [ref for ref in context if ref['start'] < support['start']]
    if len(previous) > limits['previous_sentences']:
        reasons.append('previous_sentence_limit')
    if sum(len(ref['quote']) for ref in context) > limits['context_characters']:
        reasons.append('context_character_limit')
    first = sentence_spans(element.block.text)[0]
    opening = element.block.text[first.start:first.end].strip()
    if ANAPHORA.search(opening) or unresolved_opening(opening):
        reasons.append('unresolved_block_opening')
    return reasons or [unit['reason']]


def availability(documents, pack):
    """Inventory every nonempty sentence, including vetoed/unresolved ones.

    Validated structure is the earliest observable input here. A passage absent
    from it requires the original/read snapshot; do not blame retrieval for it.
    """
    documents = tuple(documents)
    from .admission import admission_inventory
    _, excluded = admission_inventory(documents)
    Workflow(documents, pack, None)  # source fingerprints and exact handle quotes
    units = discover(documents, pack['handles'], subject=subject_bound(pack), context_display=context_bound(pack))
    if units != pack['content_units']:
        raise ValueError('UNIT_CONTEXT_BINDING')
    handles = {}; contexts = {}; primaries = {}
    for key, handle in pack['handles'].items():
        for ref in handle['citations']:
            handles.setdefault((ref['doc_id'], ref['block_id']), {}).setdefault(key, []).append(Citation(
                block_id=ref['block_id'], start=ref['start'], end=ref['end']))
    for key, unit in units.items():
        if unit['state'] != 'bounded':
            continue
        for ref in unit['context']:
            contexts.setdefault((ref['doc_id'], ref['block_id']), {}).setdefault(key, []).append(Citation(
                block_id=ref['block_id'], start=ref['start'], end=ref['end']))
    for document in documents:
        for chunk in document.chunks:
            for ref in chunk.primary:
                primaries.setdefault((document.doc_id, ref.block_id), []).append(ref)
    rows = []; counts = Counter(); losses = Counter()
    for document in documents:
        for element in document.elements:
            block = element.block; address = (document.doc_id, block.block_id)
            admission_reasons = excluded.get(address, [])
            reasons = list(eligibility(document, element))
            for span in sentence_spans(block.text):
                if not block.text[span.start:span.end].strip():
                    continue
                ref = Citation(block_id=block.block_id, start=span.start, end=span.end)
                indexed = interval_covered(ref, primaries.get(address, []))
                keys = [k for k, refs in handles.get(address, {}).items() if interval_covered(ref, refs)]
                bound = [k for k in keys if units[k]['state'] == 'bounded'
                         and units[k]['support']['doc_id'] == document.doc_id
                         and interval_covered(ref, [Citation(**{n: units[k]['support'][n]
                                                              for n in ('block_id', 'start', 'end')})])]
                reading = [k for k, refs in contexts.get(address, {}).items() if interval_covered(ref, refs)]
                first = ('admission' if admission_reasons else 'eligibility' if reasons else 'index' if not indexed else 'handles' if not keys
                         else 'content_unit' if not bound else None)
                row = dict(doc_id=document.doc_id, block_id=block.block_id,
                    start=span.start, end=span.end, text_sha256=digest(block.text[span.start:span.end]),
                    reasons=reasons, indexed=indexed, handles=keys,
                    admission_reasons=admission_reasons,
                    units=[k for k in keys if k in units], pool=bound, reading_context_of=reading,
                    unit_reasons=sorted({r for k in keys for r in unit_reasons(units[k], element)}),
                    first_unavailable=first)
                rows.append(row); counts['sentences'] += 1
                for stage, present in (('eligible', not reasons and not admission_reasons), ('indexed', indexed),
                                       ('handles', bool(keys)), ('pool', bool(bound))):
                    counts[stage] += int(present)
                if first is not None:
                    losses[first] += 1
    return dict(version=VERSION, sources=digest(pack['sources']), task=digest(pack['task']),
        units=digest(units), counts=dict(counts), first_unavailable_counts=dict(losses), sentences=rows,
        interpretation='Availability only, not semantic coverage. Index/handles/pool are distinct. '
            'Unresolved units stay unresolved; missing extracted text needs original-reader evidence.')
