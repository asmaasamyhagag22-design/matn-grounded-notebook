"""Conservative lexical source triage, not semantic acceptance or authority proof."""
import re

STOP = set('what which should must how the and for from with before after this that their only public source sources explain check describe identify useful material appropriate does have about into when under know planners fixture question planning axis explicit detail details synthetic requirement requirements'.split())


def terms(text):
    return {w for w in re.findall(r'[a-z]{4,}', text.lower()) if w not in STOP}


def assess(hit, document, facet, points):
    wanted = terms(' '.join([facet.get('query', facet.get('question','')), facet.get('label',''), *[p['description'] for p in points]]))
    text = ' '.join(e.block.text for e in document.elements)
    content_matches = sorted(wanted & terms(text))
    metadata_matches = sorted(wanted & terms(str(hit.get('title','')) + ' ' + str(hit.get('content',''))))
    return dict(status=('unknown' if not wanted else 'candidate' if content_matches else 'unsuitable'),
        reason='No discriminating facet terms; suitability cannot be assessed lexically' if not wanted else 'Readable content has facet terms; authority and semantic sufficiency remain unknown' if content_matches else 'Readable content has no facet terms; fetch success is insufficient',
        content_matches=content_matches, metadata_matches=metadata_matches,
        authority='unknown', source_type='unknown', semantic_suitability='unknown')
