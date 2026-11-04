"""Bounded, source-scoped conversation context; previous answers never become evidence."""
import hashlib
import json
import re
from pathlib import Path
from .readiness import write, lock

VERSION='conversation-v1'
FOLLOWUP_START=re.compile(r'^(and\b|what about\b|how about\b|وماذا|ومَن|وما)',re.I)
ANAPHORA=re.compile(r'\b(those|these|they|them)\b|\bthat (group|revenue|figure|number|rate|result|estimate|trend|sector|country|period)\b|منهم|تلك|هؤلاء',re.I)


class Conversation:
    def __init__(self, folder, session, scope):
        if not session or len(session)>128:
            raise ValueError('SESSION_ID_REQUIRED_MAX_128')
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        self.path=folder/(hashlib.sha256(session.encode()).hexdigest()+'.json')
        self.scope=scope;self.session=session

    def __enter__(self):
        self.guard=lock(self.path.with_suffix('.lock'));self.guard.__enter__()
        try:
            self.value=json.loads(self.path.read_bytes()) if self.path.exists() else dict(version=VERSION,scope=self.scope,turns=[])
            if self.value['version']!=VERSION or self.value['scope']!=self.scope:
                raise ValueError('SESSION_SOURCE_SCOPE_MISMATCH_RESET_OR_NEW_SESSION')
            return self
        except BaseException:
            self.guard.__exit__(None,None,None);raise

    def __exit__(self,*args):
        self.guard.__exit__(*args)

    def reset(self):
        self.value['turns']=[];write(self.path,self.value)

    def resolve(self, question):
        # Compatibility formatter for saved callers; runtime uses plan(). An
        # explicit current period must never pick up a prior answer's dates.
        from .question_scope import YEAR
        if YEAR.search(question):return self.plan(question)['retrieval_query']
        turns=self.value['turns'][-2:]
        needs_context=bool(ANAPHORA.search(question) or re.match(r'^(?:what about|how about|وماذا)\s+[^?]{1,50}\??$', question.strip(), re.I))
        if not needs_context:
            return question
        if not turns:
            raise ValueError('FOLLOWUP_NEEDS_CONTEXT')
        context=[{'question':t['question'],'answer':t['answer']} for t in turns]
        return ('Conversation context for resolving references, entities and periods ONLY. '
                'This is not source evidence. Verify the new answer against retrieved source citations.\n'
                +json.dumps(context,ensure_ascii=False)+'\nCurrent question: '+question)

    def plan(self, question):
        """A bounded standalone retrieval query; history is orientation, never evidence.

        Explicit new dates override inherited dates. Only the last *resolved*
        question is inherited, so a chain cannot resurrect an abandoned topic.
        Answers are retained separately for UI/audit and never fed to retrieval.
        """
        from .question_scope import YEAR
        reference = bool(ANAPHORA.search(question))
        elliptical = bool(re.match(r'^(?:what about|how about|وماذا)\s+[^?]{1,50}\??$', question.strip(), re.I))
        current = re.sub(r'^and\s+', '', question.strip(), flags=re.I)
        query = current; inherited = ''; changes = []
        if (reference or elliptical) and not self.value['turns']:
            # Nothing earlier to resolve: "these experiments" in a first
            # question is read as written, never a failed turn.
            reference = elliptical = False
            changes.append('reference_without_earlier_turn_answered_as_written')
        if reference or elliptical:
            previous = self.value['turns'][-1]
            inherited = previous.get('retrieval_query', previous['question'])
            if YEAR.search(current):
                inherited = YEAR.sub('', inherited)
                changes.append('explicit_current_dates_replace_prior_dates')
            # Elliptical entity replacements lack a safe parser. Keep the topic
            # but do not inherit named actors; require an explicit question.
            if elliptical and not reference:
                raise ValueError('FOLLOWUP_AMBIGUOUS_USE_EXPLICIT_TOPIC_AND_ENTITY')
            query = current + ' Regarding: ' + inherited
            changes.append('reference_resolved_from_previous_question_only')
        elif not changes:
            changes.append('self_contained_current_question_no_history')
        from .reliable import subquestions
        plan = dict(version='standalone-query-v2', current_question=question,
            standalone_question=query, retrieval_query=query, scope_question=query, reference_question=inherited,
            answer_parts=subquestions(current),
            constraints=dict(years=sorted(set(YEAR.findall(query))), sources=self.scope.get('documents', [])),
            changes=changes, history_is_evidence=False, added_model_calls=0)
        self.last_plan = plan
        return plan

    def remember(self, question, effective, result):
        result['conversation']=dict(session=self.session,prior_turns=len(self.value['turns']),
                                    original_question=question,effective_question=effective,context_is_evidence=False,
                                    query_plan=getattr(self,'last_plan',None))
        # The user's question is orientation even when its answer failed, so a
        # follow-up can still resolve it. Only verified answer text is kept.
        answered=bool(result.get('sentences')) and result['state'] not in ('error','deferred_memory')
        self.value['turns']=(self.value['turns']+[dict(question=question[:2000],retrieval_query=getattr(self,'last_plan',{}).get('retrieval_query',question)[:2000],
            answer=' '.join(s['text'] for s in result['sentences'])[:4000] if answered else '',
            source_revision=result.get('source_revision'))])[-2:]
        write(self.path,self.value)
