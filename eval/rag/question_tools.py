"""Part1 draft checks using frozen structure spans and G4 normalization only."""
from pathlib import Path
import json,re,unicodedata
from matn_rag.tokenizer import tokenize,VERSION
from eval.normalize import normalize_text,quote_on_page
FUNCTION_WORDS=frozenset(json.loads(Path(__file__).with_name('function_words.json').read_text()))

def normalized_map(text, rejoin=True):
 chars=[];coords=[]
 for i,c in enumerate(text):
  if c=='\xad':continue
  c=unicodedata.normalize('NFKC',c).translate(str.maketrans({**{c:"'" for c in '‘’‚‛′'},**{c:'"' for c in '“”„‟″'},**{c:'-' for c in '‐‑‒–—―−﹣－'}}))
  chars.extend(c);coords.extend([(i,i+1)]*len(c))
 s=''.join(chars)
 pattern=re.compile(r'(\w)-[ \t]*\r?\n\s*(\w)')
 for m in reversed(list(pattern.finditer(s))):
  a=m.start()+1;b=m.end()-1
  if rejoin: chars[a:b]=[];coords[a:b]=[]
  else: chars[a:b]=['-'];coords[a:b]=[(coords[a][0],coords[b-1][1])]
 s=''.join(chars)
 for m in reversed(list(re.finditer(r'\s+',s))):
  a,b=m.span();chars[a:b]=[' '];coords[a:b]=[(coords[a][0],coords[b-1][1])]
 while chars and chars[-1]==' ':chars.pop();coords.pop()
 while chars and chars[0]==' ':chars.pop(0);coords.pop(0)
 value=''.join(chars);assert value==normalize_text(text,rejoin_hyphens=rejoin)
 return value,coords

def spans_for(chunk,start,end):
 out=[]
 for m in chunk.offset_map:
  a=max(start,m.start);b=min(end,m.end)
  if a>=b:continue
  if m.kind=='separator':continue
  out.append({'block_id':m.block_id,'start':m.char_start+a-m.start,'end':m.char_start+b-m.start,'primary_chunk_id':m.primary_chunk_id if m.kind=='repeated_context' else chunk.chunk_id})
 return out

def locate(d,quote):
 needle=normalize_text(quote);pattern=re.compile(r'(?<!\w)'+re.escape(needle)+r'(?!\w)'); relevant=[];spans=[]
 for c in d.chunks:
  if not quote_on_page(quote,c.text):continue
  relevant.append(c.chunk_id)
  if spans:continue
  for rejoin in (True,False):
   s,mapping=normalized_map(c.text,rejoin); match=pattern.search(s)
   if match:
    spans=spans_for(c,mapping[match.start()][0],mapping[match.end()-1][1]);break
 return sorted(relevant),spans


def question_checks(question,target):
    q=[t.base for t in tokenize(question) if t.base not in FUNCTION_WORDS]
    t=[t.base for t in tokenize(target) if t.base not in FUNCTION_WORDS]
    common={tuple(q[i:i+4]) for i in range(len(q)-3)} & {tuple(t[i:i+4]) for i in range(len(t)-3)}
    return {'shared_content_4grams':sorted(common),
            'content_token_overlap_ratio':len(set(q)&set(t))/len(set(q)) if q else 0,
            'scope_numbers':[t.base for t in tokenize(question) if any(c.isdigit() for c in t.base)]}
