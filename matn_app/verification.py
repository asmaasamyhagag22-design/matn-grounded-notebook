"""Avoid model work for a unit already vetoed by unchanged deterministic gates."""
from matn_verification.contracts import Check
from matn_verification.scope import verify_scope
from matn_chat.question_scope import question_scope


class DeferredNative:
    def check(self,text,evidence,target):
        return Check(target=target,layer='L4',verdict='not_run',reasons=())


def deterministic_first(documents,request,native,question=''):
    preview=verify_scope(documents,request,DeferredNative())
    if any(c.layer!='L4' and c.verdict!='pass' for c in preview.checks):
        return preview
    quotes=[r.get('quote','') for claim in request.get('claims',[]) for r in claim.get('citations',[])]
    if not question_scope(question,quotes)['passed']:
        return preview  # The engine attaches its unchanged question-scope veto.
    return verify_scope(documents,request,native)
