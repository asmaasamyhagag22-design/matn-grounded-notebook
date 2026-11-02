"""App-only English actor normalization; baseline verification modules stay intact.

ADR-0033. No numeric, entity-surface, conditional, native threshold or source
permission is changed. Unknown language still receives every ordinary veto.
"""
import re
from types import FunctionType,SimpleNamespace
from typing import Literal
from matn_verification import rules,meaning,scope

FINITE=r'\b(?:is|are|was|were|has|have|had|can|could|may|might|should|must|would|will|does|do|did|implements?|supports?|develops?|uses?|takes?|returns?|samples?|generates?|reports?|uploads?|reviews?|defines?|improves?|reduces?|lowers?|increases?|operates?|achieves?|exhibits?|performs?|attains?|reaches?|shows?|displays?|serves?|supplies|supply|comes?|executes?)\b'


def subject_split(pattern,text,maxsplit=0,flags=0):
    if pattern.startswith(r'\b(?:is|are|was|were'):
        # A discourse connective is not the actor. Conditions remain in the
        # original sentence and are checked by the unchanged scope operators.
        text=re.sub(r'^\s*(?:(?:however|therefore|nevertheless|thus|in summary)[,\s]+)+','',text,flags=re.I)
        return re.split(FINITE,text,maxsplit=maxsplit,flags=re.I)
    return re.split(pattern,text,maxsplit=maxsplit,flags=flags)


def actor_words(text):
    result=set()
    for word in rules._words(text)-{'of','for','with','by'}:
        if len(word)>4 and word.endswith('ies'):word=word[:-3]+'y'
        elif len(word)>4:
            word=re.sub(r'(?:ing|ed|es|s)$','',word)
            if word.endswith('e'):word=word[:-1]
        result.add(word)
    return result


def clone(function,globals):
    value=FunctionType(function.__code__,globals,function.__name__,function.__defaults__,function.__closure__)
    value.__kwdefaults__=function.__kwdefaults__
    return value


_re=dict(vars(re));_re['split']=subject_split
_re=SimpleNamespace(**_re)
_actor_l3=clone(rules._l3,{**vars(rules),'re':_re,'_words':actor_words})
_rule_globals={**vars(rules),'_l3':_actor_l3}
_rule_verify=clone(rules.verify,_rule_globals)
_rules=SimpleNamespace(**{**vars(rules),'_l3':_actor_l3,'verify':_rule_verify})
_meaning_verify=clone(meaning.verify_meaning,{**vars(meaning),'rules':_rules})
_meaning=SimpleNamespace(**{**vars(meaning),'verify_meaning':_meaning_verify})
_obligations=clone(scope.scope_obligations,{**vars(scope),'re':_re})
_verify=clone(scope.verify_scope,{**vars(scope),'meaning':_meaning,'scope_obligations':_obligations})


class ProseReceipt(scope.ScopeReceipt):
    verifier_version:Literal['app-grounded-scope-v1']='app-grounded-scope-v1'
    normalizer_version:Literal['app-english-actor-binding-v1']='app-english-actor-binding-v1'


def verify_prose(documents,request,native):
    value=_verify(documents,request,native)
    return ProseReceipt(**value.model_dump(exclude={'verifier_version','normalizer_version'}))
