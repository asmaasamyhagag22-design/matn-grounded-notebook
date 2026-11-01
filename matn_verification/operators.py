"""Bounded English operator attachments, NOT a general English parser.

Supports one explicit comma-delimited initial condition or a trailing condition,
modal auxiliaries, and need-to negation. Unknown nested/ambiguous condition syntax
abstains. Predicate/condition paraphrases require separate reciprocal native
checks as well as the full forward entailment check; a word set is never proof.
"""
import re
from dataclasses import dataclass
from .prose import surface

MARKER=re.compile(r'\b(only if|only when|unless|provided that|if|when)\b',re.I)
MODAL=re.compile(r'\b(must|should|may|might|could|would|will|can|cannot)\b',re.I)

@dataclass(frozen=True)
class Structure:
    main: str
    condition: tuple | None
    operators: tuple
    unknown: bool


def structure(text):
    t=text.strip().rstrip('.');t=re.sub(r"[’]","'",t)
    if ':' in t and re.match(r'\s*if\b',t.split(':',1)[1],re.I):t=t.split(':',1)[1].strip()
    # Reporting expect-that is not permission for the following predicate.
    t=re.sub(r'\bcan expect that\b','expect that',t,flags=re.I)
    # Nominal hypothetical requirements do not expose a conditional clause.
    # No topic-specific reconstruction: these stay outside the bounded grammar.
    if re.search(r'\bhypothetical\b',t,re.I) and not MARKER.search(t):
        return Structure(t,None,(),True)
    ms=list(MARKER.finditer(t));unknown=len(ms)>1;condition=None
    if ms:
        m=ms[0];op=m[1].lower().replace('only when','only if')
        if m.start()==0:
            if ',' not in t: return Structure(t,None,(),True)
            operand,main=t[m.end():].split(',',1)
        else:main=t[:m.start()];operand=t[m.end():]
        condition=(op,operand.strip());t=main.strip()
    ops=[]
    for m in MODAL.finditer(t):
        tail=t[m.end():]; stop=re.search(r'[,;]|\band\s+\w+\s+(?:may|must|will|would|could)\b',tail,re.I)
        if stop:tail=tail[:stop.start()]
        modal=m[1].lower();negative=modal=='cannot' or bool(re.match(r'\s+not\b',tail,re.I))
        tail=re.sub(r'^\s*not\s+','',tail,flags=re.I).strip()
        # Record nested negation at its operand, not merely presence of "not".
        nested=bool(re.search(r'\b(?:need|needs|required)\s+to\s+not\b',tail,re.I))
        action=re.sub(r'^(?:be\s+)?(?:unlikely\s+to\s+)?','',tail,flags=re.I)
        anchor=re.findall(r'\b\d+(?:\.\d+)?\b',t[:m.start()])
        ops.append((('can' if modal=='cannot' else modal),negative,nested,action,anchor[-1] if anchor else None))
    # Necessity without auxiliary, including polarity scope.
    for m in re.finditer(r'\b(?:(does? not)\s+)?(need|needs)\s+(not\s+)?to\s+(not\s+)?(.+)',t,re.I):
        ops.append(('need',bool(m[1] or m[3]),bool(m[4]),m[5]))
    # "unlikely" applies to the event; removing it changes probability.
    if re.search(r'\bunlikely\b',t,re.I):ops.append(('unlikely',False,False,re.split(r'\bunlikely\b',t,flags=re.I)[1]))
    # Non-auxiliary negation still binds to the full proposition; reciprocal
    # checks must decide paraphrases rather than a negation-word count.
    if not ops and re.search(r'\b(?:no|not|never|without)\b',t,re.I):ops.append(('negative',True,False,t))
    return Structure(t,condition,tuple(ops),unknown)


def operand(text):
    # Move explicit temporal adjuncts out of an event operand. Dates and the
    # average qualifier are verified on the complete claim, not discarded there.
    t=re.sub(r'\b(?:over|during|by|in) (?:the )?\d{4}(?:[-–]\d{4})?(?: period)?\b','',text,flags=re.I)
    t=re.sub(r'\bon average\b','',t,flags=re.I)
    return re.sub(r'^(?:be|to)\s+','',t.strip(),flags=re.I).strip(' .')


# Directional relation frames: required operand -> goal, never attained effect.
# Deliberately bounded to explicit copular requirements and one requires clause.
NECESSITY = re.compile(
    r"^(.+?)\s+(?:is|are|was|were)\s+(?:(?:considered|deemed)\s+)?"
    r"(not\s+)?(?:necessary|required|essential|indispensable|a prerequisite)\s+"
    r"(?:for|to)\s+(.+)$", re.I)
NECESSITY_WORD = re.compile(r'\b(?:necessary|required|prerequisite|requires?|essential|indispensable)\b',re.I)


def necessity(text):
    t=re.sub(r'^(?:in conclusion|finally|in addition),?\s+', '', text.strip().rstrip('.'),flags=re.I)
    m=NECESSITY.fullmatch(t)
    if m:
        left,neg,right=m.groups()
        # Mixed predicates, multiple frames and relative scope are not flattened.
        if re.search(r'\b(?:which|that)\b',left,re.I) or NECESSITY_WORD.search(right):
            return None,True
        nested=bool(re.match(r'not\b',right,re.I))
        return (bool(neg),nested,left.strip(),re.sub(r'^not\s+','',right,flags=re.I)),False
    # Relative requires is retained verbatim only. No cross-frame paraphrase is
    # authorized without a resolved subject and direction.
    return None,bool(NECESSITY_WORD.search(t) and not re.search(r'\bneeds?\s+(?:not\s+)?to\b|\bneeds?\s+(?!not\b|to\b)\w+',t,re.I))


def relation_obligations(text,source):
    a,au=necessity(text);b,bu=necessity(source)
    strip=lambda t:re.sub(r'^(?:in conclusion|finally|in addition),?\s+', '',t.strip(),flags=re.I)
    if surface(strip(text))==surface(strip(source)):return [],[]
    if au or bu:return ['necessity_scope_unresolved'],[]
    if bool(a)!=bool(b):return ['necessity_relation_changed'],[]
    if not a:return [],[]
    if a[:2]!=b[:2]:return ['necessity_polarity_changed'],[]
    if surface(a[2])==surface(b[3]) and surface(a[3])==surface(b[2]):return ['necessity_direction_changed'],[]
    pairs=[]
    for x,y,role in [(a[2],b[2],'necessity-required-operand'),(a[3],b[3],'necessity-goal')]:
        if surface(x)!=surface(y):pairs.append((x,y,role))
    return [],pairs

def obligations(text,source):
    a=structure(text);b=structure(source);errors,pairs=relation_obligations(text,source)
    if a.unknown or b.unknown:errors.append('operator_scope_unresolved')
    if bool(a.condition)!=bool(b.condition):errors.append('condition_changed')
    elif a.condition:
        if a.condition[0]!=b.condition[0]:errors.append('condition_direction_changed')
        elif surface(a.condition[1])!=surface(b.condition[1]):pairs.append((a.condition[1],b.condition[1],'condition-equivalence'))
    # Subsets align by an explicit quantity anchor, not modal word counts.
    aligned=list(b.operators)
    if 0<len(a.operators)<len(b.operators):
        aligned=[]
        for x in a.operators:
            candidates=[y for y in b.operators if len(x)>4 and x[4] and len(y)>4 and x[4]==y[4]]
            if len(candidates)!=1:errors.append('operator_scope_unresolved');break
            aligned.append(candidates[0])
    if [x[:3] for x in a.operators]!=[x[:3] for x in aligned]:errors.append('operator_attachment_changed')
    else:
        for x,y in zip(a.operators,aligned):
            if surface(operand(x[3]))!=surface(operand(y[3])):pairs.append((operand(x[3]),operand(y[3]),'operator-operand-equivalence'))
    return errors,pairs
