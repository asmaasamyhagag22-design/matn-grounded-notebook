"""Rules-only verifier over authoritative stored DocumentStructure snapshots.

No PDF readers, retrieval mutation, model imports or UI side effects. L2 is veto-only;
L1/L3 are positive gates. Every receipt also contains final-sentence L1–L4 checks.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from pydantic import ValidationError
from matn_contracts.structure import DocumentStructure
from matn_rag.contracts import canonical
from .contracts import Check, Evidence, Request, Receipt, NotRunEntailment, aggregate
from .numbers import parse
from .subjects import DOCUMENT_SUBJECTS, FOREIGN_GEOGRAPHIES


def fingerprint(document):
    return hashlib.sha256(canonical(document.model_dump(mode='json'))).hexdigest()


def _value(value):
    return getattr(value, 'value', value)


def eligibility(document, element):
    """Overlapping veto reasons; all consumers share this same policy."""
    b = element.block; flags = set(element.flags) | set(element.exclusion_reasons)
    reasons = []
    if _value(b.visibility) != 'visible': reasons.append('evidence_hidden')
    if element.role == 'figure' or _value(b.block_type) == 'figure' or 'figure_text' in flags:
        reasons.append('evidence_in_figure')
    if 'code_text' in flags: reasons.append('code_text')
    page = next((p for p in document.pages if p.pdf_page_index == b.page_index), None)
    if page is None: reasons.append('snapshot_invalid')
    elif page.route == 'mixed' and _value(b.route) == 'ocr': reasons.append('mixed_ocr_evidence')
    tables = [t for t in document.tables if b.block_id in t.block_ids]
    if element.role == 'table' or _value(b.block_type) == 'table':
        if not tables or any(t.structure != 'available' for t in tables):
            reasons.append('unavailable_table_evidence')
    if not element.citable: reasons.append('evidence_not_citable')
    return tuple(dict.fromkeys(reasons))


def _linked(number):
    if number.status == 'digital':
        return number.reader_source == 'digital' and bool(number.reader_ref) and number.bbox.bbox_precision in ('char','word')
    if number.status == 'accepted':
        return number.reader_source == 'ocr' and bool(number.reader_ref and number.reader_status and number.reader_bbox)
    return False


def _cell_number(document, element, number):
    b = element.block
    if element.role != 'table' and _value(b.block_type) != 'table': return True
    return any(t.structure == 'available' and b.block_id in t.block_ids and any(
        not cell.is_header and any(s.block_id == b.block_id and s.start <= number.start and s.end >= number.end for s in cell.source_spans)
        for cell in t.cells) for t in document.tables)


def coverage(document):
    """Both all-block and citable baselines; veto totals overlap, union never does."""
    all_counts = Counter(); base = Counter(); survived = Counter(); vetoes = {}; numeric = Counter()
    dispositions = Counter(); eligible_status = Counter()
    for e in document.elements:
        size = len(e.block.text); all_counts.update(blocks=1, characters=size)
        reasons = eligibility(document, e)
        if e.citable:
            base.update(blocks=1, characters=size)
            if not reasons: survived.update(blocks=1, characters=size)
        for reason in reasons:
            row = vetoes.setdefault(reason, Counter())
            row.update(blocks=1, characters=size)
            if e.citable: row.update(citable_blocks=1, citable_characters=size)
        for n in e.number_tokens:
            numeric['all'] += 1; dispositions[n.status] += 1
            if e.citable: numeric['citable'] += 1
            if _linked(n): numeric['linked_status'] += 1
            if _linked(n) and not reasons and _cell_number(document, e, n):
                numeric['eligible'] += 1; eligible_status[n.status] += 1
            for reason in reasons: vetoes[reason]['numeric_tokens'] += 1
    return dict(doc_id=document.doc_id, fingerprint=fingerprint(document), all_blocks=dict(all_counts),
                citable=dict(base), surviving={k:survived[k] for k in ('blocks','characters')},
                vetoes={k:dict(v) for k,v in sorted(vetoes.items())},
                numeric={k:numeric[k] for k in ('all','citable','linked_status','eligible')},
                numeric_status=dict(dispositions), eligible_numeric_status=dict(eligible_status))


def _check(target, layer, verdict='pass', reasons=()):
    return Check(target=target, layer=layer, verdict=verdict, reasons=tuple(dict.fromkeys(reasons)))


def interval_covered(ref, spans):
    cursor=ref.start
    for a,z in sorted((s.start,s.end) for s in spans if s.block_id==ref.block_id):
        if a<=cursor<z: cursor=min(z,ref.end)
    return cursor==ref.end


def evidence_bundles(documents, refs):
    """Only adjacent authoritative blocks continuing an unfinished sentence form an edge."""
    from .contracts import Citation
    refs=[r if isinstance(r,Citation) else Citation.model_validate(r) for r in refs]
    positions={e.block.block_id:(d.doc_id,i,e) for d in documents for i,e in enumerate(d.elements)}
    groups=[]
    for ref in refs:
        if groups:
            prev=groups[-1][-1]; a=positions.get(prev.block_id); b=positions.get(ref.block_id)
            if a and b and a[0]==b[0] and b[1]==a[1]+1 and prev.end==len(a[2].block.text) and ref.start==0:
                tail=a[2].block.text[prev.start:prev.end].rstrip()
                head=b[2].block.text[:ref.end].lstrip()
                if tail and head and tail[-1] not in '.!?;:' and head[0].islower():
                    groups[-1].append(ref); continue
        groups.append([ref])
    return groups


def _semantic_entries(entries):
    # Called only for a single validated evidence bundle. Shift numeric provenance,
    # preserving originals for the receipt and entailment adapter.
    if len(entries)<2:return entries
    d,e,ref,_=entries[0]; text=''; tokens=[]
    for _,element,r,q in entries:
        if text:text+=' '
        offset=len(text)
        tokens.extend(n.model_copy(update={'start':offset+n.start-r.start,'end':offset+n.end-r.start})
                      for n in element.number_tokens if r.start<=n.start<n.end<=r.end)
        text+=q
    block=e.block.model_copy(update={'text':text})
    element=e.model_copy(update={'block':block,'number_tokens':tuple(tokens)})
    return [(d,element,ref.model_copy(update={'start':0,'end':len(text)}),text)]


def _resolve(documents, req, refs, target, fingerprints):
    entries = []; errors = []
    by = {e.block.block_id:(d,e) for d in documents for e in d.elements}
    if not refs: errors.append('invalid_evidence_span')
    for ref in refs:
        pair = by.get(ref.block_id)
        if pair is None: errors.append('invalid_evidence_span'); continue
        d,e = pair; b=e.block
        if d.doc_id not in req.selected_doc_ids: errors.append('source_not_selected')
        if req.retrieved_spans is not None and not interval_covered(ref,req.retrieved_spans):
            errors.append('evidence_not_retrieved')
        if req.fingerprints.get(d.doc_id) != fingerprints[d.doc_id]: errors.append('stale_source')
        if not 0 <= ref.start < ref.end <= len(b.text): errors.append('invalid_evidence_span'); continue
        quote = b.text[ref.start:ref.end]
        if not quote.strip() or (ref.start and b.text[ref.start-1].isalnum() and quote[0].isalnum()) or (ref.end<len(b.text) and b.text[ref.end].isalnum() and quote[-1].isalnum()):
            errors.append('invalid_evidence_span')
        if ref.quote is not None and ref.quote != quote: errors.append('quote_not_found')
        errors.extend(eligibility(d,e))
        # Citations must resolve to primary source intervals, never prefix/separator offsets.
        intervals = sorted((s.start,s.end) for c in d.chunks for s in c.primary if s.block_id == b.block_id)
        cursor=ref.start
        for a,z in intervals:
            if a <= cursor < z: cursor=min(z,ref.end)
        if cursor != ref.end: errors.append('evidence_not_citable')
        entries.append((d,e,ref,quote))
    return _check(target,'L0','reject' if errors else 'pass',errors), entries


# Capitalized spans are a conservative entity surface, never a claim-supplied allow-list.
_CAP = re.compile(r'\b(?:[A-Z][A-Za-z0-9-]*)(?:\s+(?:(?:of|the|and)\s+)?[A-Z][A-Za-z0-9-]*)*\b')
_NON_ENTITY = {'the','a','an','some','all','most','only','revenue','employment','costs','growth','rate','systems','source','this','these','it','there','however','overall','according'}


def entities(text):
    result=[]
    for m in _CAP.finditer(text):
        name=m.group().strip()
        if re.fullmatch(r'(?:Q[1-4]-)?FY\d{4}|GDP|US',name): continue
        name=re.sub(r'^(The|A|An)\s+', '', name)
        if name.casefold() not in _NON_ENTITY: result.append(name)
    return tuple(dict.fromkeys(result))


def _contains(text, entity):
    return bool(re.search(r'(?<!\w)'+re.escape(entity)+r'(?!\w)',text,re.I))


def _registered_subjects(document, evidence):
    subjects=DOCUMENT_SUBJECTS.get(document.doc_id,())
    if any(_contains(evidence,geo) for geo in FOREIGN_GEOGRAPHIES if geo not in subjects):
        return ()
    return subjects


def _own_segments(text, evidence, subjects=()):
    """Evidence clauses containing the claim's named entity, with raw offsets."""
    names=tuple(n for n in entities(text) if n not in subjects or _contains(evidence,n))
    chunks=[(m.start(),m.end(),m.group()) for m in re.finditer(r'.+?(?:[.!?](?!\d)|;|(?=\s+(?:and|while|whereas|but)\s+[A-Z])|$)',evidence,re.S)]
    if not chunks: chunks=[(0,len(evidence),evidence)]
    if not names: return chunks
    return [(a,z,s) for a,z,s in chunks if any(_contains(s,n) for n in names)]


def _l1(text, entries, target):
    claim_numbers, problems=parse(text)
    if problems:
        verdict='reject' if 'spelled_number_mismatch' in problems else 'unknown'
        return _check(target,'L1',verdict,problems)
    errors=[]; unknown=[]
    for n in claim_numbers:
        claim_clause=next((s for a,z,s in _own_segments('',text) if a<=n.start<z),text)
        matches=[]
        for d,e,ref,quote in entries:
            for a,z,segment in _own_segments(claim_clause,quote,_registered_subjects(d,quote)):
                nums,_=parse(segment)
                for ev in nums:
                    if ev.value == n.value: matches.append((d,e,ref,ev,ref.start+a+ev.start,ref.start+a+ev.end))
        if not matches: errors.append('number_not_in_evidence'); continue
        scoped=[m for m in matches if m[3].unit == n.unit]
        if not scoped: errors.append('scope_mismatch'); continue
        qualified=[m for m in scoped if m[3].qualifier == n.qualifier]
        if not qualified: errors.append('quantity_mismatch'); continue
        # Essential explicit period, entity and match-level scope must stay on the claim.
        scoped_qualified=[]
        for match in qualified:
            d,e,ref,ev,start,end=match
            own=[s for a,z,s in _own_segments(claim_clause,e.block.text[ref.start:ref.end],_registered_subjects(d,e.block.text[ref.start:ref.end]))
                 if ref.start+a <= start < ref.start+z]
            source=' '.join(own)
            years=set(re.findall(r'\b(?:19|20)\d{2}\b',source))
            missing_years=years-set(re.findall(r'\b(?:19|20)\d{2}\b',claim_clause))
            source_entities=entities(source)
            missing_entities=source_entities and not entities(claim_clause)
            level_words={'national','sector','occupation','industry','global','regional','household','annual','quarterly','monthly'}
            missing_levels=(_words(source)&level_words)-_words(claim_clause)
            if missing_years or missing_entities or missing_levels:
                unknown.append('scope_unknown')
            else: scoped_qualified.append(match)
        if not scoped_qualified:
            continue
        linked=False; badstatus=False; nocell=False
        for d,e,ref,ev,start,end in scoped_qualified:
            ledger=[v for v in e.number_tokens if v.start<=start and v.end>=end]
            if ev.unit.startswith('period:'):
                digits=[(start+m.start(),start+m.end()) for m in re.finditer(r'\d+',e.block.text[start:end])]
                components=[[v for v in e.number_tokens if v.start<=a and z<=v.end] for a,z in digits]
                if components and all(any(_linked(v) and _cell_number(d,e,v) for v in vs) for vs in components):
                    linked=True
                elif any(vs and not any(_linked(v) for v in vs) for vs in components):
                    badstatus=True
                continue
            if not ledger: continue
            for token in ledger:
                if not _linked(token): badstatus=True; continue
                if not _cell_number(d,e,token): nocell=True; continue
                linked=True
        if not linked:
            if badstatus: errors.append('number_status_disallowed')
            elif nocell: errors.append('table_cell_required')
            else: unknown.append('number_unlinked')
    # Dates, explicit units and named geography cannot be imported from a neighbor.
    # A narrow grammar is deliberately positive: unsupported numeric relations abstain.
    if claim_numbers and re.search(r'\b(per|ratio|versus|vs\.?|relative to)\b',text,re.I):
        combined=' '.join(q for _,_,_,q in entries)
        if not re.search(r'\b(per|ratio|versus|vs\.?|relative to)\b',combined,re.I): unknown.append('scope_unknown')
    return _check(target,'L1','reject' if errors else 'unknown' if unknown else 'pass',errors+unknown)


_UP=set('increase increased increases increasing rise rises rose risen grow grows grew grown growth expand expands expanded up'.split())
_DOWN=set('decrease decreased decreases decreasing fall falls fell fallen decline declined drop dropped down shrink shrank'.split())
_NEG=set('not no never without cannot'.split())
_MODAL=set('can could may might should must would will expected estimated likely unlikely'.split())
_QUANTITY=set('all some most only few many every always'.split())


def _words(text): return set(re.findall(r"[a-z]+",text.lower()))


def _l2(text, entries, target):
    segments=[s for _,_,_,q in entries for _,_,s in _own_segments(text,q)]
    if not segments: return _check(target,'L2')  # L3, not L2, owns missing bindings
    evidence=' '.join(segments); a=_words(text); b=_words(evidence); reasons=[]
    if (a&_UP and not a&_DOWN and b&_DOWN and not b&_UP) or (a&_DOWN and not a&_UP and b&_UP and not b&_DOWN): reasons.append('direction_mismatch')
    # Presence comparison only when each side is one clause. Multi-clause ambiguity is L4's job.
    if len(segments)==1:
        if bool(a&_NEG) != bool(b&_NEG): reasons.append('negation_mismatch')
        # Future copula and 'will need' preserve necessity, not an event prediction.
        copula=lambda t: re.sub(r'\bwill\s+(?:be(?=\s+(?:crucial|essential|necessary|important)\b)|need(?=\s+to\s+be\s+complemented\b))','',t.lower())
        am=_words(copula(text))&_MODAL; bm=_words(copula(evidence))&_MODAL
        if am != bm: reasons.append('modality_mismatch')
        # A quantity in an unrelated evidence adjunct is not the claim's quantifier.
        quant=lambda t: re.match(r'^(?:the\s+)?(all|some|most|only|few|many|every)\b',t.strip(),re.I)
        aq=quant(text); bq=quant(evidence)
        if aq and bq and aq.group(1).lower()!=bq.group(1).lower(): reasons.append('quantity_mismatch')
        comp=re.compile(r'(.+?)\s+(?:is\s+)?(higher|lower|greater|less|more)\s+than\s+(.+?)[.!]?$')
        ca=comp.fullmatch(text.strip()); cb=comp.fullmatch(evidence.strip())
        if ca and cb:
            if _words(ca.group(1))==_words(cb.group(3)) and _words(ca.group(3))==_words(cb.group(1)): reasons.append('comparison_mismatch')
    return _check(target,'L2','reject' if reasons else 'pass',reasons)


def _l3(text, entries, target):
    names=entities(text); quotes=[q for _,_,_,q in entries]
    subjects=set.intersection(*(set(_registered_subjects(d,q)) for d,_,_,q in entries)) if entries else set()
    missing=[name for name in names if name not in subjects and not any(_contains(q,name) for q in quotes)]
    if missing: return _check(target,'L3','reject',('attribution_mismatch',))
    fallback={n for n in names if n in subjects and not any(_contains(q,n) for q in quotes)}
    if fallback and any(re.search(r'^(it|they|these|this|he|she|their)\b',q.strip(),re.I) for q in quotes):
        return _check(target,'L3','unknown',('entity_binding_unknown',))
    if re.search(r'^(it|they|these|this|he|she|their)\b',text.strip(),re.I):
        return _check(target,'L3','unknown',('entity_binding_unknown',))
    # A positive lexical subject binding also catches lower-case entity names.
    subject=re.split(r'\b(?:is|are|was|were|has|have|had|can|could|may|might|should|must|would|will|did|does|do|improv\w*|increas\w*|decreas\w*|expand\w*|grew|grow\w*|rose|fell|reach\w*)\b',text, maxsplit=1, flags=re.I)[0]
    subject_words=_words(subject)-{'the','a','an','some','all','most','only'}
    subject_words-=set().union(*(_words(s) for s in subjects))
    if subject_words and not any(subject_words <= _words(q) for q in quotes):
        return _check(target,'L3','unknown',('entity_binding_unknown',))
    # Exact quoted statements with no named entity are allowed to proceed to L4.
    if not names and not any(text.strip().rstrip('.') in q for q in quotes):
        if not any(set(re.findall(r'\b[a-z]+\b',text.lower())) & set(re.findall(r'\b[a-z]+\b',q.lower())) for q in quotes):
            return _check(target,'L3','unknown',('entity_binding_unknown',))
    return _check(target,'L3')


def verify(documents, request, entailment=None):
    """Always recompute; serialized receipts are never authorization to show content."""
    docs=tuple(documents); checks=[]; evidence=[]
    request_bytes=canonical(request)
    sentence=request.get('sentence','') if isinstance(request,dict) else ''
    fps={d.doc_id:fingerprint(d) for d in docs}
    try:
        # JSON-mode strict validation accepts JSON arrays for immutable tuple fields.
        req=Request.model_validate_json(request_bytes)
        if not req.claims or any(not c.citations for c in req.claims):
            raise ValueError('empty request')
    except (ValidationError,ValueError):
        checks=[_check('sentence','L0','unknown',('invalid_request',))]
    else:
        adapter=entailment or NotRunEntailment()
        targets=[(f'claim:{i}:citation:{j}',claim.text,tuple(bundle)) for i,claim in enumerate(req.claims) for j,bundle in enumerate(evidence_bundles(docs,claim.citations))]
        targets += [(f'claim:{i}',c.text,c.citations) for i,c in enumerate(req.claims)]
        union=tuple({(r.block_id,r.start,r.end):r for c in req.claims for r in c.citations}.values())
        targets.append(('sentence',req.sentence,union))
        for target,text,refs in targets:
            l0,entries=_resolve(docs,req,refs,target,fps); checks.append(l0)
            if l0.verdict!='pass':
                checks.extend(_check(target,layer,'not_run') for layer in ('L1','L2','L3','L4')); continue
            for d,e,ref,quote in entries:
                ev=Evidence(block_id=ref.block_id,start=ref.start,end=ref.end,quote=quote,doc_id=d.doc_id,
                            pdf_page_index=e.block.page_index,page_label=e.block.page_label,
                            bbox=e.bbox.coordinates,bbox_precision=e.bbox.bbox_precision)
                if ev not in evidence: evidence.append(ev)
            semantic=entries
            bundles=evidence_bundles(docs,refs)
            if len(bundles)==1: semantic=_semantic_entries(entries)
            group=[_l1(text,semantic,target),_l2(text,semantic,target),_l3(text,semantic,target)]
            checks.extend(group)
            if any(c.verdict!='pass' for c in group): checks.append(_check(target,'L4','not_run'))
            else:
                try:
                    resolved=tuple(Evidence(block_id=r.block_id,start=r.start,end=r.end,quote=q,doc_id=d.doc_id,
                            pdf_page_index=e.block.page_index,page_label=e.block.page_label,bbox=e.bbox.coordinates,bbox_precision=e.bbox.bbox_precision) for d,e,r,q in entries)
                    decision=adapter.check(text,resolved,target)
                    if not isinstance(decision,Check) or decision.layer!='L4' or decision.target!=target: raise ValueError('invalid model output')
                    checks.append(decision)
                except Exception:
                    checks.append(_check(target,'L4','unknown',('model_output_invalid',)))
    return Receipt(text_sha256=hashlib.sha256(str(sentence).encode()).hexdigest(),
                   request_sha256=hashlib.sha256(request_bytes).hexdigest(),source_fingerprints=fps,
                   checks=tuple(checks),evidence=tuple(evidence),status=aggregate(checks))
