"""Read saved research artifacts. Missing measurements remain unknown, never zero."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


DELIVERY_ROOT = Path(os.environ.get('MATN_DELIVERY_ROOT', os.environ.get('MATN_VAULT_ROOT', str(Path(__file__).resolve().parents[3])))).resolve()
V2_ROOT = Path(__file__).resolve().parents[3]
SENIOR = 'out/topic-research-senior-20261029'
KNOWN = {
    'devH': 'out/leap-20261030/dev-h',
    'H': 'out/topic-research-round4-20261029/topic-h',
    'A': 'out/topic-research-sprint-20261029/topic-a',
    'E': 'out/topic-research-round2-20261029/topic-e',
    'Oct27': 'out/research-completion-20261027/research-delivery',
    **{k: 'out/leap-20261030/holdout-' + k.lower() for k in 'JKLMNOPQ'},
}


def read(path, default=None):
    try:
        return json.loads(Path(path).read_bytes())
    except (OSError, ValueError):
        return default


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def relative_link(path, output):
    """Links work both from a file and the loopback server's /dashboard/index.html."""
    from urllib.parse import quote
    return quote(os.path.relpath(Path(path).resolve(), Path(output).resolve()), safe='/')


def review_path(folder):
    for p in (folder / 'review.json', folder.parent / (folder.name + '-review.json'),
              folder / 'coverage-review.json', folder.parent / (folder.name + '-coverage-review.json')):
        if p.exists():
            return p
    return None


def coverage_items(review, task):
    """Only explicit reviewed status establishes semantic axis coverage."""
    raw = review.get('coverage', review.get('requirements', {}))
    requirement_rows = raw if isinstance(raw,list) else []
    if not isinstance(raw, dict):
        raw = {p['id']:p.get('review') for p in requirement_rows if p.get('id')}
    points = review.get('points', requirement_rows)
    labels = {p['id']: p.get('label', p['id']) for p in task.get('facets', [])}
    reqs = task.get('required_points') or points or [dict(id=k, facet=k) for k in labels or raw]
    rows = []
    for p in reqs:
        value = raw.get(p['id'], raw.get(p.get('facet')))
        point = next((r for r in points if r.get('id') == p['id']), {})
        value = point.get('review', value)
        if isinstance(value, dict):
            value = value.get('status')
        text = str(value).lower() if value is not None else ''
        status = next((s for s in ('missing', 'partial', 'met') if text.startswith(s)), 'unknown')
        rows.append(dict(id=p['id'], facet=p.get('facet', p['id']), label=labels.get(p.get('facet'), p['id']),
                         requirement=p.get('description', ''), status=status, review=value))
    return rows


def visible_units(folder):
    value = read(folder / 'v1.json', read(folder / 'projection.json', {}))
    return [(s.get('facet'), c) for s in value.get('slides', []) if s.get('displayed')
            for c in s.get('checks', []) if c.get('status') == 'verified']


def vendor_metrics(folder, reads, units, root=DELIVERY_ROOT):
    """Current classifier, saved source bytes only. Both read and shown denominators."""
    from matn_research.source_type import classify, page_metadata, RULE
    labels = {}; independent=set()
    for row in reads:
        if row.get('status') != 'complete' or not row.get('doc_id'):
            continue
        original = folder / 'sources' / Path(row.get('folder', '')).name / 'original.bin'
        if not original.exists() and row.get('folder'):
            original = Path(root) / row['folder'] / 'original.bin'
        metadata = None
        if row.get('coverage', {}).get('kind') == 'html' and original.exists():
            metadata = page_metadata(original.read_bytes())
        labels[row['doc_id']] = classify(row.get('final_url') or row.get('url', ''), metadata)['label']
        if row.get('independent',True):
            independent.add(row['doc_id'])
    shown = [c.get('display', {}).get('support', {}).get('doc_id') for _, c in units]
    return dict(rule=RULE, sources_vendor=sum(labels[d] == 'commercial-vendor' for d in independent),
                sources_total=len(independent), sources_other=sum(labels[d]=='other' for d in independent),
                shown_vendor=sum(labels.get(d) == 'commercial-vendor' for d in shown),
                shown_other=sum(labels.get(d)=='other' for d in shown),shown_unknown=sum(d not in labels for d in shown),
                shown_total=len(shown), sources=labels)


def _first_verified(state,folder):
    value = state.get('first_verified_seconds')
    if value is not None:
        return value
    times=[]
    for name,j in state.get('jobs',{}).items():
        if not (name.startswith('verify') and j.get('status')=='complete' and j.get('ended_at')):
            continue
        checkpoint=read(Path(folder)/j.get('path',''),{})
        if any(c.get('status')=='verified' for s in checkpoint.get('slides',[]) for c in s.get('checks',[])):
            times.append(j['ended_at'])
    return round(min(times) - state['started_at'], 1) if times and state.get('started_at') else None


def summarize(run_id, folder, root=DELIVERY_ROOT, saved=None, diagnosis=None):
    folder = Path(folder).resolve(); root = Path(root).resolve(); saved = saved or {}
    state = read(folder / 'state.json', {})
    outcome = read(folder / 'outcome.json', state.get('outcome') or {})
    meta = read(folder / 'dashboard-run.json', {})
    brief = state.get('brief', read(folder / 'brief.json', {}))
    brief = brief.get('brief', brief)
    request = read(folder / 'request.json', {})
    task = read(folder / 'task-freeze.json', {}).get('task', {})
    rp = review_path(folder)
    review = read(rp, {}) if rp else {}
    if saved.get('review_path'):
        rp = root / saved['review_path']; review = read(rp, review)
    semantic_review = read(folder / 'coverage-review.json', {})
    if not review.get('points') and semantic_review.get('points'):
        review = dict(review, points=semantic_review['points'])
    axes = coverage_items(review, task)
    reads = read(folder / 'reading-status.json', [])
    units = visible_units(folder)
    progress = read(folder / 'progress.json', {})
    counts = saved.get('calls') or progress.get('calls_used') or {}
    last_result = next((r for r in read(root / 'out/leap-20261030/results.json', [])
                        if r['run'].replace('holdout-', '').replace('dev-H', 'devH') == run_id), {})
    counts = counts or last_result.get('calls') or {}
    first = None if saved.get('classification')=='baseline' else _first_verified(state,folder)
    if first is None:
        first = last_result.get('first_verified_s')
    seconds = outcome.get('seconds', saved.get('seconds', last_result.get('total_s')))
    if seconds is None and meta.get('done') and meta.get('ended_at'):
        seconds=round(meta['ended_at']-meta['started_at'],1)
    code = meta.get('code', 'delivery' if run_id in set('NOPQ') else 'delivery ancestor' if run_id in KNOWN else 'unknown (unrecorded)')
    identity = meta.get('code_identity') or saved.get('code_evidence', {}).get('saved_artifact_code_sha256')
    if run_id in 'NOPQ' and len(run_id) == 1:
        identity = read(root / 'out/leap-20261030/code-round2-freeze.json', {}).get('code_identity_sha256')
    if run_id == 'devH':
        identity = read(root / 'out/leap-20261030/code-v2-freeze.json', {}).get('sha256')
    errors = review.get('silent_errors', review.get('counts', {}).get('silent_errors', saved.get('silent_errors')))
    error_total = (sum(errors.values()) if isinstance(errors, dict) and all(type(v) is int for v in errors.values())
                   else errors if type(errors) is int else None)
    if error_total is None and 'total_errors' in last_result:
        error_total = last_result['total_errors']
    if not (folder / 'index.html').exists():
        error_total = None  # an empty failure cannot establish error-free output
    borderline = sum(bool(u.get('borderline')) for u in review.get('units', []))
    accepted_borderline = sum(bool(u.get('borderline')) and u.get('human_review') == 'ACCEPTED_BY_OWNER'
                             for u in review.get('units', []))
    diag_axes = (diagnosis or {}).get('axes', [])
    for axis in axes:
        d = next((a for a in diag_axes if a.get('id', a.get('axis')) == axis['id']), None)
        reason = review.get('earliest_loss', {}).get(axis['id'], review.get('earliest_loss', {}).get('all'))
        if d:
            axis['diagnosis'] = d
        elif axis['status'] in ('missing', 'unknown'):
            axis['diagnosis'] = dict(stage='unknown', suitable_present=None,
                reason=reason or 'No semantic stage audit saved; availability is unknown.', evidence=[str(rp)] if rp else [])
    semantic = [a for a in axes if a['status'] != 'unknown']
    covered_facets = {a['facet'] for a in semantic if a['status'] in ('met', 'partial')}
    planned_facets = {a['facet'] for a in axes}
    missing_facets={f for f in planned_facets if all(a['status']=='missing' for a in axes if a['facet']==f)}
    display_facets={f for f,c in units} if (folder/'index.html').exists() else set()
    display_coverage=dict(planned=len(planned_facets),covered=len(planned_facets & display_facets),
                          empty=len(planned_facets-display_facets))
    coverage = dict(planned=len(planned_facets), covered=len(covered_facets) if semantic else None,
                    empty=len(missing_facets) if semantic else None,
                    unknown=len(planned_facets-covered_facets-missing_facets),
                    met=sum(a['status'] == 'met' for a in axes), partial=sum(a['status'] == 'partial' for a in axes),
                    missing=sum(a['status'] == 'missing' for a in axes), requirements=len(axes))
    review_provenance = review.get('reviewer', review.get('classification', saved.get('review_provenance')))
    explicit_kind=review.get('reviewer_type',review.get('review_kind','')).lower()
    if explicit_kind=='human':
        review_kind='human'
    elif review_provenance and 'ai' in review_provenance.lower():
        review_kind='AI'
    elif review_provenance:
        review_kind='reviewer type unknown'
    else:
        review_kind='unreviewed'
    if accepted_borderline:
        review_kind+=' + owner borderline acceptance'
    return dict(id=run_id, folder=str(folder), topic=brief.get('topic', request.get('topic', meta.get('topic',saved.get('topic', 'Unknown')))),
        audience=brief.get('audience', request.get('audience',meta.get('audience', 'Unknown'))), code=code, code_identity=identity,
        first_verified_seconds=first, first_verified_basis='saved first_verified_seconds' if state.get('first_verified_seconds') is not None
            else 'first completed verify checkpoint with verified units' if first is not None else 'unavailable',
        total_seconds=seconds, timing_scope=saved.get('time_scope', 'saved outcome; excludes preflight'),
        calls={k:counts.get(k) for k in ('generation', 'native')},
        searches=saved.get('searches',state.get('search_attempts',last_result.get('searches'))),
        sources_read=sum(r.get('status') == 'complete' and r.get('independent', True) for r in reads),
        sources_failed=sum(r.get('status') == 'failed' for r in reads), vendor=vendor_metrics(folder, reads, units,root),
        coverage=coverage, display_coverage=display_coverage, axes=axes, units_shown=len(units) if (folder / 'index.html').exists() else 0,
        verified_but_not_shown=len(units) if not (folder / 'index.html').exists() else 0,
        page_exists=(folder / 'index.html').exists(), review_provenance=review_provenance or 'UNREVIEWED',
        review_kind=review_kind,
        silent_errors=error_total, borderline=borderline, borderline_accepted=accepted_borderline,
        review_path=str(rp) if rp else None, status=meta.get('status',outcome.get('status', 'FAILED: no page' if not (folder / 'index.html').exists() else 'saved')),
        failure_page=meta.get('failure_page',False),
        evidence=[str(p) for p in (folder / 'state.json', folder / 'task-freeze.json', folder / 'reading-status.json') if p.exists()])


def discover(root):
    """All saved research states, excluding code mirrors and internal checkpoints."""
    found = []
    for base, dirs, files in os.walk(Path(root) / 'out'):
        dirs[:] = [d for d in dirs if not d.startswith(('code', '.', 'embedding')) and d not in
                   ('sources', 'jobs', 'raw', 'payloads', 'versions', 'fallback-mirror', 'gallery-v4', 'replays', 'replays-v2')]
        if 'dashboard-run.json' in files:
            found.append(Path(base).resolve())
        elif 'state.json' in files:
            state = read(Path(base) / 'state.json', {})
            brief = state.get('brief', {})
            if isinstance(brief, dict) and (brief.get('topic') or brief.get('brief', {}).get('topic')):
                found.append(Path(base).resolve())
    return found


def collect(root=DELIVERY_ROOT, extra=()):
    root = Path(root).resolve()
    saved_rows = read(root / SENIOR / 'metrics.json', {}).get('runs', [])
    saved = {r['run_id']: r for r in saved_rows if r.get('displayed_version') == 'original'}
    diagnostics = read(root / 'out/research-v2/diagnosis.json', {}).get('runs', {})
    if isinstance(diagnostics, list):
        diagnostics = {r['run']: r for r in diagnostics}
    paths = {k: root / p for k, p in KNOWN.items() if (root / p).exists()}
    known_paths = {p.resolve() for p in paths.values()}
    for folder in [*discover(root), *(Path(p) for p in extra)]:
        if folder.resolve() in known_paths:
            continue
        name = str(folder.relative_to(root / 'out')) if folder.is_relative_to(root / 'out') else folder.name
        paths[name] = folder; known_paths.add(folder.resolve())
    rows = [summarize(k, p, root, saved.get(k), diagnostics.get(k)) for k, p in paths.items()]
    historical_vendor=read(root/'out/research-v2/vendor-diagnosis.json',{}).get('runs',{})
    for row in rows:
        prior=historical_vendor.get(row['id'],{})
        if prior:
            row['vendor']['recorded_delivery']=dict(sources_vendor=prior.get('source_vendor_count'),
                sources_total=prior.get('source_count'),shown_vendor=prior.get('displayed_vendor_count'),
                shown_total=prior.get('displayed_unit_count'))
    benches = []
    for p in sorted((root / 'out').glob('**/bench.json')):
        if any(part.startswith('code-') for part in p.parts):
            continue
        value = read(p, {})
        if value.get('summary'):
            benches.append(dict(path=str(p), modified_at=p.stat().st_mtime, summary=value['summary'],
                                errors={k:r['error'] for k,r in value.get('topics', {}).items() if 'error' in r}))
    return dict(schema=1, method='Saved artifacts only; zero network, model and search calls.',
                runs=rows, benches=benches, diagnosis_path=str(root / 'out/research-v2/diagnosis.json'))
