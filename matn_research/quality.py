"""Negative prose screening and auditable requirement agreement, never proof."""
import re
from matn_research.view_rank import retrieval_terms

STOP=set('identify describe outline summarize explain assess evaluate discuss determine establish include provide current existing potential associated relevant specific public general topic subject findings evidence approach appropriate useful important critical crucial essential key vital help ensure support improve use uses using system systems aspect aspects part parts related information brief briefing'.split())
# General requirement vocabulary, independent of topics, sites and saved IDs.
GROUPS=(
 {'policy','legal','law','legislation','legislative','regulation','regulatory','statute','liability','compliance'},
 {'safety','safe','unsafe','hazard','risk','danger','failure'},
 {'cost','economic','economy','funding','fund','finance','financial','budget','subsidy','benefit'},
 {'environment','environmental','recycle','recycling','disposal','waste','emission','pollution'},
 {'adoption','adopt','acceptance','accept','participate','participation','trust','driver'},
 {'example','case','study','implementation','implemented','deploy','deployed','result','outcome'},
 {'barrier','obstacle','challenge','challenging','difficulty','difficult'},
 {'boundary','boundaries','constraint','limitation','limit','tradeoff','tradeoffs'},
 {'data','dataset','database','repository','indicator','statistic'},
 {'governance','oversight','accountability','responsibility','control'},
)


def tokens(text):
    words=retrieval_terms(text)
    for group in GROUPS:
        folded=set().union(*(retrieval_terms(word) for word in group))
        if words & folded:words |= folded
    return words-STOP


def sentence_reason(text,topic=''):
    value=text.strip().lstrip('•- ')
    if re.match(r'(?i)^(?:for one thing\b|in addition\s*[,;:]|additionally\s*,|furthermore\s*,|moreover\s*,)',value):
        return 'discourse_fragment'
    if re.match(r'(?i)^(?:it|they|these|those)\b|^this\s+(?:is|was|has|have|can|could|will|would|means|allows|enables|helps|results|leads)\b',value):
        return 'unresolved_opening'
    if re.match(r'(?i)^this\s+(?:approach|process|step|method|strategy|initiative|change|measure|technique|result|outcome|tool|system|framework)\s+(?:is|was|has|can|could|will|would|means|allows|enables|helps|improves|reduces|provides|requires|results|leads)\b',value):
        return 'unresolved_opening'
    if topic and re.search(r'(?i)\b(?:important|critical|crucial|essential|vital|key)\b',value) and not (tokens(topic)&tokens(value)):
        if re.match(r'(?i)^(?:this|it|they|these|those|success|progress|good practices|effective management|collaboration|innovation|planning|communication)\b',value):
            return 'generic_platitude_without_topic_subject'
    return None


def axis_agreement(requirement,text,*,topic='',label=''):
    """The model must already have selected this text. Matching is a veto only.

    Remove shared topic words, then require an independent requirement anchor.
    The receipt records actual anchors; it never upgrades part to full coverage.
    """
    reason=sentence_reason(text,topic)
    wanted=tokens(requirement+' '+label)-tokens(topic)
    have=tokens(text)
    anchors=sorted(wanted & have)
    return dict(passed=not reason and bool(anchors),reason=reason or (None if anchors else 'no_requirement_anchor'),
                matched_anchors=anchors,requirement_terms=sorted(wanted),policy='model-pick-plus-requirement-anchor-v1',proof=False)


def authoritative_query(query):
    """One existing requirement search gets source-class hints; no extra calls."""
    hint='(site:gov OR site:edu OR site:ac.uk OR site:int OR site:iso.org OR site:oecd.org)'
    return query if 'site:' in query.lower() else query[:300].rstrip()+' '+hint


def commercial_warning(sources,units):
    cited={getattr(u,'source',None) if not isinstance(u,dict) else u.get('source') for u in units}
    rows=[s for s in sources if (getattr(s,'id',None) if not isinstance(s,dict) else s.get('id')) in cited]
    vendor=sum((getattr(s,'type',None) if not isinstance(s,dict) else s.get('type'))=='commercial-vendor' for s in rows)
    return dict(cited_sources=len(rows),commercial_sources=vendor,share=vendor/len(rows) if rows else None,
                warning='Sources are mostly commercial; independent coverage is limited.' if vendor>len(rows)/2 else None)


def filter_saved_catalog(catalog):
    """Conservative display revision of already selected/verified research.

    Never rewrite a saved result, move a unit, promote coverage, or mint a new
    verification receipt. Old model selections must also meet the current veto.
    """
    from dataclasses import replace
    from matn_deck.catalog import Gap
    descriptions=[r.description for r in catalog.plan.requirements]
    common=set.intersection(*(retrieval_terms(d) for d in descriptions)) if descriptions else set()
    retained=[];audit=[];coverage=dict(catalog.origin.get('axis_coverage',{}));gaps=list(catalog.gaps)
    for unit in catalog.units:
        requirements=[r.description for r in catalog.plan.requirements if r.axis==unit.axis]
        label=next(a.title for a in catalog.plan.axes if a.id==unit.axis)
        checks=[axis_agreement(r,unit.text,topic=' '.join(common),label=label) for r in requirements]
        reason=sentence_reason(unit.text,catalog.plan.topic)
        passed=not reason and (not checks or any(c['passed'] for c in checks))
        audit.append(dict(unit=unit.id,axis=unit.axis,model_selected=True,passed=passed,
                          reason=reason or (None if passed else 'no_requirement_anchor'),checks=checks))
        if passed:retained.append(unit)
    kept={u.id for u in retained}
    for axis in catalog.plan.axes:
        old=[u for u in catalog.units if u.axis==axis.id];new=[u for u in retained if u.axis==axis.id]
        if len(new)<len(old):
            coverage[axis.id]='part' if new else 'none'
            if not any(g.axis==axis.id for g in gaps):gaps.append(Gap(axis.id,axis.id,axis.title,(),reason='Saved selections withheld by the current display eligibility checks.'))
    return replace(catalog,units=tuple(retained),numbers=tuple(n for n in catalog.numbers if n.origin=='json' or n.unit_id in kept),
        figures=tuple(replace(f,unit_ids=tuple(u for u in f.unit_ids if u in kept)) for f in catalog.figures if set(f.unit_ids)&kept),
        synthesis=tuple(s for s in catalog.synthesis if set(s.unit_ids)<=kept),gaps=tuple(gaps),
        origin=dict(catalog.origin,display_filter_audit=audit,axis_coverage=coverage,
                    display_revision='Saved model selections and verification; current negative display filters; zero new inference')).validate()
