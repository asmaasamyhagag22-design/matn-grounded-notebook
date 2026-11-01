"""Opt-in bounded candidate reranking; unchanged source/quantity/scope verification."""
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time
from types import FunctionType

from matn_rag.contracts import canonical
from . import engine
from .preserved import PreservedChatEngine, preserved_payload, build_meaning_handles

ROOT = Path(__file__).resolve().parents[1]
RELIABLE_SCHEMA=copy.deepcopy(engine.SCHEMA)
item=RELIABLE_SCHEMA['properties']['sentences']['items']
item['properties']['claim']=item['properties'].pop('text')
item['required']=['claim' if k=='text' else k for k in item['required']]
RELIABLE_SCHEMA['properties']['sentences']['items']['properties']['part']={'type':'integer','minimum':0,'maximum':1}
RELIABLE_SCHEMA['properties']['sentences']['items']['required'].append('part')


class LocalReranker:
    """Pinned installed CPU sidecar, no acquisition or external inference."""
    def __init__(self, model=None, python=None, cache=None, deadline=None):
        settings = json.loads((ROOT/'eval/reranker_settings.json').read_bytes())
        self.model = Path(model) if model else Path.home()/'.cache/huggingface/hub/models--Qwen--Qwen3-Reranker-0.6B/snapshots'/settings['model_revision']
        self.python = Path(python) if python else Path.home()/'.venvs/matn-rerank/bin/python'
        self.calls = []
        self.deadline=deadline if deadline is not None else float('inf')
        self.model_revision=settings['model_revision']
        self.worker_sha256=hashlib.sha256((ROOT/'matn_chat/rerank_worker.py').read_bytes()).hexdigest()
        self.cache=Path(cache) if cache else None
        self.settings_sha256=hashlib.sha256((ROOT/'eval/reranker_settings.json').read_bytes()+(ROOT/'matn_chat/rerank_worker.py').read_bytes()).hexdigest()

    def _validate_result(self, result, binding, hits):
        if result['input_sha256']!=binding or result['model_revision']!=self.model_revision or result['worker_sha256']!=self.worker_sha256:
            raise ValueError('RERANK_PRODUCER_BINDING')
        values=result['queries'][0]['scores'];scores={v['id']:v['score'] for v in values}
        if len(values)!=len(hits) or set(scores)!={h['chunk_id'] for h in hits} or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in scores.values()):
            raise ValueError('RERANK_SCORE_BINDING')
        return scores

    def rank(self, question, hits):
        data = canonical(dict(queries=[dict(id='chat', query=question,
            passages=[dict(id=h['chunk_id'], text=h['text']) for h in hits])]))
        binding = hashlib.sha256(data).hexdigest(); start = time.monotonic()
        cache_path=self.cache/(self.settings_sha256+'-'+binding+'.json') if self.cache else None
        if cache_path and cache_path.exists():
            from .readiness import load_page
            record=load_page(cache_path)
            if record['binding']!=binding or record['settings_sha256']!=self.settings_sha256:raise ValueError('RERANK_CACHE_IDENTITY')
            result=record['result'];scores=self._validate_result(result,binding,hits)
            self.calls.append(dict(binding=binding,cache_hit=True,complete=True,new_model_calls=0,wall_seconds=time.monotonic()-start))
            return sorted([dict(h,rerank_score=scores[h['chunk_id']]) for h in hits],key=lambda h:(-h['rerank_score'],h['chunk_id']))
        with tempfile.TemporaryDirectory(prefix='matn-rank-') as folder:
            folder = Path(folder); source=folder/'input.json';source.write_bytes(data)
            cmd=[str(self.python),str(ROOT/'matn_chat/rerank_worker.py'),'--model-path',str(self.model),
                 '--input',str(source),'--input-sha256',binding,'--output',str(folder/'result.json'),
                 '--cost',str(folder/'cost.json')]
            call=dict(binding=binding, input=json.loads(data), model_path=str(self.model), complete=False)
            self.calls.append(call)
            try:
                remaining=self.deadline-time.time()
                if remaining<=0:raise TimeoutError('RERANK_COLLECTION_BUDGET')
                run=subprocess.run(cmd,capture_output=True,text=True,timeout=min(1200,remaining))
                if run.returncode:
                    raise RuntimeError('RERANK_FAILED: '+run.stderr[-1500:])
                result=json.loads((folder/'result.json').read_bytes())
                scores=self._validate_result(result,binding,hits)
                call.update(complete=True,result=result,cost=json.loads((folder/'cost.json').read_bytes()),new_model_calls=1)
                if cache_path:
                    from .readiness import save_page
                    self.cache.mkdir(parents=True,exist_ok=True)
                    save_page(cache_path,dict(binding=binding,settings_sha256=self.settings_sha256,result=result))
                return sorted([dict(h,rerank_score=scores[h['chunk_id']]) for h in hits],
                              key=lambda h:(-h['rerank_score'],h['chunk_id']))
            except BaseException as exc:
                call['error']=type(exc).__name__+': '+str(exc)
                raise
            finally:call['wall_seconds']=time.monotonic()-start


class AnswerRequest(str):
    """The string is exclusively the current task; reference is orientation only.

    Kept through the inherited engine API so packing and fallback cannot split
    a previous interrogative into an additional answer obligation.
    """
    def __new__(cls, current, reference=''):
        value=super().__new__(cls,current)
        value.reference=reference
        value.retrieval_text=current+(' Reference for resolving mentions only: '+reference if reference else '')
        value.scope_text=value.retrieval_text
        value.reliable_scope=True
        return value


def subquestions(question):
    """Only explicit question boundaries, at most two; no invented premises."""
    import re
    parts=[x.strip(' ;') for x in re.split(r'(?<=\?)\s+(?:and\s+)?|;\s*(?:and\s+)?',question,flags=re.I) if x.strip(' ;')]
    parts=parts if 1<len(parts)<=2 else [str(question)]
    if isinstance(question,AnswerRequest):
        return [AnswerRequest(p,question.reference) for p in parts]
    return parts


class CandidateSearch:
    def __init__(self, search, reranker, documents=()):
        self.search=search;self.repo=getattr(search,'repo',None);self.reranker=reranker;self.audit={}
        self.documents=tuple(documents)

    def query(self, notebook, sources, question, **kwargs):
        from .question_scope import question_scope
        self.repo.validate_selection(notebook,sources)
        scope=question_scope(question,[r['text'] for r in self.repo.selected_chunks(notebook,sources)]) if hasattr(self.repo,'selected_chunks') else {'passed':True}
        if not scope['passed']:
            self.audit=dict(policy='explicit_dates_unavailable_in_selected_index',question_scope=scope,candidate_count=0,queries=[],legs=[],ranked=[])
            return dict(hits=[],retrieval_audit=self.audit)
        hits={}; legs=[]; queries=subquestions(question)
        for part in queries:
            query=getattr(part,'retrieval_text',part)
            value=self.search.query(notebook,sources,query,mode='focused',depth=100,ablation='no-prefix')
            legs.append(dict(query=query,hits=value['hits']))
            hits.update({h['chunk_id']:h for h in value['hits']})
        # RRF already bounds each stream to50. Two explicit subquestions at most.
        candidates=list(hits.values())
        if self.documents:
            from matn_verification.rules import eligibility
            owners={e.block.block_id:(d,e) for d in self.documents for e in d.elements}
            grouped={}
            for hit in candidates:
                for locator in hit['evidence']:
                    if locator['kind']!='pdf_block_span':continue
                    b=locator['payload']['block_id'];d,e=owners[b]
                    if eligibility(d,e) or not e.block.text.strip():continue
                    if b not in grouped:
                        # Retrieve the complete original eligible block, including
                        # its source conditions. No chunk separators or titles.
                        spans=[(c,s) for c in d.chunks for s in c.primary if s.block_id==b]
                        evidence=[dict(kind='pdf_block_span',payload=dict(block_id=b,start=s.start,end=s.end,
                            primary_chunk_id=c.chunk_id,pdf_page_index=e.block.page_index,page_label=e.block.page_label,
                            bbox=e.bbox.model_dump(mode='json'))) for c,s in spans]
                        grouped[b]=dict(hit,chunk_id='block:'+b,block_id=b,text=e.block.text,evidence=evidence,
                            candidate_chunk_ids=[],expansion_policy='complete_primary_spans_of_retrieved_source_block')
                    grouped[b]['candidate_chunk_ids'].append(hit['chunk_id'])
            candidates=list(grouped.values())
        ranked=self.reranker.rank(question,candidates) if candidates else []
        self.audit=dict(policy='candidate100-per-part-block-rerank-packed4000-v1',queries=queries,legs=legs,
                        candidate_count=len(hits),block_candidates=len(candidates),ranked=ranked,search_queries=len(queries))
        value['hits']=ranked;value['retrieval_audit']=self.audit
        return value


def pack_ranked(question, handles, max_characters=4000):
    """Rank order plus complete source units, with no cut conditions or splices.

    Short blocks stay whole. Long blocks use a query-directed component of
    original sentence handles, linking unresolved openings and qualifications
    to their predecessor. The unchanged verifier still checks *full* source
    units and adjacent qualifications; packing is never a support permission.
    """
    import re
    from matn_verification.prose import unresolved_opening
    from .evidence_selection import score
    asks_method=bool(re.search(r'\b(method|methodology|calculate|calculated|calculation|survey|respondents|sample|sampling|definition|define|mean|user guide|coverage|taxonomy)\b',question,re.I))
    groups={}
    # Canonical JSON sorts mapping keys lexically; s10 must not precede s2
    # when a saved catalog is inspected or replayed. IDs carry retrieval order.
    ordered=sorted(handles.items(),key=lambda pair:int(pair[0][1:]) if pair[0].startswith('s') and pair[0][1:].isdigit() else 10**9)
    for key,h in ordered:
        group=tuple(sorted({c['block_id'] for c in h['citations']}))
        groups.setdefault(group,[]).append((key,h))
    kept={};used=0
    for rows in groups.values():
        paths=[path for _,h in rows for path in h.get('source_sections',[])]
        source_method=any(re.search(r'\b(methodology|user guide|survey design)\b',' '.join(path[:3]),re.I) for path in paths)
        # Source genre is orientation for answer selection, never proof. Method
        # sections remain retrievable and are used for explicit method questions.
        if source_method and not asks_method:continue
        text=' '.join(h['text'] for _,h in rows).strip()
        # A title or bare list of occupations does not independently answer a
        # prose question. Typed tables have their own exact projection path.
        if not text.rstrip('"”\')]').endswith(('.', '!', '?')) or text.endswith('...'):continue
        size=sum(len(h['text']) for _,h in rows)
        if size>1000:
            components=[]
            for key,h in rows:
                linked=unresolved_opening(h['text']) or re.match(
                    r'^\s*(?:however|except|unless|provided that|this (?:rule|requirement|restriction))\b',h['text'],re.I)
                if components and linked:components[-1].append((key,h))
                else:components.append([(key,h)])
            rows=max(components,key=lambda rs:score(question,' '.join(h['text'] for _,h in rs),[x['text'] for x in handles.values()]))
            size=sum(len(h['text']) for _,h in rows)
            text=' '.join(h['text'] for _,h in rows).strip()
            if unresolved_opening(text):continue
        if used+size>max_characters:continue
        kept.update(rows);used+=size
    return kept


def build_reliable_handles(documents, hits):
    documents=tuple(documents)
    handles=build_meaning_handles(documents,hits)
    paths={b:list(section.path) for d in documents for section in d.sections for b in section.block_ids}
    for h in handles.values():
        h['source_sections']=[paths[c['block_id']] for c in h['citations'] if c['block_id'] in paths]
    return handles


def reliable_payload(question, handles, failures=None, *, num_ctx=16384):
    body=preserved_payload(question,handles,failures,num_ctx=num_ctx)
    body['prompt']=body['prompt'].replace('Copy the relevant complete source rule with its conditions when possible.',
        'Keep the complete source form for technical option rules and conditional statistics. Ordinary prose may be paraphrased while retaining its explicit subject and all qualifications.')
    body['prompt']=body['prompt'].replace('At most two sentences.',
        'At most two output items. Each item may keep up to three consecutive source sentences when needed to preserve their subject, conditions and linked exceptions.')
    parts=subquestions(question)
    item=body['format']['properties']['sentences']['items']
    item['properties']['claim']=item['properties'].pop('text')
    item['required']=['claim' if k=='text' else k for k in item['required']]
    body['format']['properties']['sentences']['items']['properties']['part']={'type':'integer','enum':list(range(len(parts)))}
    body['format']['properties']['sentences']['items']['required'].append('part')
    if getattr(question,'reference',''):
        body['prompt'] += '\nReference for resolving mentions ONLY (not a request to answer, not evidence): '+json.dumps(question.reference)
    body['prompt'] += '\nQuestion parts: '+json.dumps([dict(part=i,question=q) for i,q in enumerate(parts)])
    body['prompt'] += ('\nWrite the claim before selecting its source handles. Answer the requested relationship about the requested subject. Do not substitute source methodology for the requested findings. Set part to the question part answered by each item. Each part keeps its own dates and entity scope. Answer the requested parts as one coherent response. Complementary sources need not be compared. '
        'Use one independently supported meaning unit per output item; different items may use different sources. '
        'Do not combine different entities, populations, definitions or periods into one fact. '
        'Use only relevant sources; do not force every selected source into the answer.\n')
    sections={}
    for key,h in handles.items():
        for path in h.get('source_sections',[]):
            # Orientation only; full original titles remain in the trace. A
            # source guide/method cannot silently pose as reported findings.
            label=tuple(title[:160] for title in path[:3])
            sections.setdefault(label,[]).append(key)
    body['prompt'] += '\nSource section orientation (titles are not factual evidence): '+json.dumps(
        [dict(section=list(path),handles=list(dict.fromkeys(keys))) for path,keys in sections.items()],ensure_ascii=False,separators=(',',':'))
    return body


class ReliableChatEngine(PreservedChatEngine):
    _ask=FunctionType(engine.ChatEngine.ask.__code__,{**vars(engine),'build_handles':build_reliable_handles})
    def __init__(self, search, documents, *, reranker=None, source_coverage=None, source_revisions=None, **kwargs):
        self.declared_coverage=copy.deepcopy(source_coverage or {})
        self.source_revisions=dict(source_revisions or {})
        documents=tuple(documents)
        from .block_rank import LexicalBlockRanker
        self.candidates=CandidateSearch(search,reranker or LexicalBlockRanker(),documents)
        super().__init__(self.candidates,documents,**kwargs)

    _generate_raw=FunctionType(engine.ChatEngine._generate.__code__,
                               {**vars(engine),'payload':reliable_payload,'SCHEMA':RELIABLE_SCHEMA})
    def _generate_once(self, question, failures, timings):
        generated,entry=self._generate_raw(question,failures,timings)
        # The constrained decoder emits the claim before citation choices.
        # Translate the schema key only; never edit model-written content.
        entry['parsed_original']=copy.deepcopy(entry['parsed'])
        converted=[dict(text=s['claim'],handles=s['handles'],part=s['part']) for s in generated]
        entry['parsed']={'sentences':converted}
        return converted,entry

    _select_handles=staticmethod(pack_ranked)

    def _verify(self, sentences, entry, documents, timings, receipts):
        resolved=[]
        for sentence in sentences:
            part=sentence.get('part')
            if type(part) is not int or not 0<=part<len(self.parts):
                raise engine.ChatFailure('invalid_question_part')
            self.active_question=self.parts[part]
            child=dict(attempt=entry['attempt'],sentences=[],timings={'verification_seconds':0.})
            values=super()._verify([sentence],child,documents,timings,receipts)
            for item,index in values:
                item['question_part']=part;receipts[index]['question_part']=part
            entry['sentences'].extend(child['sentences'])
            entry.setdefault('verification_requests',[]).extend(child.get('verification_requests',[]))
            entry['timings']['verification_seconds']+=child['timings']['verification_seconds']
            resolved.extend(values)
        return resolved

    def _excerpt(self, question, documents, result):
        before=len(result['sentences'])
        super()._excerpt(question,documents,result)
        from .question_scope import question_scope
        retained=result['sentences'][:before]
        for item in result['sentences'][before:]:
            matching=[i for i,p in enumerate(self.parts) if question_scope(p,[item['text']])['passed']]
            if matching:
                item['question_part']=matching[0]
                retained.append(item)
        result['sentences']=retained

    def ask(self, notebook, sources, question, *, query_plan=None):
        if query_plan is not None:
            if question!=query_plan['current_question']:raise ValueError('CURRENT_QUESTION_PLAN_BINDING')
            question=AnswerRequest(question,query_plan['reference_question'])
        else:question=AnswerRequest(question)
        started=self.clock();self.candidates.audit={}
        self.parts=subquestions(question)
        self.candidates.reranker.calls=[]
        result=super().ask(notebook,sources,question)
        if not result.get('error') and result['state']!='deferred_memory':
            selected_ids={r['doc_id'] for r in self.search.repo.source_rows(notebook) if r['id'] in sources}
            documents=[d for d in self.documents if d.doc_id in selected_ids]
            from .source_copy import add_native_copies
            try:add_native_copies(self,documents,result)
            finally:
                if self.owns_entailment:self.entailment.close()
        try:selected_rows=self.search.repo.source_rows(notebook)
        except Exception:selected_rows=[]
        selected_ids={r['doc_id'] for r in selected_rows if r['id'] in sources}
        selected_docs=[d for d in self.documents if d.doc_id in selected_ids]
        from .notebooks import attach_source_context
        attach_source_context(result,selected_docs,self.declared_coverage,self.source_revisions,self.fingerprints)
        result['configuration']='reliable-multisource-v8'
        result['prompt_version']='reliable-source-unit-bm25-v8'
        result['question_parts']=self.parts
        result['retrieval_audit']=self.candidates.audit
        result['reranker_calls']=self.candidates.reranker.calls
        from matn_verification.prose import surface
        by={e.block.block_id:e.block.text for d in self.documents for e in d.elements}
        for item in result['sentences']:
            item['question_part']=result['receipts'][item['receipt_index']].get('question_part')
            if item.get('kind')=='source_excerpt':continue
            copy=any(surface(item['text'])==surface(by[c['block_id']][c['start']:c['end']]) for c in item['citations'])
            item['kind']='source_copy' if copy else 'generated_verified_unit'
            item['verification_scope']='native_L0_L4_and_preserved_scope'
        result['answer_sources']=sorted({c['doc_id'] for s in result['sentences'] for c in s['citations']})
        excerpts=any(s.get('kind')=='source_excerpt' for s in result['sentences'])
        result['answer_kind']=('mixed_source_fidelity' if len(result['answer_sources'])>1 and excerpts else 'generated_multisource' if len(result['answer_sources'])>1 and
            any(s['kind']=='generated_verified_unit' for s in result['sentences']) else
            'multisource_copies' if len(result['answer_sources'])>1 else 'single_source_or_abstention')
        result['timings']['total_seconds']=self.clock()-started
        return result
