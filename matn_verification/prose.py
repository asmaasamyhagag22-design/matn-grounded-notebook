"""Opt-in prose boundaries: quoted punctuation literals are not sentence ends.

Offsets and source bytes never change. The historical reader splitter is intact.
"""
import re
from matn_reading.structure.sentences import sentence_spans as original_spans
from .meaning import normalized


def sentence_spans(text):
    masked = list(text)
    # Only a quoted punctuation-only token. Quoted prose retains its boundaries.
    for m in re.finditer(r'''["“'][!?./:;=<>+*|&~^-]+["”']''', text):
        masked[m.start():m.end()] = 'x' * (m.end()-m.start())
    return original_spans(''.join(masked))


def surface(text):
    text = normalized(text).strip()
    # A separated list bullet is formatting, never an option like -a or --all.
    text = re.sub(r'^[•–—-]\s+(?=[A-Za-z])', '', text)
    if text.startswith('(') and text.endswith(')') and text.count('(') == text.count(')') == 1:
        text = text[1:-1].strip()
    # Introductory exception label adds no condition beyond the explicit if.
    text = re.sub(r'^There is one exception:\s*(?=if\b)', '', text, flags=re.I)
    return text[:1].lower() + text[1:]


def literals(text):
    """Exact quoted contents; apostrophes inside words are not quote delimiters."""
    pattern = r'"([^"\n]*)"|“([^”\n]*)”|`([^`\n]*)`|(?<!\w)\'([^\'\n]*)\'(?!\w)|‘([^’\n]*)’'
    return tuple(next(x for x in m.groups() if x is not None) for m in re.finditer(pattern, text))


def unresolved_opening(text):
    """A discourse connective cannot supply a missing source antecedent."""
    text = re.sub(r'^[•–—-]\s+(?=[A-Za-z])', '', text.strip())
    text = re.sub(r'^(?:(?:however|therefore|nevertheless|thus|instead|also|but|and|so)[,\s]+)+',
                  '', text.strip(), flags=re.I)
    from .meaning import UNRESOLVED
    return bool(UNRESOLVED.search(text))


def literal_in_source(value, quote):
    quoted = literals(quote)
    return value in quoted if quoted else value in quote
