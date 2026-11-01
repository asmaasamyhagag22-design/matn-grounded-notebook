"""Deterministic per-requirement shortlist: code ranks, the model only chooses.

Production hybrid ranking (BM25 + cached no-prefix embeddings, RRF) over the
admitted bounded pool. Optional BM25 prefilter bounds embedding cost. Optional
source-quality prior reorders, never excludes. Diversity and near-duplicate
suppression act only on the top-K presentation; every candidate stays saved.
"""
import re

from matn_rag.embedding import query_input
from matn_rag.scoring import bm25, cosine, fuse

POLICY = 'code-shortlist-v1'
PRIOR = {'government': 1, 'academic': 1, 'international organization': 1, 'commercial-vendor': -1}
PRIOR_WEIGHT = 1 / 62 - 1 / 72  # one prior step ~= moving ten places near the top of one RRF stream


def candidates(wire, screen=None):
    """Rows the model may see. Page furniture is excluded by the existing screen; `screen`
    (sid -> reason) adds the v2 admission screen. Excluded IDs stay in the saved pool."""
    from .view_rank import boilerplate
    segments = {s['id']: s for s in wire['segments']}
    rows = []
    for s in wire['sources']:
        seg = segments[s['support_segment']]
        if not boilerplate(seg['text']) and not (screen or {}).get(s['handle']):
            rows.append(dict(chunk_id=s['handle'], source_id=seg['source'], text=seg['text'],
                             context_prefix=s.get('retrieval_context', '')))
    return rows


def admission_screen(wire, reg, host_of, label_of):
    """sid -> reason for promotion/consent/own-vendor lines and cross-page template sentences."""
    from .view_rank import promotion, cross_page_boilerplate
    segments = {s['id']: s for s in wire['segments']}
    out = {}; rows = []
    for s in wire['sources']:
        seg = segments[s['support_segment']]; doc = reg['segments'][s['support_segment']]['doc_id']
        from .quality import sentence_reason
        reason = sentence_reason(seg['text']) or promotion(seg['text'], host_of.get(doc), label_of.get(doc) == 'commercial-vendor')
        if reason:
            out[s['handle']] = reason
        rows.append((s['handle'], doc, host_of.get(doc), seg['text']))
    for sid, reason in cross_page_boilerplate(rows).items():
        out.setdefault(sid, reason)
    return out


def rank(task, wire, *, vectors=None, prefilter=None, ablation='hybrid', screen=None):
    """requirement id -> [(sid, fused score)], best first. vectors(texts) -> list of vectors or None."""
    # Rank exactly as without the screen, then drop screened IDs from the fused lists: every unscreened
    # candidate keeps its relative order and can only move up.
    rows = candidates(wire); result = {}; screen = screen or {}
    drop = lambda fused: [r for r in fused if r[0] not in screen]
    # Fast-path metadata adds the frozen axis label and exact source headings
    # to lexical retrieval only. Neither becomes claim text or an embedding
    # input; legacy callers have empty prefixes and unchanged queries.
    lexical = {p['id']: bm25(rows, p.get('retrieval_query', p['description']), prefix=True)
               for p in task['required_points']}
    if vectors is None or ablation == 'bm25':
        return {pid: drop(fuse(lex, [], 'bm25')) for pid, lex in lexical.items()}, dict(embedded=0)
    keep = {pid: [cid for cid, _ in lex[:prefilter]] if prefilter else [r['chunk_id'] for r in rows] for pid, lex in lexical.items()}
    wanted = list(dict.fromkeys(c for ids in keep.values() for c in ids))
    by = {r['chunk_id']: r for r in rows}
    texts = [by[c]['text'] for c in wanted] + [query_input(p['description']) for p in task['required_points']]
    found = vectors(texts)
    table = {(by[c]['source_id'], c): v for c, v in zip(wanted, found[:len(wanted)], strict=True) if v is not None}
    for p, q in zip(task['required_points'], found[len(wanted):], strict=True):
        pool = [by[c] for c in keep[p['id']] if (by[c]['source_id'], c) in table]
        vec = cosine(pool, q, table) if q is not None and pool else []
        result[p['id']] = drop(fuse(lexical[p['id']], vec, ablation))
    return result, dict(embedded=len(wanted), pool=len(rows))


def words(text):
    return set(re.findall(r'[a-z0-9]+', text.lower()))


def near_duplicate(a, b, threshold=.8):
    wa, wb = words(a), words(b)
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= threshold


def shortlist(task, wire, ranking, *, k=3, source_type=None, diversity=True, dedup=True):
    """requirement id -> top-k sids. source_type: sid -> label (from source_type.classify).

    diversity: True = one per source until sources run out; an int n = at most n per source first; False = rank order.
    """
    per_doc = 1 if diversity is True else (diversity or 10 ** 6)
    segments = {s['id']: s for s in wire['segments']}
    by = {s['handle']: segments[s['support_segment']] for s in wire['sources']}
    out = {}
    for pid, fused in ranking.items():
        scored = [(sid, score + (PRIOR_WEIGHT * PRIOR.get(source_type.get(sid), 0) if source_type else 0)) for sid, score in fused]
        order = [sid for sid, _ in sorted(scored, key=lambda r: (-r[1], r[0]))]
        kept = []; docs = {}; deferred = []
        for sid in order:
            if len(kept) >= k:
                break
            text = by[sid]['text']
            if dedup and any(near_duplicate(text, by[o]['text']) for o in kept):
                continue
            if docs.get(by[sid]['source'], 0) >= per_doc:
                deferred.append(sid); continue
            kept.append(sid); docs[by[sid]['source']] = docs.get(by[sid]['source'], 0) + 1
        for sid in deferred:  # fill from repeated sources only when distinct sources run out
            if len(kept) >= k:
                break
            if not (dedup and any(near_duplicate(by[sid]['text'], by[o]['text']) for o in kept)):
                kept.append(sid)
        out[pid] = kept
    return out
