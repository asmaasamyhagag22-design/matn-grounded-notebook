"""Readable Markdown over an immutable V2 result; no inference or fact rewriting."""
from .units import render


def readable(version, source_urls=None, *, source_labels=None, synthesis=None, unit_ids=None, source_identities=None):
    """Optional round-2 extras (labels, verified synthesis, unit IDs) are display only."""
    render(version)  # integrity and canonical visibility contract
    source_urls=source_urls or {};unit_ids=unit_ids or {}
    tag=lambda c:(' ('+source_labels.get(c['doc_id'],'other · unknown')+')') if source_labels is not None else ''
    references=[]
    def ref(c):
        if c not in references:references.append(c)
        return f'[{references.index(c)+1}]'
    lines=['# Evidence-backed storyboard','',f"Audience: {version['task']['audience']}",'']
    for slide,facet in zip(version['slides'],version['task']['facets']):
        lines += ['## '+facet['label'],'']
        if not slide['displayed']:
            lines += ['Content gap: support or required context has not been established.',''];continue
        shown=[x for x in (synthesis or {}).get('facets',{}).get(slide['facet'],{}).get('sentences',[]) if x.get('status')=='shown']
        if shown:
            lines += ['**ملخص من الأدلة المعروضة**','']+[x['text']+' '+''.join('['+u+']' for u in x['units']) for x in shown]+['']
        for receipt in slide['checks']:
            display=receipt['display']
            uid=unit_ids.get(receipt['binding'])
            local=display.get('local_context')
            if local:
                identity=(source_identities or {}).get(display['support']['doc_id'],{})
                title_ref=local.get('source_title_citation')
                source_title=local['source_title'] if title_ref else identity.get('source_title') or local['source_title']
                lines += ['**Source: '+source_title+'**'+tag(display['support'])+(' '+ref(title_ref) if title_ref else ''),'']
                if local['headings']:
                    lines += ['Governing heading: '+' › '.join(c['quote'].strip()+' '+ref(c) for c in local['headings']),'']
                for c in local['preceding']:
                    lines += ['> Local source context (display only; not a verified claim): '+c['quote'].strip()+' '+ref(c),'']
            for c in display['context']:
                label='Source-backed context: ' if c.get('origin')=='source-backed context' else 'Context: '
                lines += [label+c['quote'].strip()+' '+''.join(ref(x) for x in c.get('citations',[c]))+''.join(ref(x) for x in display.get('context_alias_definitions',[])),'']
            claim='**'+display['text']+'**' if local else display['text']
            lines += [('**'+uid+'** ' if uid else '')+claim+' '+ref(display['support'])+''.join(ref(d) for d in display.get('alias_definitions',[]))+('' if local else tag(display['support'])),'']
    lines += ['## Source references','']
    for i,c in enumerate(references,1):
        url=source_urls.get(c["doc_id"])
        if url:
            anchor=f"#page={c['pdf_page_index']+1}" if ".pdf" in url else ""
            lines += [f"[{i}] [Original source]({url}{anchor}){tag(c)}", ""]
        lines += [f"[{i}] PDF p.{c['pdf_page_index']+1}; {c['doc_id']}; {c['block_id']} [{c['start']}:{c['end']}].",'']
    lines += [f"Version: {version['version']}"]
    return '\n'.join(lines)
