"""Number-preserving, position-based lexical tokens (no model or dependencies).

Offsets are intentionally not exposed: NFKC can change length. Citation offsets
come exclusively from DocumentStructure, never from these normalized tokens.
Aliases share a base position, so they cannot increase document length.
"""
from dataclasses import dataclass
import re
import unicodedata

VERSION = 'rag-tokenizer-v1'
_NUMBER = r'(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)'
_CURRENCY = r'(?:[a-z]{1,3}\$|[$€£¥])'
_SIGN = r'[+\-−]?'
_UNIT_NUMBER = rf'{_SIGN}(?:{_CURRENCY})?{_NUMBER}%?'
_JOIN = r'[-‐‑‒–—]'
_WORD = rf'[^\W_]+(?:[/\-‐‑‒–—][^\W_]+)*'
_TOKEN = re.compile(rf'{_UNIT_NUMBER}{_JOIN}{_UNIT_NUMBER}|{_UNIT_NUMBER}(?![\w/]|{_JOIN}\w)|{_WORD}', re.UNICODE)
_NUMERIC = re.compile(rf'^{_UNIT_NUMBER}$')
_RANGE = re.compile(rf'^({_UNIT_NUMBER}){_JOIN}({_UNIT_NUMBER})$')
_PARTS = re.compile(_JOIN)
_CORE = re.compile(_NUMBER)

@dataclass(frozen=True)
class Token:
    base: str
    position: int
    aliases: tuple[str, ...]

    @property
    def terms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.base, *self.aliases)))


def _numeric_aliases(value: str) -> list[str]:
    core = _CORE.search(value).group()
    normalized = '0'+core if core.startswith('.') else core
    values = []
    if ',' in value:
        values.append(normalized.replace(',', ''))
    values.extend((normalized, normalized.replace(',', '')))
    return values


def tokenize(text: str) -> tuple[Token, ...]:
    normalized = unicodedata.normalize('NFKC', text).lower()
    result = []
    for match in _TOKEN.finditer(normalized):
        base = match.group()
        aliases = []
        span = _RANGE.fullmatch(base)
        if span:
            for end in span.groups():
                aliases.extend(_numeric_aliases(end))
        elif _NUMERIC.fullmatch(base):
            aliases.extend(_numeric_aliases(base))
        elif _PARTS.search(base):
            aliases.extend(_PARTS.split(base))
        aliases = tuple(x for x in dict.fromkeys(aliases) if x and x != base)
        result.append(Token(base, len(result), aliases))
    return tuple(result)
