"""Exact bounded quantities for content units, independent of legacy parsing.

No rounding tolerance. Fraction + conflicting parenthetic percentage is an
unsupported approximation, not an identity (the exact percentage remains usable).
Text fractions bind to eligible source characters; digit components additionally
require the original reader ledger and table cells.
"""
from dataclasses import dataclass, asdict
from fractions import Fraction
import re
from .numbers import parse, ONES, TENS
from . import rules

DEN = {'half':2,'halves':2,'third':3,'thirds':3,'fourth':4,'fourths':4,'quarter':4,'quarters':4,'fifth':5,'fifths':5,'sixth':6,'sixths':6,'eighth':8,'eighths':8,'tenth':10,'tenths':10}
FRACTION = re.compile(r'\b('+'|'.join(ONES|TENS)+r')[- ]('+'|'.join(DEN)+r')\b',re.I)
RATIO = re.compile(r'\b(\d+)\s*(/|out of|of)\s*(?:every\s+)?(?:hypothetical\s+)?(\d+)\b',re.I)

@dataclass(frozen=True)
class Quantity:
    raw: str
    start: int
    end: int
    value: Fraction
    unit: str
    denominator: int | None = None
    approximation: str = ''
    population: str = ''
    periods: tuple = ()
    surface_unit: str = ''

    def record(self):
        return dict(raw=self.raw,start=self.start,end=self.end,value=str(self.value),unit=self.unit,
                    denominator=self.denominator,approximation=self.approximation,population=self.population,periods=list(self.periods),surface_unit=self.surface_unit)


def quantities(text):
    result=[]; masked=list(text); problems=[]
    for pattern in (FRACTION,RATIO):
        for m in pattern.finditer(text):
            if any(masked[i]=='\0' for i in range(m.start(),m.end())):continue
            if pattern is FRACTION:
                a=(ONES|TENS)[m[1].lower()]; b=DEN[m[2].lower()]
            else:a=int(m[1]);b=int(m[3])
            if not b:problems.append('zero_denominator');continue
            prefix=text[max(0,m.start()-20):m.start()]
            approx='about' if re.search(r'\b(?:about|approximately|roughly)\s*$',prefix,re.I) else ''
            result.append(Quantity(m.group(),m.start(),m.end(),Fraction(a,b),'ratio',b,approx))
            masked[m.start():m.end()]='\0'*(m.end()-m.start())
    # A known number followed by an unrecognised fraction-like token must not
    # silently turn into that integer (two-sevenths is intentionally unsupported).
    if re.search(r'\b(?:'+'|'.join(ONES)+r')-(?:[a-z]+ths?|half|halves)\b',''.join(' ' if x=='\0' else x for x in masked),re.I):
        problems.append('unsupported_fraction')
    rest=''.join(' ' if x=='\0' else x for x in masked)
    nums,errors=parse(rest);problems.extend(errors)
    for n in nums:
        value=Fraction(n.value);unit=n.unit
        if unit in ('person','worker'):unit=''
        # Bare counts and explicitly human count units share a count dimension;
        # population identity remains a separate scope/semantic obligation.
        if unit=='percent':value/=100;unit='ratio'
        end=n.end
        suffix=re.match(r'\s*(?:%|percent\b)',text[end:],re.I) if n.unit=='percent' else None
        if suffix:end+=suffix.end()
        result.append(Quantity(text[n.start:end],n.start,end,value,unit,None,n.qualifier,surface_unit=n.unit))
    from dataclasses import replace
    scoped=[]
    years=tuple(re.findall(r'\b(?:19|20)\d{2}\b',text))
    for n in result:
        # Positive grammar: a complete quantified subject ending at a finite
        # auxiliary. This is not a guess that the next word is an entity.
        m=re.match(r"\s+(?:of\s+(?:the\s+)?)?([a-z][a-z \'-]{0,70}?)\s+(?=may\b|must\b|could\b|would\b|will\b|are\b|were\b|need\b)",text[n.end:],re.I)
        if not m:
            m=re.match(r"\s+(?:of\s+(?:the\s+)?)?([a-z][a-z \'-]{0,70}?)(?=\s+(?:by|in)\s+\d{4}\b|[,.;]|$)",text[n.end:],re.I)
        population=m[1].strip().casefold() if m else ''
        if population.split()[:1] and population.split()[0] in {'may','might','must','could','would','will','need','needs','is','are','was','were','of','and','to','by','in','had','have','has'}:population=''
        scoped.append(replace(n,population=population,periods=years))
    result=sorted(scoped,key=lambda n:n.start)
    # Explicitly record contradictory dual notation; do not invent a tolerance.
    for a,b in zip(result,result[1:]):
        if a.unit==b.unit=='ratio' and re.fullmatch(r'\s*\(\s*',text[a.end:b.start]) and a.value!=b.value:
            problems.append('unsupported_approximate_dual_notation')
    return result,tuple(dict.fromkeys(problems))


# Bibliographic metadata, not a quantity claim: an author-year parenthetical
# such as "(Tan and Ng 2016)" / "(Smith et al., 2019; Lee 2020a)" or a numeric
# reference marker such as "[12]" / "[3-5]".
AUTHOR = r"[A-Z][A-Za-z'’\-]+(?:\s+(?:et\s+al\.?|and|&)(?:\s+[A-Z][A-Za-z'’\-]+)?)*"
CITATION = re.compile(r"\(\s*" + AUTHOR + r",?\s+(?:19|20)\d{2}[a-z]?(?:\s*;\s*" + AUTHOR
                      + r",?\s+(?:19|20)\d{2}[a-z]?)*\s*\)|\[\d+(?:\s*[,–-]\s*\d+)*\]")


def citation_metadata(text, quotes):
    """Citation strings copied verbatim from the evidence, never claim numbers.

    Only an exact source occurrence is masked. A changed author, year or marker
    is not in the source and therefore remains an ordinary unbound quantity.
    """
    return sorted({m.group() for m in CITATION.finditer(text) if any(m.group() in q for q in quotes)}, key=len, reverse=True)


def _mask(text, strings):
    for s in strings:
        text = text.replace(s, ' ' * len(s))
    return text


def verify_quantities(text,entries,target):
    cited=citation_metadata(text,[q for *_,q in entries])
    if cited:
        # Mask both sides at the same offsets so periods are compared consistently.
        text=_mask(text,cited);entries=[(d,e,r,_mask(q,cited)) for d,e,r,q in entries]
    ns,problems=quantities(text);errors=list(problems);audit=[]
    for n in ns:
        found=[]
        for d,e,r,q in entries:
            source,_=quantities(q)
            # A bounded explicit conditional cohort also defines a ratio. Both
            # components retain their ORIGINAL offsets/reader ledger entries.
            m=re.search(r"\bif\b[^,;]*?\b(\d+)\s+(?:people|workers|nurses|doctors)[^,;]*,\s*(\d+)\s+would\b",q,re.I)
            if m and int(m[1]):
                source.append(Quantity(m.group(),m.start(),m.end(),Fraction(int(m[2]),int(m[1])),'ratio',int(m[1]),periods=tuple(re.findall(r'\b(?:19|20)\d{2}\b',q))))
            for v in source:
                if (v.value,v.unit,v.approximation)!=(n.value,n.unit,n.approximation):continue
                if n.population and v.population and n.population!=v.population:continue
                if n.periods!=v.periods:continue
                # Ratios with an explicit denominator retain the base, even if
                # reducible; percent/fraction identities can use exact value.
                if n.denominator and v.denominator and n.denominator!=v.denominator:continue
                start=r.start+v.start;end=r.start+v.end
                digits=list(re.finditer(r'\d+',e.block.text[start:end]))
                if not all(any(t.start<=start+m.start() and start+m.end()<=t.end and rules._linked(t) and rules._cell_number(d,e,t) for t in e.number_tokens) for m in digits):continue
                found.append(dict(block_id=r.block_id,source=v.record(),start=start,end=end))
        audit.append(dict(claim=n.record(),matches=found))
        if not found:errors.append('quantity_unbound')
    return rules._check(target,'L1','unknown' if errors else 'pass',errors),audit
