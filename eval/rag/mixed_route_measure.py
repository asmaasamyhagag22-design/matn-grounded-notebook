"""Report-only comparison of saved digital and post-OCR WEF layers."""
from collections import Counter,defaultdict
from difflib import SequenceMatcher
import json
from pathlib import Path
import unicodedata
from matn_reading.structure.elements import build_elements
from matn_reading.structure.geometry import box_ref

ROOT=Path('out/rag-core/mixed-route')
INDICES=(0,19,21,32,35,37,65,66,74,75,80,83,85,87)


def words(page):
    rows=[]
    for r in page['blocks']:
        for line in r['lines']:
            for w in line['words']:
                rows.append({'text':w['text'],'role':r['block']['block_type'],'bbox':list(box_ref(w['bbox'],'word',page).coordinates),'block_id':r['block']['block_id']})
    return rows


def align(a,b):
    norm=lambda w:unicodedata.normalize('NFKC',w['text']).casefold()
    rows=[]
    for tag,i,j,k,l in SequenceMatcher(None,[norm(w) for w in a],[norm(w) for w in b],autojunk=False).get_opcodes():
        if tag=='equal':rows.extend({'operation':'match','digital':a[x],'ocr':b[y]} for x,y in zip(range(i,j),range(k,l)))
        else:
            n=min(j-i,l-k)
            rows.extend({'operation':'substitution','digital':a[i+x],'ocr':b[k+x]} for x in range(n))
            rows.extend({'operation':'deletion','digital':a[x],'ocr':None} for x in range(i+n,j))
            rows.extend({'operation':'insertion','digital':None,'ocr':b[y]} for y in range(k+n,l))
    return rows


def overlap(a,b):
    x=max(0,min(a[2],b[2])-max(a[0],b[0]));y=max(0,min(a[3],b[3])-max(a[1],b[1]))
    return x*y/max((a[2]-a[0])*(a[3]-a[1]),(b[2]-b[0])*(b[3]-b[1]))


def tokens(elements,page):
    return [{'value':n.text,'disposition':n.status,'bbox':list(n.bbox.coordinates),'bbox_precision':n.bbox.bbox_precision,'role':e.role,'citable':e.citable,'block_id':n.block_id,'start':n.start,'end':n.end} for e in elements if e.block.page_index==page for n in e.number_tokens]


def run():
    before=json.loads(Path('out/rag-core/wef-first-run/digital_read.json').read_bytes())
    after=json.loads(next(Path('out/rag-core/wef-first-run/approved-acquisition/runs').glob('*/00_reading.json')).read_bytes())
    de,_=build_elements(before);oe,_=build_elements(after);ROOT.mkdir(parents=True,exist_ok=True)
    pages=[];errors=[]
    for i in INDICES:
        dw=words(before['pages'][i]);ow=words(after['pages'][i]);alignment=align(dw,ow)
        counts=Counter(r['operation'] for r in alignment);roles=defaultdict(Counter)
        for r in alignment:roles[((r['digital'] or {}).get('role'),(r['ocr'] or {}).get('role'))][r['operation']]+=1
        dt=tokens(de,i);ot=tokens(oe,i)
        # Mutually unique best geometric counterpart; all ambiguous/unmatched
        # tokens remain explicit. Values never drive the correspondence.
        candidates={j:sorted([(overlap(d['bbox'],o['bbox']),k) for k,o in enumerate(ot) if d['bbox_precision']=='word' and o['bbox_precision']=='word'],reverse=True) for j,d in enumerate(dt)}
        reverse={k:sorted([(overlap(o['bbox'],d['bbox']),j) for j,d in enumerate(dt) if d['bbox_precision']=='word' and o['bbox_precision']=='word'],reverse=True) for k,o in enumerate(ot)}
        pairs=[];used=set();moves=Counter()
        for j,d in enumerate(dt):
            cs=candidates[j];best=cs[0] if cs else (0,None);score,k=best;rs=reverse.get(k,[])
            unique=score>=.30 and (len(cs)<2 or score>cs[1][0]) and rs and rs[0][1]==j and (len(rs)<2 or rs[0][0]>rs[1][0])
            o=ot[k] if unique else None
            if o is not None:used.add(k);moves[d['disposition']+'->'+o['disposition']]+=1
            row={'digital':d,'ocr':o,'geometry_overlap':score,'status':'matched' if o is not None else 'digital_unmatched_or_ambiguous'}
            if o and d['value']!=o['value'] and o['disposition']=='accepted':
                error={'doc_id':before['doc_id'],'pdf_page_index':i,'digital_value':d['value'],'ocr_value':o['value'],'ocr_disposition':'accepted','digital_bbox':d['bbox'],'ocr_bbox':o['bbox'],'citable':o['citable'],'classification':'measured accepted digital/OCR disagreement; native crop review pending'}
                errors.append(error);row['accepted_value_disagreement']=True
            pairs.append(row)
        pairs.extend({'digital':None,'ocr':o,'status':'ocr_unmatched_or_ambiguous'} for k,o in enumerate(ot) if k not in used)
        pages.append({'pdf_page_index':i,'digital_words':len(dw),'ocr_words':len(ow),'word_counts':dict(counts),'word_counts_by_role':[{'digital_role':a,'ocr_role':b,'counts':dict(v)} for (a,b),v in roles.items()],'alignment':alignment,'every_numeric_token':pairs,'raw_ocr_reader_tokens':after['pages'][i]['ocr']['tokens'],'disposition_moves':dict(moves)})
    result={'method':'NFKC/casefold word SequenceMatcher autojunk=false; replace gaps paired by ordinal (alignment observations, not accuracy). Numeric mutual-unique word-box overlap >=0.30, value-blind; ambiguous and region precision never assumed matched. All roles included; citable flag separate.','pages':pages,'accepted_value_disagreements':errors,'new_inference_calls':0}
    (ROOT/'measurement.json').write_text(json.dumps(result,indent=2)+'\n')
    if errors:
        import fitz
        with fitz.open('eval/incoming/wef_future_of_jobs_2025.pdf') as pdf:
            for j,e in enumerate(errors):
                box=fitz.Rect(e['digital_bbox'])|fitz.Rect(e['ocr_bbox']);box=fitz.Rect(box.x0-15,box.y0-10,box.x1+15,box.y1+10)&pdf[e['pdf_page_index']].rect
                p=ROOT/f'accepted-disagreement-{j:03}.png';pdf[e['pdf_page_index']].get_pixmap(matrix=fitz.Matrix(2,2),clip=box).save(p);e['crop']=str(p)
        (ROOT/'measurement.json').write_text(json.dumps(result,indent=2)+'\n')
    print('accepted disagreements',len(errors));print('word counts',dict(sum((Counter(p['word_counts']) for p in pages),Counter())))
    return result

if __name__=='__main__':run()
