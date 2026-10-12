"""Coverage and exact saved-word/native-glyph alignment for M4 diagnostics."""
from collections import Counter
import unicodedata


def word_chars(word,native,tolerance=0.5):
    x0,y0,x1,y1=word['bbox']
    chars=[c for c in native if x0-tolerance<=c['bbox'][0] and c['bbox'][2]<=x1+tolerance and y0-tolerance<=c['bbox'][1] and c['bbox'][3]<=y1+tolerance and not c['text'].isspace()]
    chars.sort(key=lambda c:(c['bbox'][0],c['object_id']))
    text=''.join(unicodedata.normalize('NFKC',c['text']) for c in chars)
    return chars if text==word['text'] else None


def block_data(page,record,objects,source):
    if page.get('ocr') or record['block']['route']!='text_layer':return None,'OCR_OR_NON_NATIVE_ROUTE'
    native=objects.get(f"{source}/{page['page_index']}")
    if not native:return None,'NO_SAVED_NATIVE_PAGE'
    words=[w for l in record['lines'] for w in l['words']]
    if not words or not all(w.get('font_face') and w.get('size',0)>0 and len(w.get('bbox',[]))==4 for w in words):return None,'MISSING_WORD_FONT_OR_GEOMETRY'
    chars=native['chars'];matches=[word_chars(w,chars) for w in words]
    if any(x is None for x in matches):return None,'EXACT_WORD_NATIVE_GLYPH_ALIGNMENT_UNKNOWN'
    return {'chars':chars,'word_matches':matches},None


def coverage(sources,objects):
    result={}
    for key,src in sources.items():
        rows=[]
        for page in src['snapshot']['pages']:
            for r in page['blocks']:
                data,reason=block_data(page,r,objects,key)
                rows.append({'block_id':r['block']['block_id'],'pdf_page_index':page['page_index'],'known':data is not None,'reason':reason})
        result[key]={'total':len(rows),'known':sum(r['known'] for r in rows),'unknown':sum(not r['known'] for r in rows),'reasons':dict(Counter(r['reason'] for r in rows if r['reason'])),'rows':rows}
    return {'ordering':'EXACT_NATIVE_WORD_COVERAGE_BEFORE_M4_RULE_AND_CONTROLS','native_bbox_tolerance_pt':0.5,'normalization_for_matching':'NFKC of saved glyph text; no source mutation; original glyph IDs retained','sources':result}
