"""Opt-in P1-V2 source-bound content units. No changes to the legacy verifier.

Bounded context discovery: preceding sentences of the SAME body block (at most
three / 1200 characters), plus adjacent explicit exceptions in that block. This
is a conservative source window, not a coreference resolver. Cross-block or
window-leading anaphora remain unresolved. Context is displayed verbatim and
separately cited; no synthesized quote or model-authored context is trusted.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import re

from matn_verification import rules
from matn_verification.contracts import Request, Evidence, Check, aggregate
from matn_verification.prose import sentence_spans, surface, unresolved_opening, literals, literal_in_source
from matn_verification.scope import conditions, canon
from .core import Workflow, digest

POLICY = 'source-content-units-v2.4'
ANAPHORA = re.compile(r'^(?:of (?:these|those)|these|those|they|their|it|this|such|however,?\s+\d+)\b', re.I)
RELATION = re.compile(r'\b(because|therefore|thus|hence|consequently|as a result|due to|compared with|more than|less than)\b|(?<!such )(?<!well )\bas\b(?!\s+(?:well|long)\b)', re.I)
EXCEPTION = re.compile(r'^\s*(?:unless|except|provided that|only if|this (?:rule|requirement))\b', re.I)


def recipient_promoted_to_actor(text, source):
    """Veto a bounded role reversal even when NLI accepts lexical overlap.

    Match a simple opening subject + predicate reused from an explicit source
    pronoun clause, where that subject occurs as its to/for recipient. This is
    only a negative guard, never a general subject resolver or support proof.
    """
    claim = re.match(r'^\s*((?:[Tt]he\s+)?[A-Za-z]+)\s+([a-z]+)\b', text)
    if not claim:
        return False
    subject, verb = claim.groups()
    return bool(re.search(
        r'\b(?:they|it|he|she|we)\s+' + re.escape(verb) +
        r'\b[^.;!?]*?\b(?:to|for)\s+' + re.escape(subject) + r'\b',
        source, re.I))


def exact_context_excerpts(context):
    """Separate displayed excerpts must each equal their ordered source quotes.

    A union of citations does not authorize a new connective between excerpts.
    Source eligibility/offset integrity and semantic checks remain mandatory.
    """
    return bool(context) and all(
        c.get('citations') and surface(c['quote']) == surface(
            ' '.join(ref['quote'].strip() for ref in c['citations']))
        for c in context)


def quantity_entities(text):
    # Sentence-opening English prepositions/discourse markers are not entities.
    # Local namespace only; all numeric offset/ledger/unit/cell checks unchanged.
    grammar={'of','if','given','by','in','on','for','from','among','hypothetical','global'}
    return tuple(n for n in rules.entities(text) if n.casefold() not in grammar)


def quantity_provenance(text, entries, target):
    return rules._l1(text, entries, target, entity_parser=quantity_entities)


def citation(d, e, s):
    return dict(doc_id=d.doc_id, block_id=e.block.block_id, start=s.start, end=s.end,
        quote=e.block.text[s.start:s.end], pdf_page_index=e.block.page_index,
        page_label=e.block.page_label, bbox=list(e.bbox.coordinates), bbox_precision=e.bbox.bbox_precision)


def discover(documents, handles, *, subject=False, context_display=False):
    """One support sentence, separate source context spans; never example IDs."""
    by = {e.block.block_id:(d,e) for d in documents for e in d.elements}
    result = {}
    for key, h in handles.items():
        refs = h['citations']
        if len(refs)!=1:
            result[key]=dict(state='unresolved', reason='continued_or_multi_span_support'); continue
        c=refs[0]; d,e=by[c['block_id']]; spans=sentence_spans(e.block.text)
        indices=[i for i,s in enumerate(spans) if s.start==c['start'] and s.end==c['end']]
        if len(indices)!=1 or rules.eligibility(d,e) or e.role=='table':
            result[key]=dict(state='unresolved',reason='not_one_eligible_body_sentence');continue
        i=indices[0]; previous=list(spans[:i]); following=[]
        if i+1<len(spans) and EXCEPTION.search(e.block.text[spans[i+1].start:spans[i+1].end]):following=[spans[i+1]]
        context=[citation(d,e,s) for s in previous+following]
        state='bounded'; reason='same_block_prefix_and_explicit_exception'
        if len(previous)>3 or sum(len(c['quote']) for c in context)>1200:
            state='unresolved'
        first=e.block.text[spans[0].start:spans[0].end].strip()
        if ANAPHORA.search(first) or unresolved_opening(first):state='unresolved'
        window=antecedent_window(e.block.text,spans,i) if state=='unresolved' else None
        if window is not None:
            # A late sentence keeps only the minimal dependent prefix. The window
            # is reading context; the support sentence alone remains the claim.
            context=[citation(d,e,s) for s in window+following]
            state='bounded'; reason='antecedent_window'
        result[key]=dict(state=state, reason=reason,
            support=citation(d,e,spans[i]), context=context,
            limits=dict(previous_sentences=3, context_characters=1200, cross_block=False))
        if reason=='antecedent_window':result[key].update(context_role='reading_context',window=WINDOW)
        if context_display:
            from .context_display import build_context
            local=build_context(d,result[key]['support'])
            result[key]['display_context']=local
            result[key].update(state='bounded' if local['anaphora']['resolved'] else 'unresolved',
                               reason='local_context_display' if local['anaphora']['resolved'] else 'context_unresolved:anaphora')
        elif subject and result[key]['state']=='bounded':
            bind_subject(result[key],d,e,spans[i],SUBJECT_POLICY if subject is True else subject)
    return result


SUBJECT_POLICY = 'subject-binding-v2'
SUBJECT_POLICIES = ('subject-binding-v1', 'subject-binding-v2')
# Grammar only: third-person verbs, participles and predicative adjectives that
# open a fragment whose subject is elsewhere ("Supports X", "Compliant with Y").
SUBJECTLESS = frozenset('''supports provides offers allows enables includes integrates meets helps lets
delivers ensures gives tracks automates comes works makes creates reduces improves simplifies
streamlines empowers combines uses features contains connects protects stores manages handles generates
monitors measures sends syncs scales runs requires costs starts lacks takes adapts adds assigns
designed built used trusted known compliant available ideal suitable compatible accessible certified
approved powered backed based priced rated ranked recognized considered regarded'''.split())
# A following word that makes the opener a plural noun subject ("Features include").
NOUN_FOLLOWER = frozenset('''are is were was include includes can may will should must could would of for to
have has and or that which in on'''.split())
GENERIC_REFERENCE = re.compile(r'^(?:the|this|that|these|those|our|its|their|your)\s+(?:[\w-]+\s+){0,2}?'
    r'(?:platform|tool|solution|software|product|app|application|suite|module|offering|vendor|provider)s?\b', re.I)
DEFINITE_ACRONYM = re.compile(r'^[Tt]he\s+[A-Z]{2,6}s?\s+(?=[a-z])')
FIRST_PERSON = re.compile(r'^(?:we|our|us)\b', re.I)
NAME_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9&'’-]*[A-Za-z0-9]")


def subject_need(sentence):
    """Why a sentence cannot name its own subject; None when it can.

    Bounded surface grammar, not a parser: a verb/adjective-led fragment, a
    definite artifact reference ("The tool", "Our solution") or first person.
    Pronoun openings keep the existing ANAPHORA/antecedent handling.
    """
    s=re.sub(r'^[•–—*-]\s*','',sentence.strip())
    if s.endswith('?'):return None
    words=re.findall(r"[A-Za-z][A-Za-z'-]*",s)
    if words and words[0].lower() in SUBJECTLESS and words[0][0].isupper() and (len(words)<2 or words[1].lower() not in NOUN_FOLLOWER):
        return 'subjectless'
    if GENERIC_REFERENCE.search(s) or DEFINITE_ACRONYM.search(s):
        return 'generic_reference'
    if FIRST_PERSON.search(s):
        return 'first_person'
    return None


def document_names(document, text):
    """Name-like tokens in text, judged against the whole document.

    A name has internal capitals/digits or a mark (CourseMill, LMS365, X®), or is
    a capitalized word that the document never writes in lower case and repeats.
    Every name must also occur in non-heading text (labels like "Price:" do not).
    Acronyms alone and title-case common words are not names.
    """
    body=' '.join(e.block.text for e in document.elements)
    prose=' '.join(e.block.text for e in document.elements if str(getattr(e.block.block_type,'value',e.block.block_type))!='heading')
    lower={w for w in NAME_TOKEN.findall(body) if w.islower()}
    names=[]
    for m in NAME_TOKEN.finditer(text):
        w=m.group(0); after=text[m.end():m.end()+1]
        if w.isupper() or not w[0].isupper() and not re.search(r'[A-Z]',w[1:]):
            continue
        marked=after in '®™' and after!=''
        internal=bool(re.search(r'[a-z][A-Z]|[A-Za-z]\d|\d[A-Za-z]',w))
        proper=(w[1:].islower() and len(w)>=3 and w.lower() not in lower
                and len(re.findall(r'(?<![A-Za-z])'+re.escape(w)+r'(?![A-Za-z])',body))>=2)
        if (marked or internal or proper) and re.search(r'(?<![A-Za-z])'+re.escape(w)+r'(?![A-Za-z])',prose):names.append(w)
    return list(dict.fromkeys(names))


def heading_level(element):
    for flag in element.flags:
        if flag.startswith('html_heading_level:'):return int(flag.split(':')[1])
    return None


def governing_heading(document, element):
    """Nearest heading chain above an element: each step must outrank the last.

    Without explicit levels, only the nearest heading may govern.
    """
    elements=list(document.elements); index=next(i for i,x in enumerate(elements) if x.block.block_id==element.block.block_id)
    limit=None
    for e in reversed(elements[:index]):
        if str(getattr(e.block.block_type,'value',e.block.block_type))!='heading' or not e.block.text.strip():continue
        level=heading_level(e)
        if limit is not None and (level is None or level>=limit):continue
        if rules.eligibility(document,e):return None,[]
        names=document_names(document,e.block.text)
        if names:return e,names
        # Climb only through minor labels ("Price:", "Key strengths"); a
        # nameless major section (h1/h2) owns its own general content.
        if level is None or level<=2:return None,[]
        limit=level
    return None,[]


class _Span:
    def __init__(self,start,end):self.start=start;self.end=end


# v2: a demonstrative reference inside the sentence ("…this study highlighted…").
RESEARCH_NOUNS = r'study|studies|report|survey|paper|research|analysis|article|review|dissertation|thesis'
DEMONSTRATIVE = re.compile(r'(?<!^)\b(?:this|these)\s+(' + RESEARCH_NOUNS +
    r'|platform|tool|solution|product|project|program|programme|initiative|framework|guide)\b', re.I)
# v2: a block-initial verb + object pronoun whose antecedent is outside the block ("Replace it with …").
# The pronoun must be an object: followed by a preposition/particle or punctuation, never a noun,
# and the opener must not be a subordinator, preposition or question word.
OBJECT_PRONOUN = re.compile(r'^(?!(?:Within|While|If|Throughout|In|Whether|During|After|Before|As|Since|For|With|At|On|By|From|To|'
    r'Is|Are|Does|Do|Did|Can|Will|Should|Would|Could|Unlike|Like|Under|Over|Despite|Given|Once|Until|Unless|When|Where|Why|How|What)\b)'
    r'[A-Z][a-z]+\s+(?:it|them|this|these|those)(?:\s+(?:with|into|to|for|as|from|on|in|by|and|or|up|out|down|away|off|over|back|at|across|through)\b|\s*[.,;!]|$)')


def document_title(document):
    """The first eligible h1 heading, or None."""
    for e in document.elements:
        if str(getattr(e.block.block_type,'value',e.block.block_type))=='heading' and heading_level(e)==1 and e.block.text.strip():
            return None if rules.eligibility(document,e) else e
    return None


def bind_subject_v2(unit, document, element, span, sentence):
    """Extra v2 needs; returns True when it decided the unit (bound or blocked)."""
    s=sentence.strip()
    prefix=[c for c in unit['context'] if c['block_id']==element.block.block_id and c['start']<span.start]
    if OBJECT_PRONOUN.search(s) and not ANAPHORA.search(s) and not prefix:
        unit.update(state='unresolved',reason='subject_unresolved:object_pronoun',
                    subject=dict(policy='subject-binding-v2',need='object_pronoun',resolved_by=None,names=[]))
        return True
    m=DEMONSTRATIVE.search(s)
    if not m:
        return False
    names=document_names(document,' '.join(c['quote'] for c in unit['context']))
    if names:
        unit['subject']=dict(policy='subject-binding-v2',need='demonstrative_reference',resolved_by='reading_context',names=names)
        return True
    if re.fullmatch(RESEARCH_NOUNS,m.group(1),re.I):
        title=document_title(document)
        if title is not None:
            text=title.block.text; end=len(text.rstrip().rstrip(':').rstrip())
            ref=citation(document,title,_Span(0,end))
            unit['context']=[ref]+unit['context']
            unit['subject']=dict(policy='subject-binding-v2',need='demonstrative_reference',resolved_by='document_title',
                                 names=[ref['quote']],block_id=title.block.block_id)
            unit['limits']=dict(unit['limits'],subject_heading=True)
            return True
    else:
        heading,names=governing_heading(document,element)
        if heading is not None:
            text=heading.block.text
            start=re.match(r'\s*(?:\d+[.)]\s*)?',text).end(); end=len(text.rstrip().rstrip(':').rstrip())
            unit['context']=[citation(document,heading,_Span(start,end))]+unit['context']
            unit['subject']=dict(policy='subject-binding-v2',need='demonstrative_reference',resolved_by='heading',names=names,block_id=heading.block.block_id)
            unit['limits']=dict(unit['limits'],subject_heading=True)
            return True
    unit.update(state='unresolved',reason='subject_unresolved:demonstrative_reference',
                subject=dict(policy='subject-binding-v2',need='demonstrative_reference',resolved_by=None,names=[]))
    return True


def bind_subject(unit, document, element, span, policy='subject-binding-v1'):
    """Make the displayed unit name what it is about, or block it.

    Uses the existing reading context (same-block prefix) first, then the
    governing heading as an exact, separately cited excerpt. No model, no
    product or topic lists; an unnamed subject leaves the unit unresolved.
    """
    if policy not in SUBJECT_POLICIES:raise ValueError('SUBJECT_POLICY')
    sentence=element.block.text[span.start:span.end]
    need=subject_need(sentence)
    if need is None:
        if policy=='subject-binding-v2':bind_subject_v2(unit,document,element,span,sentence)
        return
    # "The Open edX platform": a name inside the reference itself suffices.
    own=GENERIC_REFERENCE.search(re.sub(r'^[•–—*-]\s*','',sentence.strip()))
    if need=='generic_reference' and own and document_names(document,own.group(0)):return
    names=document_names(document,' '.join(c['quote'] for c in unit['context']))
    if names:
        unit['subject']=dict(policy=policy,need=need,resolved_by='reading_context',names=names);return
    heading,names=(None,[]) if ANAPHORA.search(sentence.strip()) else governing_heading(document,element)
    if heading is None:
        unit.update(state='unresolved',reason='subject_unresolved:'+need,
                    subject=dict(policy=policy,need=need,resolved_by=None,names=[]))
        return
    text=heading.block.text
    start=re.match(r'\s*(?:\d+[.)]\s*)?',text).end(); end=len(text.rstrip().rstrip(':').rstrip())
    unit['context']=[citation(document,heading,_Span(start,end))]+unit['context']
    unit['subject']=dict(policy=policy,need=need,resolved_by='heading',names=names,block_id=heading.block.block_id)
    unit['limits']=dict(unit['limits'],subject_heading=True)


def subject_bound(pack):
    """The saved pack's subject policy (exact version), or False."""
    if pack.get('subject_policy') not in (None, *SUBJECT_POLICIES):raise ValueError('SUBJECT_POLICY')
    return pack.get('subject_policy') or False


def context_bound(pack):
    from .context_display import POLICY as context_policy
    if pack.get('context_policy') not in (None, context_policy):raise ValueError('CONTEXT_POLICY')
    return bool(pack.get('context_policy'))


def subject_shown(unit, visible):
    """A bound subject must be visible in the final display."""
    subject=unit.get('subject')
    return not subject or any(re.search(r'(?<![A-Za-z])'+re.escape(n)+r'(?![A-Za-z])',visible) for n in subject['names'])


WINDOW = 'antecedent-window-v1'
CONNECTIVE = re.compile(r'^(?:in (?:this|that|these|those|such|each|both) (?:case|cases|study|studies|condition|conditions|period|area|areas|setting|way)|as a result|similarly|likewise|in contrast|by contrast|in addition|moreover|furthermore|additionally|for (?:example|instance)|otherwise|then|here|there(?:fore)?|accordingly|consequently|still|yet|meanwhile|finally)\b', re.I)


def dependent_opening(sentence):
    """A sentence that cannot be read without the text before it."""
    s=sentence.strip()
    return bool(ANAPHORA.search(s) or unresolved_opening(s) or CONNECTIVE.search(s) or subject_need(s))


def antecedent_window(text, spans, i):
    """Smallest same-block prefix that makes a late sentence readable.

    Walk back only over connective-led sentences (or a colon introduction) to
    the nearest independent sentence, within the same caps as the bounded
    prefix. A pronoun/determiner antecedent ("they", "those teams") may span
    an unknown extent, so any such opening keeps the sentence unresolved.
    """
    j=i
    while True:
        sentence=text[spans[j].start:spans[j].end].strip()
        if ANAPHORA.search(sentence) or unresolved_opening(sentence):return None
        if j==0 or not (CONNECTIVE.search(sentence) or text[spans[j-1].start:spans[j-1].end].rstrip().endswith(':')):break
        j-=1
        if i-j>3 or sum(len(text[s.start:s.end]) for s in spans[j:i])>1200:return None
    return list(spans[j:i])


def unit_slots(task):
    """Output slots follow the requirements: one per required point, two minimum."""
    return {f['id']: max(2, sum(p['facet'] == f['id'] for p in task.get('required_points', [])))
            for f in task['facets']}


def upgrade_pack(documents, pack, *, selected_display=False, subject_binding=False, context_display=False):
    # Reuse strict P1 binding validation; derive every unit from snapshots.
    Workflow(documents,pack,None)
    value=deepcopy(pack); value.pop('context_dependencies',None)
    value.update(configuration=POLICY, content_units=discover(documents,pack['handles'],subject=subject_binding,context_display=context_display))
    if context_display:
        from .context_display import POLICY as context_policy
        value['context_policy']=context_policy
        value.pop('subject_policy',None)
    elif subject_binding:value['subject_policy']=SUBJECT_POLICY if subject_binding is True else subject_binding
    if selected_display:value["display_policy"]="selected-context-v1"
    return value


def identity():
    from .core import verifier_identity
    return dict(**verifier_identity(), content_policy=POLICY,
        content_code=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


def primary_proposition(text):
    # Introductory prose before an explicit colon does not share the modal scope
    # of a following conditional proposition. Keep the condition itself intact.
    return text.split(':',1)[1].strip() if ':' in text and re.match(r'\s*(?:if|unless)\b',text.split(':',1)[1],re.I) else text


def guard(text, source, context):
    """Bounded deterministic vetoes in addition to unchanged L0/L1/native L4.

    Not a paraphrase proof. Unknown predicate equivalence still needs native L4;
    explicit operators, literals and quantity provenance cannot be rescued by it.
    """
    reasons=[]; main=primary_proposition(source)
    if len(sentence_spans(text))!=1:reasons.append('unit_not_atomic')
    if conditions(text)!=conditions(main):reasons.append('condition_changed')
    # Compare only the selected support proposition, not the block or neighbors.
    force=lambda q: set(re.findall(r'\b(?:must|should|may|might|could|would|will|cannot|never|not|unlikely)\b',q.lower()))
    if force(text)!=force(main):reasons.append('force_changed')
    a=rules._words(text); b=rules._words(main)
    if (a & rules._UP and not a & rules._DOWN and b & rules._DOWN and not b & rules._UP) or (a & rules._DOWN and not a & rules._UP and b & rules._UP and not b & rules._DOWN):reasons.append('direction_changed')
    if RELATION.search(text) and surface(text)!=surface(source):reasons.append('added_relation_unresolved')
    if unresolved_opening(text) and not context:reasons.append('unresolved_claim')
    if any(not literal_in_source(v,source) for v in literals(text)):reasons.append('literal_changed')
    # Named population/geography cannot be authorized by a neighboring source.
    extra=[n for n in rules.entities(text) if not rules._contains(source,n)
           and not any(rules._contains(c['quote'],n) for c in context)]
    if extra:reasons.append('new_entity')
    return reasons


def style_version(parent, operations):
    """Pure saved-version view: no workflow, source loading or verifier."""
    if digest({k:v for k,v in parent.items() if k!='version'})!=parent['version']:
        raise ValueError('PARENT_VERSION_INTEGRITY')
    result=deepcopy(parent)
    for op in operations:
        if op['op']!='style':raise ValueError('STYLE_OPERATION')
        if op['key'] not in ('accent','density'):raise ValueError('STYLE_KEY')
        result['style'][op['key']]=op['value']
    result['parent_version']=parent['version']
    result['reused_receipts']=sorted({c['binding'] for s in parent['slides'] for c in s['checks']})
    result['invalidated_receipts']=[]
    if 'composition_policy' in parent:
        result['reused_composition_receipts']=sorted({s['composition']['binding'] for s in parent['slides'] if s.get('composition',{}).get('binding')})
        result['invalidated_composition_receipts']=[]
    result.pop('version');result['version']=digest(result)
    return result


class UnitWorkflow:
    def __init__(self,documents,pack,entailment,*,verifier=None):
        self.documents=tuple(documents); self.pack=deepcopy(pack);self.entailment=entailment
        Workflow(documents,pack,None)
        if pack.get('configuration')!=POLICY or discover(documents,pack['handles'],subject=subject_bound(pack),context_display=context_bound(pack))!=pack.get('content_units'):
            raise ValueError('UNIT_CONTEXT_BINDING')
        self.identity=verifier or identity();self.cache={}
        if context_bound(pack):
            from . import context_display
            self.identity=dict(self.identity,context_display=dict(policy=context_display.POLICY,
                sha256=hashlib.sha256(Path(context_display.__file__).read_bytes()).hexdigest()))
        self.fps={d.doc_id:rules.fingerprint(d) for d in documents}
        from matn_verification.aliases import definitions
        self.alias_definitions=definitions(self.documents)
        if 'content_plan' in self.pack:
            from .planning import validate, code_identity
            validate(self.pack)
            self.identity = dict(self.identity, content_plan=code_identity())

    def check(self, atom, *, title=None, prior=None, select_context=True):
        unit=self.pack['content_units'].get(atom['support']); reasons=[];checks=[]
        if not unit or unit['state']!='bounded':
            reason=unit.get('reason') if unit and unit.get('reason')=='context_unresolved:anaphora' else 'unresolved_source_context'
            return dict(atom=deepcopy(atom),status='abstained',reasons=[reason],binding=digest(dict(atom=atom,pack=self.pack,identity=self.identity,title=title)),reused=False)
        if self.pack.get('display_policy')=='selected-context-v1':
            return self.check_selected(atom,unit,title=title,prior=prior,select_context=select_context)
        support=unit['support']; context=unit['context']; text=atom['text']
        # Code, not a formatter/model, determines the exact visible context.
        display=dict(context=deepcopy(context),text=text,support=deepcopy(support))
        if context_bound(self.pack):
            display['local_context'], local_reasons=self.local_display(unit,text)
            reasons.extend(local_reasons)
        binding=digest(dict(atom=atom,display=display,title=title,task=self.pack['task'],sources=self.pack['sources'],identity=self.identity))
        if prior and binding in prior:return dict(deepcopy(prior[binding]),reused=True)
        refs=[{k:c[k] for k in ('block_id','start','end','quote')} for c in context+[support]]
        req=Request.model_validate_json(__import__('json').dumps(dict(sentence=text,
            claims=[dict(text=text,citations=refs)],selected_doc_ids=sorted(self.fps),fingerprints=self.fps,
            retrieved_spans=refs)))
        l0,entries=rules._resolve(self.documents,req,req.claims[0].citations,'unit',self.fps);checks.append(l0)
        reasons.extend(guard(text,support['quote'],context))
        if not subject_shown(unit,' '.join(c['quote'] for c in context)+' '+text):reasons.append('subject_not_displayed')
        # L1 sees the generated claim alone: exact context does not conceal a
        # wrong unit/year/denominator in the claim. Original ledgers/cells retained.
        if l0.verdict=='pass':
            checks.append(quantity_provenance(text,entries,'unit'))
            # Bound the explicit noun immediately following each quantity.
            # Generic person counters are allowed only when the source says
            # people/person(s)/individual(s). They cannot authorize an occupation,
            # cohort or country. L1 still owns units/periods/ledgers/cells.
            allowed=rules._words(' '.join(c['quote'] for c in context+[support]))
            generic={'people','person','persons','individual','individuals'}
            if allowed & generic:allowed |= generic
            operators={'may','might','could','would','will','must','should','is','are','was','were','had','have','has','need','needs','of','out','and','or','by','in','to','per','for'}
            for n in rules.parse(text)[0]:
                after=re.match(r'\s+([A-Za-z]+)',text[n.end:])
                if after and after.group(1).lower() not in allowed|operators:
                    reasons.append('quantity_population_unresolved')
            # Context itself is exact eligible source content; verify its source
            # integrity via L0 above, and interpretation with the final user text.
            if not reasons and all(c.verdict=='pass' for c in checks):
                evidence=tuple(Evidence.model_validate_json(__import__('json').dumps(c)) for c in context+[support])
                visible=' '.join(c['quote'].strip() for c in context)+' '+text if context else text
                primary=(Evidence.model_validate_json(__import__('json').dumps(support)),)
                checks.append(self.native(text,primary,'claim'))
                checks.append(self.native(visible,evidence,'visible-unit'))
        status='abstained' if reasons else aggregate(checks)
        # L0/L1 alone can never constitute support.
        if not any(c.layer=='L4' for c in checks) and status=='verified':status='abstained'
        return dict(binding=binding,atom=deepcopy(atom),display=display,status=status,reasons=reasons,
            checks=[c.model_dump(mode='json') for c in checks],reused=False,
            relations=([dict(text=text,support=deepcopy(support),state='supported' if status=='verified' else 'unresolved')] if RELATION.search(text) else []),
            source_copy=surface(text)==surface(support['quote']))

    def check_selected(self,atom,unit,*,title=None,prior=None,select_context=True):
        from matn_verification.quantity_units import verify_quantities, quantities
        from matn_verification.operators import obligations
        import json
        support=unit['support'];reading=unit['context'];text=atom['text']
        selected=atom.get('context',{})
        ctxtext=selected.get('text','').strip()
        indices=selected.get('sources',[])
        if any(type(i) is not int or not 0<=i<len(reading) for i in indices):
            raise ValueError('DISPLAY_CONTEXT_SOURCE')
        ctxrefs=[reading[i] for i in indices]
        selection=None
        # Select, never synthesize: retain one COMPLETE generated context
        # sentence covering the source cohort/period/condition. Native checks
        # below still decide support and the final visible interpretation.
        if select_context and ctxtext and reading and '_built_context' not in atom and ANAPHORA.search(support['quote']) and quantities(support['quote'])[0]:
            from matn_verification.operators import structure
            cohort=primary_proposition(reading[0]['quote']);condition=structure(cohort).condition
            wanted=quantities(condition[1] if condition else cohort)[0]
            years=re.findall(r'\b(?:19|20)\d{2}\b',cohort)
            candidates=[]
            for span in sentence_spans(ctxtext):
                sentence=ctxtext[span.start:span.end].strip();nums=quantities(sentence)[0]
                if all(any(n.value==v.value and n.unit==v.unit for v in nums) for n in wanted) and all(y in sentence for y in years) and (not condition or re.search(r'\b(?:if|hypothetical)\b',sentence,re.I)):
                    if 'content_plan' in self.pack:
                        from .planning import for_atom, check
                        candidate = dict(atom, context=dict(text=sentence, sources=[0]))
                        if check(for_atom(self.pack, atom), candidate):
                            continue
                    candidates.append(sentence)
            if candidates:
                chosen=min(candidates,key=len)
                if chosen!=ctxtext:
                    selection=dict(original_text=ctxtext,selected_text=chosen,reason='complete sentence retaining explicit cohort, period and conditional scope; not a support verdict')
                    ctxtext=chosen;ctxrefs=[reading[0]]
        context=[dict(quote=ctxtext, citations=deepcopy(ctxrefs))] if ctxtext else []
        trimmed=[]
        if '_built_context' in atom:
            context=deepcopy(atom['_built_context'])
            # Code-built reading context must not display numbers that cannot be
            # linked to the source ledger. Omit such excerpts instead of linking
            # them, unless the support sentence depends on the text before it.
            if not dependent_opening(primary_proposition(support['quote'])):
                trimmed=[c for c in context if self.unlinked_quantities(c)]
                context=[c for c in context if c not in trimmed]
            ctxtext=' '.join(c['quote'] for c in context)
            ctxrefs=[ref for c in context for ref in c['citations']]
        elif 'content_plan' in self.pack:
            for c in context:c['origin']='model-proposed context'
        display=dict(text=text,support=deepcopy(support),context=context)
        local_reasons=[]
        if context_bound(self.pack):
            display['local_context'],local_reasons=self.local_display(unit,text)
        from matn_verification.aliases import resolve_scoped
        claim_entities, claim_definitions = resolve_scoped(
            text, [support], self.alias_definitions, entity_parser=quantity_entities)
        context_entities, context_definitions = resolve_scoped(
            ctxtext, ctxrefs, self.alias_definitions, entity_parser=quantity_entities)
        claim_definitions = [{k:v for k,v in d.items() if k not in ('long','short')}
                             for d in claim_definitions]
        context_definitions = [{k:v for k,v in d.items() if k not in ('long','short')}
                               for d in context_definitions]
        display['alias_definitions'] = deepcopy(claim_definitions)
        display['context_alias_definitions'] = deepcopy(context_definitions)
        planned = {}
        plan_reasons = []
        if 'content_plan' in self.pack:
            from .planning import for_atom, check_display
            item = for_atom(self.pack, atom)
            planned = dict(content_plan_item=item)
            plan_reasons = check_display(item, display, unit)
        binding=digest(dict(atom=atom,display=display,reading=reading,title=title,task=self.pack['task'],sources=self.pack['sources'],identity=self.identity,**planned))
        if prior and binding in prior:return dict(deepcopy(prior[binding]),reused=True)
        refs=ctxrefs+[support]
        req=Request.model_validate_json(json.dumps(dict(sentence=text,claims=[dict(text=text,citations=[{k:c[k] for k in ('block_id','start','end','quote')} for c in refs])],selected_doc_ids=sorted(self.fps),fingerprints=self.fps)))
        l0,entries=rules._resolve(self.documents,req,req.claims[0].citations,'unit',self.fps)
        checks=[l0];reasons=list(plan_reasons)+local_reasons;audit=[]
        main=primary_proposition(support['quote'])
        errors,pairs=obligations(text,main);reasons.extend(errors)
        if recipient_promoted_to_actor(text, main):reasons.append('recipient_promoted_to_actor')
        if len(sentence_spans(text))!=1:reasons.append('unit_not_atomic')
        if RELATION.search(text) and surface(text)!=surface(main):reasons.append('added_relation_unresolved')
        if any(not literal_in_source(v,support['quote']) for v in literals(text)):reasons.append('literal_changed')
        if claim_entities or context_entities:reasons.append('new_entity')
        if ctxtext and not ctxrefs:reasons.append('missing_display_context_source')
        if ctxtext and RELATION.search(ctxtext) and not exact_context_excerpts(context):reasons.append('context_relation_unresolved')
        a=rules._words(text);b=rules._words(main)
        if (a & rules._UP and not a & rules._DOWN and b & rules._DOWN and not b & rules._UP) or (a & rules._DOWN and not a & rules._UP and b & rules._UP and not b & rules._DOWN):reasons.append('direction_changed')
        visible=(ctxtext+' '+text).strip()
        if not subject_shown(unit,visible):reasons.append('subject_not_displayed')
        # Anaphoric quantities need an explicit visible cohort, denominator and
        # period. Only the actual source condition/cohort supplies obligations.
        if ANAPHORA.search(main) and quantities(main)[0]:
            if not reading:reasons.append('missing_display_scope')
            else:
                cohort=primary_proposition(reading[0]['quote'])
                from matn_verification.operators import structure
                condition=structure(cohort).condition
                required=(condition[1] if condition else cohort)
                required_nums=quantities(required)[0]
                years=re.findall(r'\b(?:19|20)\d{2}\b',cohort)
                shown=quantities(visible)[0]
                if any(not any(n.value==v.value and n.unit==v.unit for v in shown) for n in required_nums) or any(y not in visible for y in years):reasons.append('missing_display_scope')
                if condition and not re.search(r'\b(?:if|hypothetical)\b',visible,re.I):reasons.append('missing_display_condition')
                # Cohort nouns are bound semantically by an explicit native
                # context check; a new noun cannot be authorized by a number.
                if not ctxtext:reasons.append('missing_display_context')
        if l0.verdict=='pass':
            primary_entries=[x for x in entries if x[2].block_id==support['block_id']
                             and x[2].start==support['start'] and x[2].end==support['end']]
            numeric,audit=verify_quantities(text,primary_entries,'unit');checks.append(numeric)
            if ctxtext:
                selected_entries=[x for x in entries if any(x[2].block_id==c['block_id'] and x[2].start==c['start'] and x[2].end==c['end'] for c in ctxrefs)]
                cnum,caudit=verify_quantities(ctxtext,selected_entries,'context');checks.append(cnum);audit+=caudit
            if not reasons and all(c.verdict=='pass' for c in checks):
                primary=tuple(Evidence.model_validate_json(json.dumps(c)) for c in [support]+claim_definitions)
                # Claim must be supported independently of the context selection.
                checks.append(self.native(text,primary,'claim'))
                if ctxtext:
                    ev=tuple(Evidence.model_validate_json(json.dumps(c)) for c in ctxrefs+context_definitions)
                    checks.append(self.native(ctxtext,ev,'display-context'))
                # Changed condition operands need reciprocal checks. They are
                # source-derived, not model metadata, and cannot replace L0/L1.
                for left,right,role in pairs:
                    # A semantic assay has synthetic identity and exact probe
                    # offsets. It is NEVER a source citation or evidence union.
                    ev=primary[0].model_copy(update={'quote':right,'doc_id':'semantic-assay-not-a-source','block_id':'semantic-assay','start':0,'end':len(right)})
                    checks.append(self.native(left,(ev,),role))
                    reverse=ev.model_copy(update={'quote':left,'end':len(left)})
                    checks.append(self.native(right,(reverse,),role+'-reverse'))
                evidence=tuple(Evidence.model_validate_json(json.dumps(c)) for c in (reading if ANAPHORA.search(main) and quantities(main)[0] else ctxrefs)+[support]+claim_definitions+context_definitions)
                checks.append(self.native(visible,evidence,'visible-unit'))
        status='abstained' if reasons else aggregate(checks)
        if not any(c.layer=='L4' for c in checks) and status=='verified':status='abstained'
        receipt=dict(binding=binding,display_sha256=digest(display),atom=deepcopy(atom),display=display,reading_context=deepcopy(reading),context_selection=selection,status=status,reasons=reasons,checks=[c.model_dump(mode='json') for c in checks],quantity_audit=audit,reused=False,source_copy=surface(text)==surface(support['quote']))
        if trimmed:receipt['context_trimmed']=[dict(quote=c['quote'],reason='unlinked_numbers_outside_claim') for c in trimmed]
        return receipt

    def local_display(self,unit,text):
        """Source-checked display metadata never enters claim/native evidence."""
        from .context_display import validate_context, anaphora_audit
        document=next(d for d in self.documents if d.doc_id==unit['support']['doc_id'])
        context=deepcopy(validate_context(document,unit['support'],unit['display_context']))
        audit=anaphora_audit(text,context)
        context['displayed_claim_anaphora']=audit
        return context, [] if audit['resolved'] else ['context_unresolved:anaphora']

    def unlinked_quantities(self,excerpt):
        """True when an exact context excerpt shows a number L1 cannot link."""
        from matn_verification.quantity_units import verify_quantities, quantities
        import json
        if not quantities(excerpt['quote'])[0]:return False
        refs=[{k:c[k] for k in ('block_id','start','end','quote')} for c in excerpt['citations']]
        req=Request.model_validate_json(json.dumps(dict(sentence=excerpt['quote'],claims=[dict(text=excerpt['quote'],citations=refs)],selected_doc_ids=sorted(self.fps),fingerprints=self.fps)))
        l0,entries=rules._resolve(self.documents,req,req.claims[0].citations,'unit',self.fps)
        return l0.verdict=='pass' and verify_quantities(excerpt['quote'],entries,'context')[0].verdict!='pass'

    def native(self,text,evidence,target):
        key=digest(dict(text=text,evidence=[e.model_dump(mode='json') for e in evidence],identity=self.identity))
        if key not in self.cache:self.cache[key]=self.entailment.check(text,evidence,target)
        return self.cache[key].model_copy(update={'target':target})

    def build(self,draft,*,parent=None,style=None,changed_atoms=()):
        if parent and digest({k:v for k,v in parent.items() if k!='version'})!=parent['version']:
            raise ValueError('PARENT_VERSION_INTEGRITY')
        facets=self.pack['task']['facets']
        if [s['facet'] for s in draft['slides']]!=[f['id'] for f in facets]:raise ValueError('SLIDE_FACET_ORDER')
        if 'content_plan' in self.pack:
            plan = self.pack['content_plan']
            if plan.get('selection_mode') == 'bounded-multiple-v1':
                slots = unit_slots(self.pack['task'])
                if sum(len(s['units']) for s in draft['slides']) > sum(slots.values()) or any(len(s['units']) > slots[s['facet']] for s in draft['slides']):
                    raise ValueError('CONTENT_PLAN_UNIT_LIMIT')
                for slide in draft['slides']:
                    allowed = {i['support'] for i in plan['items'] if i['facet'] == slide['facet'] and i['state'] == 'reviewed'}
                    if any(a['support'] not in allowed for a in slide['units']):
                        raise ValueError('CONTENT_PLAN_SUPPORT_SELECTION')
            else:
                for slide, item in zip(draft['slides'], plan['items']):
                    if any(a['support'] != item['support'] for a in slide['units']):
                        raise ValueError('CONTENT_PLAN_SUPPORT_SELECTION')
        old={c['binding']:c for s in (parent or {}).get('slides',[]) for c in s['checks']}
        slides=[]; used=set()
        reusable = (parent is not None and parent.get('pack_sha256') == digest(self.pack)
                    and parent.get('verifier') == self.identity)
        for s in draft['slides']:
            title=s.get('factual_title')
            atoms=([title] if title else [])+s['units']
            previous=next((v for v in (parent or {}).get('slides',[])
                           if v['facet']==s['facet']),None)
            unchanged=(([previous['factual_title']] if previous.get('factual_title') else [])
                       +previous['units']) if previous else []
            checked=[]
            for i,a in enumerate(atoms):
                same = (previous is not None and previous.get('factual_title') == title
                        and i < len(unchanged) and a == unchanged[i]
                        and (s['facet'],i-(1 if title else 0)) not in changed_atoms)
                if same and reusable:
                    # Immutable receipts, including blocked states, survive an
                    # unrelated edit. Never reconstruct a deleted context.
                    receipt=dict(deepcopy(previous['checks'][i]),reused=True);used.add(receipt['binding'])
                else:
                    if parent is None and 'content_plan' in self.pack:
                        from .planning import construct
                        a=construct(self.pack,a)
                    elif same:
                        # Changed policy/source identity: recheck saved content,
                        # not the pre-construction raw proposal.
                        a=deepcopy(previous['checks'][i]['atom'])
                    receipt=self.check(a,title=title,prior=old,select_context=parent is None)
                    if receipt['reused']:used.add(receipt['binding'])
                checked.append(receipt)
            slides.append(dict(**deepcopy(s),checks=checked,displayed=bool(atoms) and all(c['status']=='verified' for c in checked)))
        result=dict(configuration=POLICY,pack_sha256=digest(self.pack),task=self.pack['task'],verifier=self.identity,
            parent_version=(parent or {}).get('version'),style=style or {},slides=slides,
            reused_receipts=sorted(used),invalidated_receipts=sorted(set(old)-used))
        result['version']=digest(result);return result

    def edit(self,parent,operations):
        if digest({k:v for k,v in parent.items() if k!='version'})!=parent['version']:raise ValueError('PARENT_VERSION_INTEGRITY')
        # Style is a view of the SAVED version, independent of today's source,
        # construction and verifier identity. Even blocked receipts stay exact.
        if all(op['op']=='style' for op in operations):
            return style_version(parent,operations)
        draft=dict(slides=[{k:deepcopy(v) for k,v in s.items() if k not in ('checks','displayed')} for s in parent['slides']]);style=deepcopy(parent['style']);touched=set()
        for op in operations:
            if op['op']=='style':
                if op['key'] not in ('accent','density'):raise ValueError('STYLE_KEY')
                style[op['key']]=op['value']
            elif op['op']=='replace_unit':
                # Full replacement means exactly the supplied content. Internal
                # construction carriers are not part of the public operation.
                if any(k.startswith('_') for k in op['value']):raise ValueError('EDIT_INTERNAL_FIELD')
                draft['slides'][op['slide']]['units'][op['unit']]=deepcopy(op['value'])
                touched.add((draft['slides'][op['slide']]['facet'],op['unit']))
            elif op['op'] in ('edit_claim','replace_context'):
                if op['op']=='replace_context' and self.pack.get('display_policy')!='selected-context-v1':
                    raise ValueError('EXPLICIT_CONTEXT_REQUIRES_SELECTED_DISPLAY')
                expected={'op','slide','unit','text' if op['op']=='edit_claim' else 'value'}
                if set(op)!=expected:raise ValueError('EDIT_OPERATION_FIELDS')
                si,ui=op['slide'],op['unit'];slide=draft['slides'][si]
                a=deepcopy(slide['units'][ui])
                # Materialize the final context once, before changing the claim.
                # Keep exact quotes/references/origin; no source fallback or
                # shortening may replace it during the affected recheck.
                if (slide['facet'],ui) not in touched:
                    c=parent['slides'][si]['checks'][ui+(1 if parent['slides'][si].get('factual_title') else 0)]
                    if self.pack.get('display_policy')=='selected-context-v1':
                        a['_built_context']=deepcopy(c.get('display',{}).get('context',[]))
                if op['op']=='edit_claim':
                    if not isinstance(op['text'],str) or not op['text'].strip():raise ValueError('EDIT_CLAIM_TEXT')
                    a['text']=op['text']
                else:
                    if set(op['value'])!={'text','sources'}:raise ValueError('EDIT_CONTEXT_FIELDS')
                    a['context']=deepcopy(op['value']);a.pop('_built_context',None);a.pop('_context_proposal',None)
                slide['units'][ui]=a
                touched.add((slide['facet'],ui))
            elif op['op']=='factual_title':
                draft['slides'][op['slide']]['factual_title']=deepcopy(op['value'])
                touched.add((draft['slides'][op['slide']]['facet'],-1))
            else:raise ValueError('EDIT_OPERATION')
        return self.build(draft,parent=parent,style=style,changed_atoms=touched)


def render(version):
    if digest({k:v for k,v in version.items() if k!='version'})!=version['version']:raise ValueError('VERSION_INTEGRITY')
    lines=['# Evidence-backed storyboard','',f"Version: {version['version']}",'']
    for slide,facet in zip(version['slides'],version['task']['facets']):
        lines += ['## '+facet['label'],'']
        if not slide['displayed']:
            lines += ['Content gap: '+ '; '.join(sorted({r for c in slide['checks'] for r in c.get('reasons',[]) } or {'support not established'})),''];continue
        for c in slide['checks']:
            d=c['display']
            if 'display_sha256' in c and digest(d)!=c['display_sha256']:
                raise ValueError('DISPLAY_VERIFICATION_INVALIDATED')
            local=d.get('local_context')
            if local:
                from .context_display import POLICY as context_policy, anaphora_audit
                if local.get('policy')!=context_policy or not anaphora_audit(d['text'],local)['resolved']:
                    raise ValueError('DISPLAY_CONTEXT_INVALIDATED')
                refs=local['preceding']+local['headings']
                if any(r['doc_id']!=d['support']['doc_id'] for r in refs):raise ValueError('DISPLAY_CONTEXT_SOURCE')
                lines += ['Source: '+local['source_title'],'']
                if local['headings']:lines += ['Governing heading: '+' › '.join(r['quote'] for r in local['headings']),'']
                for ref in local['preceding']:lines += ['Local source context (display only; not a verified claim): '+ref['quote'].strip(),str(ref),'']
            for ctx in d['context']:
                label='Source-backed context: ' if ctx.get('origin')=='source-backed context' else 'Context: '
                lines += [label+ctx['quote'].strip(),str(ctx.get("citations",ctx)),'']
            lines += [('**'+d['text']+'**') if local else d['text'],f"[{d['support']['doc_id']}, PDF p.{d['support']['pdf_page_index']+1}, {d['support']['block_id']} {d['support']['start']}:{d['support']['end']}]",'']
    return '\n'.join(lines)
