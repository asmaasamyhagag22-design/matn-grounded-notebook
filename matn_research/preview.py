"""Pure local preview of verified display, reading status and open gaps."""
from html import escape
import json
from pathlib import Path
from matn_storyboard.unit_markdown import readable


def source_balance(version,reads):
    from .source_type import for_records
    labels=for_records(reads)
    cited={c['display']['support']['doc_id'] for s in (version or {}).get('slides',[]) if s['displayed'] for c in s['checks'] if c.get('display')}
    vendor=sum(labels.get(doc,{}).get('label')=='commercial-vendor' for doc in cited)
    return dict(cited_sources=len(cited),commercial_sources=vendor,
                share=vendor/len(cited) if cited else None,
                warning='Sources are mostly commercial; independent coverage is limited.' if vendor>len(cited)/2 else None)


def render(folder, version=None, *, label=None):
    folder = Path(folder)
    def read(name, default):
        p = folder / name
        return json.loads(p.read_bytes()) if p.exists() else default
    state = read('state.json', {})
    outcome = read('outcome.json', state.get('outcome', {}))
    brief = state.get('brief', read('request.json', {}))
    reads = read('reading-status.json', [])
    gaps = read('gaps.json', {}).get('open', [])
    compact = version and version['style'].get('density') == 'compact'
    # Round-2 display (source-type labels, verified synthesis) only for runs that
    # enabled those features; earlier saved results render exactly as before.
    features = state.get('features', {})
    local_display=bool(version and any(c.get('display',{}).get('local_context')
                       for s in version['slides'] for c in s['checks']))
    labels = None
    identities={}
    if features or local_display:
        from .source_type import for_records, text as label_text
        labels = {k: label_text(v) for k, v in for_records(reads).items()}
    if local_display:
        from .source_type import identities_for_records
        identities=identities_for_records(reads)
    synthesis = read('synthesis.json', {}) if features.get('synthesis') else {}
    unit_ids = unit_index(version) if version and features else {}
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Matn · Topic research</title>',
             '<style>body{font-family:sans-serif;background:#f4f6f8;color:#183342;max-width:1000px;margin:40px auto;padding:0 24px}h1{font-size:30px}h2{font-size:21px}article,section{background:white;padding:24px;border-radius:12px;margin:18px 0;line-height:1.6}article{border-left:4px solid #16756a}.context{color:#486573}.badge{color:#785011}.gap{border-left:4px solid #b78635}a{color:#126568}small{overflow-wrap:anywhere}li{margin:8px 0}.compact article{padding:12px;margin:8px 0;line-height:1.3}.stype{color:#5b6b75;font-size:13px;background:#eef2f4;border-radius:6px;padding:1px 6px;margin-inline-start:6px}.synth{background:#f1f7f5;border-radius:8px;padding:10px 14px;margin:8px 0 14px}.synth h3{font-size:15px;margin:0 0 6px}.uid{color:#16756a;font-size:12px;margin-inline-end:6px}</style>',
             '<body class="' + ('compact' if compact else 'regular') + '"><header><p>مَتن · Topic research</p><h1>' + escape(brief.get('topic', 'Research preview')) + '</h1>',
             '<p>' + escape(brief.get('audience', '')) + '</p><p class="badge">' + escape(label or state.get('classification', '')) + '</p>',
             '<p>' + escape({'AI_REVIEW_REQUIRED': 'Ready for AI review', 'BLOCKED': 'Research needs setup', 'INCOMPLETE': 'Research incomplete'}.get(outcome.get('status'), outcome.get('status', 'Saved presentation'))) + '</p></header>']
    balance=source_balance(version,reads)
    if balance['warning']:parts.append('<section class="gap"><strong>'+escape(balance['warning'])+'</strong></section>')
    sources = {}
    for r in reads:
        if r.get('status') == 'complete' and r.get('independent', True):
            sources.setdefault(r['doc_id'], r)
    references = []
    def cite(c):
        if c not in references:
            references.append(c)
        return '<a href="#ref' + str(references.index(c) + 1) + '">[' + str(references.index(c) + 1) + ']</a>'
    if version:
        readable(version)  # existing immutable version and display integrity gates
        for s, f in zip(version['slides'], version['task']['facets']):
            parts.append('<article><h2>' + escape(f['label']) + '</h2>')
            if not s['displayed']:
                parts.append('<p>Evidence or required context is missing. This slide is withheld.</p>')
            else:
                shown = [x for x in synthesis.get('facets', {}).get(f['id'], {}).get('sentences', []) if x.get('status') == 'shown']
                if shown:
                    parts.append('<div class="synth" dir="auto"><h3>ملخص من الأدلة المعروضة</h3>' + ''.join(
                        '<p>' + escape(x['text']) + ' ' + ''.join('<a href="#' + escape(u) + '">[' + escape(u) + ']</a>' for u in x['units']) + '</p>'
                        for x in shown) + '<small>Written by the model from the units below only; each sentence was checked against its cited units.</small></div>')
                for check in s['checks']:
                    d = check['display']
                    uid = unit_ids.get(check['binding'])
                    if uid:
                        parts.append('<a id="' + uid + '"></a>')
                    local=d.get('local_context')
                    if local:
                        identity=identities.get(d['support']['doc_id'],{})
                        title_ref=local.get('source_title_citation')
                        source_title=local['source_title'] if title_ref else identity.get('source_title') or local['source_title']
                        parts.append('<aside class="local-context"><p><strong>Source: '+escape(source_title)+'</strong> '+
                                     (cite(title_ref) if title_ref else '')+
                                     ('<span class="stype">'+escape(labels.get(d['support']['doc_id'],'other · unknown'))+'</span>' if labels is not None else '')+'</p>')
                        if local['headings']:
                            parts.append('<p class="context">Governing heading: '+' › '.join(escape(c['quote'])+' '+cite(c) for c in local['headings'])+'</p>')
                        for ctx in local['preceding']:
                            parts.append('<p class="context">Local source context (display only; not a verified claim): '+escape(ctx['quote'])+' '+cite(ctx)+'</p>')
                        parts.append('</aside>')
                    for ctx in d['context']:
                        prefix = 'Source-backed context: ' if ctx.get('origin') == 'source-backed context' else 'Context: '
                        parts.append('<p class="context">' + prefix + escape(ctx['quote']) + ' ' +
                                     ''.join(cite(c) for c in ctx.get('citations', [ctx])) + '</p>')
                    claim='<mark>'+escape(d['text'])+'</mark>' if local else escape(d['text'])
                    parts.append('<p>' + ('<span class="uid">' + uid + '</span>' if uid else '') + claim + ' ' + cite(d['support']) +
                                 ''.join(cite(c) for c in d.get('alias_definitions', []) + d.get('context_alias_definitions', [])) +
                                 ('<span class="stype">' + escape(labels.get(d['support']['doc_id'], 'other · unknown')) + '</span>' if labels is not None and not local else '') + '</p>')
            parts.append('</article>')
    if gaps or outcome.get('status') == 'BLOCKED':
        parts.append('<section class="gap"><h2>Open questions</h2><ul>')
        descriptions = {p['id']:p['description'] for p in (version or {}).get('task',{}).get('required_points',[])}
        for g in gaps:
            parts.append('<li>'+escape(g.get('label',str(g))))
            missing=g.get('missing_points',[])
            if missing:
                parts.append('<ul>'+''.join('<li>'+escape(descriptions.get(k,k))+'</li>' for k in missing)+'</ul>')
            if g.get('next_question'):parts.append('<p>'+escape(g['next_question'])+'</p>')
            parts.append('</li>')
        messages = {'TAVILY_API_KEY_MISSING': 'Add your Tavily search key to start research.', 'FREE_QUOTA_AND_SPENDING_DISABLED_PROOF_MISSING': 'Confirm that your account has free search credits and paid spending is disabled.'}
        parts.extend('<li>' + escape(messages.get(reason, 'Research setup is incomplete.')) + '</li>' for reason in outcome.get('reasons', []))
        parts.append('</ul></section>')
    deck = folder / 'deck'
    if (deck / 'deck_qa.json').exists():
        qa = json.loads((deck / 'deck_qa.json').read_bytes())
        parts.append('<section><h2>Deck</h2><p><a href="deck/deck.pdf">PDF</a> · <a href="deck/deck.pptx">PPTX</a> · '
                     '<a href="deck/deck_qa.html">QA ' + escape(qa.get('status', '')) + '</a></p></section>')
    parts.append('<section><h2>Sources read</h2><ul>')
    for r in reads:
        description = 'Read' if r['status'] == 'complete' else 'Reading failed'
        if r.get('independent') is False:
            description += ' · duplicate content'
        parts.append('<li><a rel="noreferrer" href="' + escape(r['url'], quote=True) + '">' + escape(r['url']) + '</a> — ' + description)
        if labels is not None and r['status'] == 'complete' and r.get('doc_id') in labels:
            parts.append('<span class="stype">' + escape(labels[r['doc_id']]) + '</span>')
        if r.get('coverage'):
            coverage = r['coverage']
            text = (str(len(coverage['read_pages'])) + ' of ' + str(coverage['total_pages']) + ' PDF pages') if coverage['kind'] == 'pdf' else coverage['scope']
            parts.append('<br><small>' + escape(text if coverage['kind'] == 'pdf' else 'Static article text; partial reading') + '</small>')
        parts.append('</li>')
    parts.append('</ul></section>')
    if references:
        parts.append('<details><summary>Citation details</summary><ol>')
        for i, c in enumerate(references, 1):
            source = sources.get(c['doc_id'], {})
            is_pdf = source.get('coverage', {}).get('kind') == 'pdf' or (not source and c.get('page_label') != 'HTML')
            location = ('PDF page ' + str(c['pdf_page_index'] + 1)) if is_pdf else 'HTML text block'
            url = source.get('final_url', '')
            parts.append('<li id="ref' + str(i) + '"><a rel="noreferrer" href="' + escape(url, quote=True) + '">' + location + '</a>' +
                         ('<span class="stype">' + escape(labels.get(c['doc_id'], 'other · unknown')) + '</span>' if labels is not None else '') +
                         '<br><small>' + escape(c['block_id']) + ' [' + str(c['start']) + ':' + str(c['end']) + ']</small></li>')
        parts.append('</ol></details>')
    parts.append('</body></html>')
    return ''.join(parts)


def unit_index(version):
    """Stable displayed-unit IDs (U1, U2, ...) in display order, keyed by receipt binding."""
    ids = {}
    for s in version['slides']:
        if s['displayed']:
            for check in s['checks']:
                ids.setdefault(check['binding'], 'U' + str(len(ids) + 1))
    return ids


def publish(folder, version=None, *, name='index.html', label=None):
    p = Path(folder) / name; p.write_text(render(folder, version, label=label), encoding='utf-8')
    if version is not None and name == 'index.html':
        reads=json.loads((Path(folder)/'reading-status.json').read_bytes()) if (Path(folder)/'reading-status.json').exists() else []
        urls={r['doc_id']:r['final_url'] for r in reads if r.get('status')=='complete'}
        state_path=Path(folder)/'state.json'
        brief=json.loads(state_path.read_bytes()).get('brief',{}) if state_path.exists() else {}
        heading=brief.get('topic','Topic research')
        features=json.loads(state_path.read_bytes()).get('features',{}) if state_path.exists() else {}
        extras={}
        if features:
            from .source_type import for_records, text as label_text
            synthesis_path=Path(folder)/'synthesis.json'
            extras=dict(source_labels={k:label_text(v) for k,v in for_records(reads).items()}, unit_ids=unit_index(version),
                        synthesis=json.loads(synthesis_path.read_bytes()) if features.get('synthesis') and synthesis_path.exists() else None)
        if any(c.get('display',{}).get('local_context') for s in version['slides'] for c in s['checks']):
            from .source_type import identities_for_records, text as label_text
            identities=identities_for_records(reads)
            extras.update(source_identities=identities,
                          source_labels={k:label_text(v) for k,v in identities.items()})
        text=readable(version,urls,**extras).replace('# Evidence-backed storyboard','# '+heading,1)
        balance=source_balance(version,reads)
        if balance['warning']:text+='\n\n> '+balance['warning']+'\n'
        (Path(folder)/'source-balance.json').write_text(json.dumps(balance,indent=2)+'\n',encoding='utf-8')
        for r in reads:
            if r.get('coverage',{}).get('kind')=='html':
                text=text.replace('PDF p.1; '+r['doc_id'],'HTML text block; '+r['doc_id'])
        gaps=json.loads((Path(folder)/'gaps.json').read_bytes()).get('open',[]) if (Path(folder)/'gaps.json').exists() else []
        descriptions={p['id']:p['description'] for p in version['task']['required_points']}
        text+='\n\n## Unresolved original requirements\n\n'
        text+='Coverage below remains unconfirmed; source references and tags alone do not establish it.\n\n'
        text+='\n'.join('- '+k+': '+descriptions.get(k,k) for g in gaps for k in g.get('missing_points',[]))+'\n'
        (Path(folder)/'research.md').write_text(text,encoding='utf-8')
    return p
