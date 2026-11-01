"""Compact review sheet for one result: requirements, displayed units with exact context, synthesis.

Read-only; for cross-family AI review (not human gold, not independent of the implementer).
  .venv/bin/python -B -m eval.research.review_dump RUN_FOLDER > review.md
"""
import json
from pathlib import Path
import sys


def dump(folder):
    folder = Path(folder); out = []
    state = json.loads((folder / 'state.json').read_bytes())
    brief = json.loads((folder / 'brief.json').read_bytes())
    out.append('# ' + brief['brief']['topic'] + ' — ' + brief['brief']['audience'])
    o = state.get('outcome', {})
    out.append('outcome: ' + json.dumps({k: o.get(k) for k in ('status', 'verified_units', 'displayed_slides', 'stop_reason',
                                                              'first_verified_seconds', 'seconds', 'degraded')}))
    for p in brief['task']['required_points']:
        out.append('- REQ ' + p['id'] + ': ' + p['description'])
    reads = json.loads((folder / 'reading-status.json').read_bytes()) if (folder / 'reading-status.json').exists() else []
    urls = {r['doc_id']: r.get('final_url') or r['url'] for r in reads if r.get('doc_id')}
    v = folder / 'v1.json'
    if not v.exists():
        out.append('NO DISPLAY'); return '\n'.join(out)
    version = json.loads(v.read_bytes())
    from matn_research.preview import unit_index
    from matn_research.source_type import classify
    ids = unit_index(version)
    for slide in version['slides']:
        out.append('\n## ' + slide['facet'] + (' (displayed)' if slide['displayed'] else ' (withheld)'))
        for c in slide['checks']:
            d = c.get('display', {}); lc = d.get('local_context') or {}
            doc = (d.get('support') or {}).get('doc_id', '')
            url = urls.get(doc, '')
            out.append('### ' + ids.get(c['binding'], '-') + ' [' + c['status'] + '] ' + ', '.join(c.get('reasons', [])[:3])
                       + ' — ' + classify(url)['label'] + ' ' + url)
            if lc.get('source_title'):
                out.append('  title: ' + lc['source_title'])
            if lc.get('headings'):
                out.append('  headings: ' + ' / '.join(h['quote'] for h in lc['headings']))
            for x in lc.get('preceding', []):
                out.append('  context: ' + x['quote'])
            out.append('  CLAIM: ' + c['atom']['text'])
    syn = folder / 'synthesis.json'
    if syn.exists():
        s = json.loads(syn.read_bytes())
        for f, row in s.get('facets', {}).items():
            for x in row.get('sentences', []):
                out.append('SYN ' + f + ' [' + x['status'] + '] ' + x['text'] + ' ' + str(x['units']) + ' ' + ','.join(x.get('reasons', [])))
    out.append('\n## Sources')
    for doc, url in urls.items():
        out.append('- ' + classify(url)['label'] + ' ' + url)
    return '\n'.join(out)


if __name__ == '__main__':
    print(dump(sys.argv[1]))
