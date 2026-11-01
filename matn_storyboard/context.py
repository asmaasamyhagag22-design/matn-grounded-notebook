"""Reviewed, source-bound display dependencies (a veto, never support proof).

Dependencies are explicit evidence-pack annotations, not inferred from labels or
nearby numbers. A reviewer must identify them; absence is not a completeness
claim. Exact visible source text is deliberately conservative about paraphrases.
"""
from matn_verification.meaning import normalized

POLICY = 'reviewed-visible-dependencies-v1'


def validate_dependencies(documents, dependencies):
    by = {e.block.block_id: (d, e) for d in documents for e in d.elements}
    for row in dependencies:
        if not row.get('reason') or not row.get('requires'):
            raise ValueError('CONTEXT_DEPENDENCY_REVIEW_REQUIRED')
        for ref in [row['target'], *row['requires']]:
            d, e = by[ref['block_id']]
            if (ref['doc_id'] != d.doc_id or not 0 <= ref['start'] < ref['end'] <= len(e.block.text)
                    or ref['quote'] != e.block.text[ref['start']:ref['end']]):
                raise ValueError('CONTEXT_DEPENDENCY_SOURCE_BINDING')


def display_context(atoms, handles, dependencies):
    """Require cited dependencies inside the same indivisible display unit.

    Citations alone cannot discharge an obligation. The full required text must
    also be visible, and still goes through atomic AND composed verification.
    No source text is appended automatically or unioned into another claim.
    """
    refs = [c for a in atoms for k in a['handles'] for c in handles[k]['citations']]
    missing = []
    for row in dependencies:
        t = row['target']
        if not any(c['doc_id'] == t['doc_id'] and c['block_id'] == t['block_id']
                   and c['start'] < t['end'] and t['start'] < c['end'] for c in refs):
            continue
        for required in row['requires']:
            satisfied = any(
                normalized(required['quote']) in normalized(a['text'])
                and any(c['doc_id'] == required['doc_id'] and c['block_id'] == required['block_id']
                        and c['start'] <= required['start'] and c['end'] >= required['end']
                        for k in a['handles'] for c in handles[k]['citations'])
                for a in atoms)
            if not satisfied:
                missing.append(dict(target=t, required=required, reason=row['reason']))
    return dict(policy=POLICY, status='missing' if missing else 'complete_for_reviewed_dependencies',
                missing=missing)
