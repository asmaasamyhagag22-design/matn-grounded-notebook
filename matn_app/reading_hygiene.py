"""Reading-region labels, not truth permissions; the existing verifier still decides."""
from collections import Counter
from statistics import median
import re

LABELS=dict(body='Body',footnote='Footnote',caption='Caption',toc='Contents',
            reference_list='References',acknowledgement='Acknowledgements',boilerplate='Page furniture')


def _value(value):
    return getattr(value,'value',value)


def regions(document):
    by_page={}
    headings={}
    sizes=[]
    for e in document.elements:
        by_page.setdefault(e.block.page_index,[]).append(e)
        size=getattr(getattr(e.block,'style',None),'font_size_pt',None)
        if size and len(e.block.text.split())>=12 and _value(e.role) not in ('heading','header','footer'):
            sizes.extend([size]*min(100,len(e.block.text.split())))
        if _value(e.role)=='heading':
            headings.setdefault(' '.join(e.block.text.split()).casefold(),set()).add(e.block.page_index)
    repeated={text for text,pages in headings.items() if len(pages)>=2 and len(text)>=12}
    body_size=median(sizes) if sizes else 0
    heights={p.pdf_page_index:p.height for p in document.pages}
    labels={}
    for page,elements in by_page.items():
        headings='\n'.join(e.block.text for e in elements if _value(e.role)=='heading')
        genre=None
        if re.search(r'(?im)^\s*(?:contents|table of contents|list of (?:figures|tables)|figures and tables)\s*$',headings):genre='toc'
        elif re.search(r'(?im)^\s*(?:appendix\s+\w+:\s*)?(?:bibliography|references|acronyms|abbreviations|glossary)\s*$',headings):genre='reference_list'
        elif re.search(r'(?i)\backnowledg(?:e?ments?|ements?)\b',headings):genre='acknowledgement'
        elif re.search(r'(?im)^(?:obtaining copies|order by phone|connect with|to report fraud|external liaison)\b',headings):genre='boilerplate'
        for e in elements:
            role=str(_value(e.role));kind=str(_value(e.block.block_type));text=e.block.text.strip()
            size=getattr(getattr(e.block,'style',None),'font_size_pt',None)
            box=e.block.bbox
            small_bottom_note=bool(body_size and size and size<body_size*.85 and box
                and box[1]>=heights.get(page,float('inf'))*.6 and len(text.split())>=8)
            if role in ('header','footer') or kind in ('header','footer'):label='boilerplate'
            elif role=='footnote' or kind=='footnote':label='footnote'
            elif re.search(r'\.{4,}\s*(?:\d+|[ivxlcdm]+)?\s*$',text,re.I):label='toc'
            elif role in ('caption','figure') or kind in ('caption','figure') or re.match(r'^(?:Figure|Fig\.)\s+[A-Z0-9]+\s*[:.—]',text):label='caption'
            elif genre:label=genre
            elif small_bottom_note:label='footnote'
            elif role=='heading' and ' '.join(text.split()).casefold() in repeated:label='boilerplate'
            elif re.match(r'(?i)^(?:copyright|all rights reserved|this is a work of the (?:u\.?s\.?|united states) government)',text):label='boilerplate'
            else:label='body'
            labels[e.block.block_id]=label
    return labels


def eligible_handles(handles,document,question=''):
    labels=regions(document);by={e.block.block_id:e for e in document.elements}
    result={}
    for key,h in handles.items():
        refs=h['citations']
        if any(not allowed(labels.get(c['block_id'],'body'),question) for c in refs):continue
        # The general meaning-unit builder can join an unfinished heading to a
        # lowercase continuation. Headings are orientation, never antecedents
        # that turn that continuation into an independent factual sentence.
        if any(_value(by[c['block_id']].role)=='heading' and labels[c['block_id']]=='body' for c in refs):continue
        text=h['text'].lstrip(' \t\n\"“\'‘-•')
        if text[:1].islower() and not re.match(r'^[a-z][A-Z]',text):continue
        result[key]=h
    return result


def allowed(kind,question=''):
    if kind=='body':return True
    patterns=dict(footnote=r'\b(?:footnotes?|endnotes?)\b',
        reference_list=r'\b(?:references?|bibliograph\w*|acronyms?|abbreviations?|glossary|papers cited|cited papers)\b',
        caption=r'\b(?:figures?|captions?|illustrations?|images?|charts?)\b',
        acknowledgement=r'\b(?:acknowledg\w*|authors?|prepared (?:by|the))\b',
        toc=r'\b(?:table of contents|contents page)\b',
        boilerplate=r'\b(?:copyright|licen[sc]e|publisher|contact details)\b')
    return bool(re.search(patterns.get(kind,r'(?!)'),str(question),re.I))


def summary(document,labels):
    return dict(doc_id=document.doc_id,counts=dict(Counter(labels.values())),
                policy='Body evidence by default; footnotes and references require an explicit question.')


def shortlist(handles,document,limit=12):
    """Transparent salience candidates; the local model ranks these exact units."""
    handles=eligible_handles(handles,document)
    labels=regions(document)
    owners={e.block.block_id:e for e in document.elements}
    scored=[]
    for position,(key,h) in enumerate(handles.items()):
        text=h['text'].strip();refs=h['citations']
        if not refs or any(labels.get(c['block_id'])!='body' for c in refs):continue
        if not 8<=len(text.split())<=160 or not text.rstrip('\"”\')]').endswith(('.','!','?')):continue
        if re.match(r'(?i)^(?:for one thing|in addition|this|it|these|those)\b',text):continue
        if not all(owners[c['block_id']].citable for c in refs):continue
        page=owners[refs[0]['block_id']].block.page_index
        section=' '.join(dict.fromkeys(' '.join(p[-2:]) for p in h.get('source_sections',[])))
        score=4*bool(re.search(r'(?i)\b(?:summary|conclusions?|findings?|recommendations?)\b',section))
        score+=2*bool(re.search(r'(?i)\bframework principle\b',section))
        score-=3*bool(re.search(r'(?i)\bappendix\b',section))
        score+=len(re.findall(r'(?i)\b(?:should|must|important|critical|therefore|in summary|findings|recommend)\b',text))
        score+=2 if page < max(12,len(document.pages)//5) else 0
        score-=1 if re.search(r'(?i)\b(?:methodology|forum participants|literature we reviewed)\b',text) else 0
        scored.append((-score,position,page,key,h))
    result={};pages=Counter()
    for _,_,page,key,h in sorted(scored):
        if pages[page]>=2:continue
        result[key]=h;pages[page]+=1
        if len(result)>=limit:break
    # Diversity is a first pass, not a two-sentence cap on short documents.
    for _,_,page,key,h in sorted(scored):
        if len(result)>=limit:break
        if key not in result:result[key]=h
    return result
