"""Explicit question dates are necessary evidence constraints, never support proof.

No date inference from titles, current time, neighboring entities or year ranges.
A conservative rejection is preferable to answering a dated question with an
undated statistic. Undated questions retain the semantic verifier's behavior.
"""
import re

YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
MONTH_YEAR = re.compile(r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(?:[0-3]?\d(?:st|nd|rd|th)?[,\s]+)?((?:19|20)\d{2})\b", re.I)


def question_scope(question, evidence):
    quotes = tuple(evidence)
    current=str(question)
    reliable=getattr(question,'reliable_scope',False)
    question=getattr(question,'scope_text',question)
    years = sorted(set(YEAR.findall(question)))
    dates = sorted({(m[1].casefold(), m[2]) for m in MONTH_YEAR.finditer(question)})
    missing = [year for year in years if not any(year in YEAR.findall(q) for q in quotes)]
    missing += [month+' '+year for month, year in dates
                if not any(year in YEAR.findall(q) and re.search(r'\b'+month+r'\b', q, re.I) for q in quotes)]
    if reliable:
        missing += population_date_gaps(current,years,quotes)
    return dict(policy='explicit_question_dates_v1', years=years, dates=dates,
                missing=missing, passed=not missing, support_proof=False)


def population_date_gaps(question, years, quotes):
    """Conservative rate/period binding, never a new support permission.

    A rate and its period must occur in one source sentence. Unqualified rate
    requests require an explicit aggregate population there too; a subgroup's
    date cannot complete an undated global headline. Other statistical forms
    retain their existing native verifier contracts.
    """
    metric=re.search(r'\b([a-z]+ rate)\b',question,re.I)
    if not metric or not years:return []
    aggregate=re.compile(r"\b(?:global|worldwide|world(?:[’']s)?)\b",re.I)
    # An explicit population is a prepositional qualifier other than a year.
    scoped=bool(re.search(r'\b(?:in|among|for|of)\s+(?!the rate\b)(?:the\s+)?[a-z]',question,re.I))
    needs_aggregate=bool(aggregate.search(question)) or not scoped
    gaps=[]
    for year in years:
        dated=[sentence for quote in quotes for sentence in re.split(r'(?<=[.!?])\s+(?=[A-Z])',quote)
               if year in YEAR.findall(sentence) and metric.group(1).casefold() in sentence.casefold()]
        if not any(not needs_aggregate or aggregate.search(sentence) for sentence in dated):
            gaps.append('requested_population_period:'+year)
    return gaps
