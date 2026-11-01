"""CPU-only source-unit ranking; normalization changes retrieval, never evidence."""
import hashlib
import re
from matn_rag.contracts import canonical
from matn_rag.scoring import bm25
from matn_rag.tokenizer import tokenize
from matn_chat.evidence_selection import IGNORE

# Collective/person vocabulary for candidate matching only. These identities
# are deliberately absent from claim verification and actor authorization.
ALIASES={'workforce':'worker','employee':'worker','staff':'worker'}
FUNCTION_WORDS=IGNORE | set('who why where when into according their whose regarding based say says report'.split())


def normalized(text):
    result=[]
    for token in tokenize(text):
        word=token.base
        if re.fullmatch('[a-z]+',word):
            if word.endswith('ing') and len(word)>5:word=word[:-3]
            elif word.endswith('s') and len(word)>3 and not word.endswith('ss'):word=word[:-1]
            word=ALIASES.get(word,word)
        if word not in FUNCTION_WORDS:result.append(word)
    return ' '.join(result)


def method_question(question):
    return bool(re.search(r'\b(method|methodology|calculate|calculated|calculation|sampling|definition|define|mean|user guide|taxonomy|survey coverage|sample size)\b',question,re.I))


def exclusion(question, hit):
    text=hit['text'].strip()
    if not text.rstrip('"”\')]').endswith(('.', '!', '?')) or text.endswith('...'):
        return 'incomplete_prose_unit'
    path=' '.join(hit.get('section_path',[])[:3])
    if re.search(r'\b(methodology|user guide|survey design)\b',path,re.I) and not method_question(question):
        return 'method_section_for_findings_question'
    return None


class LexicalBlockRanker:
    def __init__(self):self.calls=[]
    def rank(self,question,hits):
        from .reliable import subquestions
        binding=hashlib.sha256(canonical(dict(query=getattr(question,'retrieval_text',question),hits=[dict(id=h['chunk_id'],text=h['text'],section_path=h.get('section_path',[])) for h in hits]))).hexdigest()
        excluded=[dict(block_id=h.get('block_id'),reason=exclusion(question,h)) for h in hits if exclusion(question,h)]
        eligible=[h for h in hits if not exclusion(question,h)]
        records=[dict(h,text=normalized(h['text'])) for h in eligible];by={h['chunk_id']:h for h in eligible}
        rankings=[];scores=[]
        for part in subquestions(question):
            ranked=[(cid,score) for cid,score in bm25(records,normalized(getattr(part,'retrieval_text',part)),False) if score>0]
            rankings.append([cid for cid,score in ranked]);scores.append(dict(ranked))
        ordered=[];seen=set()
        # Coverage is per explicitly requested question part, never per source.
        for i in range(max(map(len,rankings),default=0)):
            for ranking in rankings:
                if i<len(ranking) and ranking[i] not in seen:ordered.append(ranking[i]);seen.add(ranking[i])
        result=[]
        for cid in ordered:
            result.append(dict(by[cid],block_lexical_scores=[s.get(cid,0.) for s in scores],
                ranking_policy='source-unit-bm25-round-robin-explicit-parts-v1'))
        self.calls.append(dict(binding=binding,policy='source-unit-bm25-v1',new_model_calls=0,
            input_blocks=len(hits),eligible_blocks=len(eligible),excluded=excluded,
            question_parts=subquestions(question),normalization='english-inflection-collective-v1',proof=False))
        return result
