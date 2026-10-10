"""Rule-only splitter preserving every character; block separators are hard boundaries.

Cross-block continuation rule v1: disabled. Each reader block is a hard boundary.
"""
import re
from matn_contracts.structure import SentenceSpan
_ABBR=re.compile(r'(?:\b(?:e\.g|i\.e|Fig|No|Dr|Mr|Mrs|Ms|vs|etc)|(?:\b[A-Z]\.)+[A-Z])\.$',re.I)


def sentence_spans(text):
    result=[];start=0;i=0
    while i<len(text):
        ch=text[i]
        if ch not in '.!?': i+=1;continue
        prefix=text[:i+1]
        decimal=ch=='.' and i>0 and i+1<len(text) and text[i-1].isdigit() and text[i+1].isdigit()
        enumerator=ch=='.' and re.fullmatch(r'\s*\d+\.',prefix)
        protected=ch=='.' and (decimal or enumerator or _ABBR.search(prefix))
        if protected: i+=1;continue
        end=i+1
        while end<len(text) and text[end] in '.!?\"\'”’)]': end+=1
        if end<len(text) and not text[end].isspace(): i+=1;continue
        while end<len(text) and text[end].isspace(): end+=1
        result.append(SentenceSpan(start=start,end=end));start=end;i=end
    if start<len(text): result.append(SentenceSpan(start=start,end=len(text)))
    return tuple(result)
