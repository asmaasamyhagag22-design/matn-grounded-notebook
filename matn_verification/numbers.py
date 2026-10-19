"""Bounded English numeric parser. Preserve offsets; never rewrite evidence."""
from dataclasses import dataclass, replace
from decimal import Decimal
import re

PERIOD = re.compile(r'\b(?:Q[1-4]-)?FY(?:19|20)\d{2}/\d{2}\b')
DIGIT = re.compile(r'(?<![\w.,])[+-]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)(?!\w|[.,]\d)')
ONES = dict(zip('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split(), range(20)))
TENS = dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(), range(20, 100, 10)))
WORDS = ONES | TENS | {'hundred': 100, 'thousand': 1000}
SPELLED = re.compile(r'\b(?:' + '|'.join(WORDS) + r')(?:[- ](?:' + '|'.join(WORDS) + r'))*\b', re.I)
UNITS = re.compile(r'^\s*(%|percentage\s+points?|percent\b|dollars?\b|euros?\b|pounds?\b|USD\b|EGP\b|GPUs?\b|minutes?\b|seconds?\b|hours?\b|years?\b|people\b|workers?\b|million\b|billion\b)', re.I)
QUALIFIER = re.compile(r'(over|under|above|below|about|approximately|at least|at most|more than|less than|[<>]=?)\s*$', re.I)


@dataclass(frozen=True)
class Number:
    value: Decimal
    start: int
    end: int
    unit: str
    qualifier: str


def _number(text, value, start, end):
    match = UNITS.match(text[end:])
    unit = match.group(1).lower() if match else ''
    if unit in ('%', 'percent'): unit = 'percent'
    elif unit.startswith('percentage'): unit = 'percentage_point'
    elif unit.endswith('s'): unit = unit[:-1]
    if unit=='percent' and match and re.match(r'\s+of\s+GDP\b',text[end+match.end():],re.I):
        unit='percent of gdp'
    prefix=text[:start]
    currency=re.search(r'([+-]?)(\$|€|£|USD|EUR|EGP)\s*$',prefix)
    if unit in ('million','billion') and match:
        suffix=re.match(r'\s+(dollars?|euros?|pounds?|USD|EUR|EGP)\b',text[end+match.end():],re.I)
        if suffix: unit += ' '+suffix.group(1).lower().rstrip('s')
    if currency:
        money={'$':'dollar','€':'euro','£':'pound','USD':'dollar','EUR':'euro','EGP':'egp'}[currency.group(2)]
        unit=(unit+' '+money).strip() if unit else money
        if currency.group(1)=='-': value=-value
        prefix=prefix[:currency.start()]
    qualifier = QUALIFIER.search(prefix)
    q = qualifier.group(1).lower() if qualifier else ''
    q = {'above':'over', 'more than':'over', '>':'over', 'below':'under', 'less than':'under', '<':'under', 'approximately':'about'}.get(q, q)
    return Number(value, start, end, unit, q)


def parse(text):
    periods = list(PERIOD.finditer(text))
    numbers = [_number(text, Decimal(m.group().replace(',', '')), m.start(), m.end()) for m in DIGIT.finditer(text)
               if not any(p.start() <= m.start() < p.end() for p in periods)]
    numbers += [Number(Decimal(0), p.start(), p.end(), 'period:'+p.group(), '') for p in periods]
    problems = []
    # Every digit run needs a recognized numeric span; glued units/IDs cannot disappear.
    if any(not any(n.start <= m.start() and m.end() <= n.end for n in numbers)
           for m in re.finditer(r'\d+', text)):
        problems.append('unsupported_numeric_form')
    if re.search(r'\d(?:[⁰¹²³⁴⁵⁶⁷⁸⁹]|[eE][+-]?\d|\^\d)', text) or re.search(r'\d+\.\d+\.\d+', text):
        problems.append('unsupported_numeric_form')
    for m in SPELLED.finditer(text):
        words = re.split('[- ]', m.group().lower())
        if len(words) == 2 and all(w in ONES and ONES[w] < 10 for w in words):
            problems.append('spelled_number_mismatch'); continue
        value = 0; current = 0; valid = True
        for i, w in enumerate(words):
            if w in ONES or w in TENS:
                if i and words[i-1] in ONES: valid = False
                current += WORDS[w]
            elif w == 'hundred' and 0 < current < 10: current *= 100
            elif w == 'thousand' and current: value += current * 1000; current = 0
            else: valid = False
        if valid:
            numbers.append(_number(text, Decimal(value + current), m.start(), m.end()))
        else: problems.append('unsupported_numeric_form')
    numbers=sorted(numbers,key=lambda n:n.start)
    for i in range(len(numbers)-1):
        a,b=numbers[i:i+2]
        if not a.unit and not b.unit and re.fullmatch(r'\s+out\s+of\s+',text[a.end:b.start],re.I):
            numbers[i]=replace(a,unit='ratio_numerator:'+format(b.value.normalize(),'f'))
            numbers[i+1]=replace(b,unit='ratio_denominator:'+format(a.value.normalize(),'f'))
    return numbers, tuple(dict.fromkeys(problems))
