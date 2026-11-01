"""Offline shortlist bench over saved topics. Zero model and zero network calls.

For every saved topic: rebuild the admitted catalogue from the saved documents
under current code, rank each frozen requirement with code only, and measure
whether evidence the old pipeline REVIEWED (selected as reviewed in any round)
or DISPLAYED (verified final unit) is in the top-K shortlist. Embeddings come
only from existing hash-keyed caches; uncached texts fall back to BM25 rank.

Positives are what the old model-heavy path found, so they bound recall of what
was already found, not unseen useful evidence (stated in every report).

  .venv/bin/python -B -m eval.research.bench.run --out out/leap-20261030/bench
"""
import argparse
import json
from pathlib import Path
import socket

ROOT = Path(__file__).resolve().parents[3]
TOPICS = {
    'A': 'out/topic-research-sprint-20261029/topic-a', 'A-new': 'out/topic-research-round2-20261029/topic-a',
    'B': 'out/topic-research-sprint-20261029/topic-b', 'C': 'out/topic-research-final-20261029/topic-c',
    'D': 'out/topic-research-final-20261029/topic-d', 'E': 'out/topic-research-round2-20261029/topic-e',
    'F': 'out/topic-research-round2-20261029/topic-f', 'G': 'out/topic-research-round3-20261029/topic-g',
    'H': 'out/topic-research-round4-20261029/topic-h', 'I': 'out/topic-research-senior-20261029/topic-i',
    'Urban': 'out/topic-research-sprint-20261029/urban-fix',
}
CACHES = sorted(p for p in (ROOT / 'out').glob('*/embedding-cache')) + [ROOT / 'out/research-embeddings-c1']
VARIANTS = {  # name: (ablation, prefilter, prior, diversity, admission screen)
    'bm25': ('bm25', None, False, True, False),
    'hybrid': ('hybrid', None, False, True, False),
    'hybrid-nodiv': ('hybrid', None, False, False, False),
    'hybrid-pf40': ('hybrid', 40, False, True, False),
    'hybrid-pf40-nodiv': ('hybrid', 40, False, False, False),
    'hybrid-pf20-nodiv': ('hybrid', 20, False, False, False),
    'hybrid-pf40-div2': ('hybrid', 40, False, 2, False),
    'hybrid-pf40-nodiv-prior': ('hybrid', 40, True, False, False),
    'hybrid-pf40-nodiv-prior-screen': ('hybrid', 40, True, False, True),
    'hybrid-pf40-div2-prior-screen': ('hybrid', 40, True, 2, True),
    'hybrid-pf20-div2-prior-screen': ('hybrid', 20, True, 2, True),
    'hybrid-pf30-div2-prior-screen': ('hybrid', 30, True, 2, True),
    'hybrid-pf30-div2-prior': ('hybrid', 30, True, 2, False),
    'bm25-prior-screen': ('bm25', None, True, True, True),
}


def block_network():
    def refuse(*a, **k):
        raise RuntimeError('BENCH_NETWORK_FORBIDDEN')
    socket.socket.connect = refuse; socket.create_connection = refuse


def cached_vectors(stats):
    from matn_research.requirement_selection import vector_key
    def lookup(texts):
        out = []
        for t in texts:
            key = vector_key(t) + '.json'; hit = None
            for folder in CACHES:
                if (folder / key).exists():
                    value = json.loads((folder / key).read_bytes())
                    if value['input'] == t:
                        hit = value['vector']; break
            stats['hit' if hit is not None else 'miss'] += 1; out.append(hit)
        return out
    return lookup


def load(run):
    from matn_contracts.structure import DocumentStructure
    run = ROOT / run
    freeze = run / 'task-freeze.json'
    task = json.loads(freeze.read_bytes())['task'] if freeze.exists() else json.loads((run / 'evidence-pack.json').read_bytes())['task']
    docs = []; urls = {}
    for r in json.loads((run / 'reading-status.json').read_bytes()):
        if r.get('status') != 'complete' or r.get('independent') is False:
            continue
        folder = run / 'sources' / Path(r['folder']).name
        if not (folder / 'document.json').exists():
            folder = Path(r['folder'])
        d = DocumentStructure.model_validate_json((folder / 'document.json').read_bytes())
        if d.doc_id not in urls:
            docs.append(d); urls[d.doc_id] = r.get('final_url') or r['url']
    return run, task, docs, urls


def positives(run, task):
    """(facet, doc_id, quote) the old pipeline reviewed, and the subset it displayed."""
    reviewed = set(); handle_text = {}
    for reg_path in sorted(run.glob('segment-registry-*.json')):
        reg = json.loads(reg_path.read_bytes())
        for sid, s in reg['supports'].items():
            seg = reg['segments'][s['segment']]
            handle_text.setdefault(reg_path.stem.rsplit('-', 1)[1], {})[s['handle']] = (seg['doc_id'], seg['quote'])
    pack_path = run / 'evidence-pack.json'
    pack = json.loads(pack_path.read_bytes()) if pack_path.exists() else None
    for job in sorted((run / 'jobs').glob('facet-*.json')):
        parts = job.stem.split('-')
        if not parts[1].isdigit():
            continue
        for item in json.loads(job.read_bytes()).get('items', []):
            if item.get('state') != 'reviewed' or not item.get('support'):
                continue
            ref = handle_text.get(parts[1], {}).get(item['support'])
            if ref is None and pack and item['support'] in pack['content_units']:
                u = pack['content_units'][item['support']]['support']; ref = (u['doc_id'], u['quote'])
            if ref:
                reviewed.add((item['facet'],) + ref)
    displayed = set()
    if (run / 'v1.json').exists() and pack:
        for slide in json.loads((run / 'v1.json').read_bytes())['slides']:
            for c in slide['checks']:
                if c['status'] == 'verified':
                    u = pack['content_units'][c['atom']['support']]['support']
                    displayed.add((slide['facet'], u['doc_id'], u['quote']))
    return reviewed, displayed


def old_views(run):
    sizes = []
    for g in sorted(run.glob('generation-plan-*.json')):
        for v in json.loads(g.read_bytes()).get('facet_views', {}).values():
            if 'sent' in v:
                sizes.append(len(v['sent']))
    return sizes


def bench_topic(name, run_rel, ks=(3, 5, 8)):
    from matn_research import workflow
    from matn_research.facets import registry
    from matn_research.shortlist import rank, shortlist
    from matn_research.source_type import classify
    run, task, docs, urls = load(run_rel)
    workflow.FEATURES.update(context_display=True)
    pack, _ = workflow.catalogue(docs, task)
    rows = [dict(handle=k) for k, u in pack['content_units'].items() if u.get('state') == 'bounded']
    reg, wire = registry(pack, rows)
    key = {}
    for sid, s in reg['supports'].items():
        seg = reg['segments'][s['segment']]; key[(seg['doc_id'], seg['quote'])] = sid
    stype = {sid: classify(urls.get(reg['segments'][s['segment']]['doc_id'], ''))['label'] for sid, s in reg['supports'].items()}
    reviewed, displayed = positives(run, task)
    stats = dict(hit=0, miss=0); vec = cached_vectors(stats)
    result = dict(topic=name, run=run_rel, documents=len(docs), pool=len(rows), requirements=len(task['required_points']),
                  reviewed_positives=len(reviewed), displayed_positives=len(displayed), old_view_sizes=old_views(run), variants={})
    in_pool = {p for p in reviewed if (p[1], p[2]) in key}
    result['reviewed_in_current_pool'] = len(in_pool)
    from urllib.parse import urlsplit
    from matn_research.shortlist import admission_screen
    hosts = {d: urlsplit(u).hostname for d, u in urls.items()}
    labels = {d: classify(u)['label'] for d, u in urls.items()}
    screened = admission_screen(wire, reg, hosts, labels)
    result['screened'] = dict(total=len(screened), reasons={r: list(screened.values()).count(r) for r in set(screened.values())},
        reviewed_positives_screened=sorted({reg['segments'][reg['supports'][sid]['segment']]['quote'][:120] for sid in screened
            if any((d, q) == (reg['segments'][reg['supports'][sid]['segment']]['doc_id'], reg['segments'][reg['supports'][sid]['segment']]['quote'])
                   for f, d, q in reviewed)}))
    for vname, (ablation, prefilter, prior, diversity, screen) in VARIANTS.items():
        ranking, info = rank(task, wire, vectors=vec, prefilter=prefilter, ablation=ablation, screen=screened if screen else None)
        row = dict(info=info)
        for k in ks:
            sl = shortlist(task, wire, ranking, k=k, source_type=stype if prior else None, diversity=diversity)
            per = []
            for p in task['required_points']:
                pos = {key[(d, q)] for f, d, q in reviewed if f == p['facet'] and (d, q) in key}
                dis = {key[(d, q)] for f, d, q in displayed if f == p['facet'] and (d, q) in key}
                vendor = sum(stype.get(s) == 'commercial-vendor' for s in sl[p['id']])
                per.append(dict(requirement=p['id'], facet=p['facet'], positives=len(pos), hit=bool(pos & set(sl[p['id']])),
                                displayed=len(dis), displayed_hit=bool(dis & set(sl[p['id']])), vendor_in_shortlist=vendor))
            with_pos = [r for r in per if r['positives']]; with_dis = [r for r in per if r['displayed']]
            row['k' + str(k)] = dict(requirements_with_positive=len(with_pos), hit=sum(r['hit'] for r in with_pos),
                requirements_with_displayed=len(with_dis), displayed_hit=sum(r['displayed_hit'] for r in with_dis),
                vendor_slots=sum(r['vendor_in_shortlist'] for r in per), slots=sum(len(v) for v in sl.values()), per=per)
        result['variants'][vname] = row
    result['embedding_cache'] = stats
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True); ap.add_argument('--topics', nargs='*')
    ap.add_argument('--data-root',type=Path,help='Read saved runs/cache from this vault; outputs still use --out')
    args = ap.parse_args(argv); block_network()
    if args.data_root:
        global ROOT,CACHES
        ROOT=args.data_root.resolve()
        CACHES=sorted((ROOT/'out').glob('*/embedding-cache'))+[ROOT/'out/research-embeddings-c1']
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True); results = {}
    for name, run in TOPICS.items():
        if args.topics and name not in args.topics:
            continue
        try:
            results[name] = bench_topic(name, run)
        except Exception as exc:  # report, never hide, a topic the bench cannot rebuild
            results[name] = dict(topic=name, run=run, error=repr(exc)[:300])
    summary = {}
    for v in VARIANTS:
        for k in ('k3', 'k5', 'k8'):
            rows = [r['variants'][v][k] for r in results.values() if 'variants' in r]
            summary[v + '@' + k] = dict(hit=sum(r['hit'] for r in rows), of=sum(r['requirements_with_positive'] for r in rows),
                displayed_hit=sum(r['displayed_hit'] for r in rows), displayed_of=sum(r['requirements_with_displayed'] for r in rows),
                vendor_slots=sum(r['vendor_slots'] for r in rows), slots=sum(r['slots'] for r in rows))
    (out / 'bench.json').write_text(json.dumps(dict(summary=summary, topics=results), indent=1))
    lines = ['| variant | reviewed hit | displayed hit | vendor slots |', '|---|---|---|---|']
    for k, s in summary.items():
        lines.append(f"| {k} | {s['hit']}/{s['of']} | {s['displayed_hit']}/{s['displayed_of']} | {s['vendor_slots']}/{s['slots']} |")
    lines += ['', '| topic | docs | pool | reviewed (in pool) | displayed | old view sizes | cache hit/miss |', '|---|---|---|---|---|---|---|']
    for n, r in results.items():
        if 'error' in r:
            lines.append(f'| {n} | ERROR {r["error"][:80]} |'); continue
        ov = r['old_view_sizes']
        lines.append(f"| {n} | {r['documents']} | {r['pool']} | {r['reviewed_positives']} ({r['reviewed_in_current_pool']}) | {r['displayed_positives']} | "
                     f"{min(ov) if ov else '-'}–{max(ov) if ov else '-'} | {r['embedding_cache']['hit']}/{r['embedding_cache']['miss']} |")
    (out / 'bench.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
