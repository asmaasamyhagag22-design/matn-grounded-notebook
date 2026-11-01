"""Read-only live progress for a running topic. Never touches run state or calls.

A sidecar reads the files the run already writes (state.json, ledger.json,
reading-status.json, sources/) and writes progress.json plus a self-refreshing
progress.html next to them. `--watch` keeps refreshing until the run has an outcome.
"""
import argparse
from html import escape
import json
from pathlib import Path
import time

STAGES = [  # (job-name prefix, readable stage), later stages win
    ('explicit-plan', 'Planning the research axes'), ('plan', 'Planning the research axes'),
    ('search-0-', 'Searching public sources'), ('facet-batch-0-', 'Selecting evidence (first pass)'),
    ('search-1-', 'Follow-up search'), ('facet-batch-1-', 'Selecting evidence (follow-up)'),
    ('gap-search-', 'Gap filling: targeted search'), ('facet-batch-2-', 'Gap filling: selecting evidence'),
    ('draft', 'Writing the units'), ('verify', 'Verifying every unit'), ('synthesis-', 'Writing and checking the summaries'),
    ('owner-plan', 'Using the approved plan'), ('select-0', 'Choosing evidence from the shortlist'),
    ('verify-0', 'Verifying the first units'), ('select-gap', 'Gap filling: choosing evidence'), ('verify-gap', 'Verifying the gap units'),
]


def _read(path, default):
    try:
        return json.loads(Path(path).read_bytes())
    except (OSError, ValueError):
        return default


def snapshot(folder, ledger=None, planned=None, started_at=None):
    folder = Path(folder)
    state = _read(folder / 'state.json', {})
    jobs = state.get('jobs', {})
    stage = 'Starting'; running = None
    for name, row in sorted(jobs.items(), key=lambda kv: kv[1].get('started_at', 0)):
        for prefix, label in STAGES:
            if name.startswith(prefix):
                stage = label
        if row.get('status') == 'running':
            running = name
    sources = [p for p in (folder / 'sources').glob('*') if (p / 'read.json').exists()] if (folder / 'sources').exists() else []
    reads = _read(folder / 'reading-status.json', [])
    complete = sum(1 for r in reads if r.get('status') == 'complete' and r.get('independent', True))
    outcome = state.get('outcome')
    if outcome:
        stage = 'Done' if outcome.get('status') == 'AI_REVIEW_REQUIRED' else 'Stopped: ' + str(outcome.get('status'))
    calls = {}
    if ledger:
        value = _read(Path(ledger) / 'ledger.json', {})
        base = (planned or {}).get('ledger_before', {})
        calls = {k: value.get('calls', {}).get(k, 0) - base.get(k, 0) for k in ('generation', 'native')}
    start = started_at or state.get('started_at') or time.time()
    version = _read(folder / 'v1.json', None)
    verified = sum(c.get('status') == 'verified' for sl in version['slides'] for c in sl['checks']) if version else 0
    return dict(topic=state.get('brief', {}).get('topic', ''), stage=stage, running_job=running, units_verified=verified,
                first_verified_seconds=state.get('first_verified_seconds'),
                elapsed_seconds=round(time.time() - start), calls_used=calls,
                calls_planned={k: v for k, v in (planned or {}).items() if k in ('generation', 'native')},
                searches=state.get('search_attempts', 0), sources_attempted=len(sources),
                sources_read=complete, done=bool(outcome), updated_at=time.time())


def render(value):
    minutes, seconds = divmod(value['elapsed_seconds'], 60)
    calls = ''.join('<li>' + escape(k) + ': ' + str(v) + (' of ' + str(value['calls_planned'][k]) if k in value['calls_planned'] else '') + '</li>'
                    for k, v in value['calls_used'].items())
    refresh = '' if value['done'] else '<meta http-equiv="refresh" content="3">'
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">' + refresh +
            '<title>Matn · live run</title><style>body{font-family:sans-serif;background:#f4f6f8;color:#183342;max-width:720px;margin:40px auto;padding:0 20px}'
            'section{background:white;border-radius:12px;padding:20px 24px;line-height:1.7}h1{font-size:24px}.stage{font-size:22px;color:#16756a}'
            '.pulse{display:inline-block;width:10px;height:10px;border-radius:50%;background:#16756a;margin-inline-end:8px;animation:p 1.2s infinite}'
            '@keyframes p{50%{opacity:.2}}</style><body><h1>مَتن · ' + escape(value['topic'] or 'Topic research') + '</h1><section>'
            '<p class="stage">' + ('' if value['done'] else '<span class="pulse"></span>') + escape(value['stage']) + '</p>'
            '<p>Elapsed: ' + str(minutes) + ' min ' + str(seconds) + ' s</p>'
            '<p>Searches: ' + str(value['searches']) + ' · Sources read: ' + str(value['sources_read']) + ' of ' + str(value['sources_attempted']) + ' attempted</p>'
            '<p>Units verified so far: ' + str(value.get('units_verified', 0)) + ' · <a href="index.html">open the result</a></p>'
            '<p>Model calls used:</p><ul>' + calls + '</ul>'
            + ('<p><small>Current step: ' + escape(value['running_job']) + '</small></p>' if value['running_job'] else '') +
            '</section></body></html>')


def publish(folder, out=None, **kwargs):
    value = snapshot(folder, **kwargs); out = Path(out or folder)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'progress.json').write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'progress.html').write_text(render(value), encoding='utf-8')
    return value


def line(value):
    calls = ' '.join(k + '=' + str(v) + ('/' + str(value['calls_planned'][k]) if k in value['calls_planned'] else '')
                     for k, v in value['calls_used'].items())
    return '[{:>4}s] {} | searches={} sources={}/{} units={} {}'.format(value['elapsed_seconds'], value['stage'], value['searches'],
                                                             value['sources_read'], value['sources_attempted'], value.get('units_verified', 0), calls)


def main(argv=None):
    p = argparse.ArgumentParser(description='Live progress view for a Matn topic run (read-only).')
    p.add_argument('--folder', required=True); p.add_argument('--ledger'); p.add_argument('--out')
    p.add_argument('--planned', help='JSON file with generation/native plan and ledger_before counts')
    p.add_argument('--watch', action='store_true'); p.add_argument('--interval', type=float, default=3)
    p.add_argument('--quiet', action='store_true')
    a = p.parse_args(argv)
    planned = _read(a.planned, {}) if a.planned else None
    started = (planned or {}).get('started_at')
    while True:
        value = publish(a.folder, a.out, ledger=a.ledger, planned=planned, started_at=started)
        if not a.quiet:
            print(line(value), flush=True)
        if not a.watch or value['done']:
            return value
        time.sleep(a.interval)


if __name__ == '__main__':
    main()
