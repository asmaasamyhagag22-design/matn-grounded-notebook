"""Per-source hybrid retrieval over a bounded lexical pool; no global source loss."""
from matn_rag.embedding import Embedder, MODEL, query_input
from matn_rag.scoring import bm25,cosine,fuse
from matn_research.requirement_selection import vectors
import json
import re
import time
import urllib.request


class HybridSearch:
    def __init__(self,search,*,lookup=None,release=None):
        self.search=search;self.repo=search.repo;self.coverage=[];self.audit=[]
        self.lookup=lookup or self._vectors;self.release=release or self._release

    def _vectors(self,texts):return vectors(texts,embedder=Embedder(),audit=self.audit)

    @staticmethod
    def _release():
        from matn_rag.transport import LoopbackTransport
        from checks.egress_guard import block_egress
        from matn_chat.memory import sample_memory
        transport=LoopbackTransport(timeout=20)
        request=urllib.request.Request(transport.base_url+'/api/generate',
            data=json.dumps(dict(model=MODEL,keep_alive=0)).encode(),headers={'Content-Type':'application/json'})
        with block_egress(),transport.opener.open(request,timeout=20) as stream:response=json.load(stream)
        if not response.get('done') or response.get('done_reason')!='unload':raise RuntimeError('EMBED_UNLOAD_UNCONFIRMED')
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            if not sample_memory()['ollama_runner_rss_bytes']:return
            time.sleep(.1)
        raise RuntimeError('EMBED_DRAIN_UNCONFIRMED')

    def query(self,notebook,sources,question,**kwargs):
        hits=[];coverage=[]
        try:
            for source in sources:
                value=self.search.query(notebook,[source],question,mode='focused',depth=12,ablation='bm25')
                rows=value['hits'];ranked=[]
                if rows:
                    found=self.lookup([h['text'] for h in rows]+[query_input(str(question))])
                    table={(h['source_id'],h['chunk_id']):v for h,v in zip(rows,found[:-1],strict=True)}
                    semantic=cosine(rows,found[-1],table)
                    lexical=bm25(rows,str(question),prefix=False)
                    ranked=fuse(lexical,semantic,'hybrid')
                by={h['chunk_id']:h for h in rows}
                hits.extend(dict(by[cid],hybrid_score=score,source_hybrid_rank=i+1) for i,(cid,score) in enumerate(ranked))
                coverage.append(dict(source=source,candidates=len(rows),hybrid_candidates=len(ranked)))
        finally:self.release()
        self.coverage.append(dict(question=str(question),sources=coverage,policy='per-source-bm25-prefilter12-hybrid-v1'))
        return dict(hits=hits,source_coverage=coverage)


class HybridBlockRanker:
    def __init__(self):self.calls=[]
    def rank(self,question,hits):
        # Retain the lexical/semantic union. A lexical-only postfilter would
        # silently erase the semantic leg and its source-coverage guarantee.
        from matn_chat.block_rank import exclusion
        groups={};excluded=[]
        for hit in hits:
            reason=exclusion(question,hit)
            if reason:excluded.append(dict(id=hit['chunk_id'],reason=reason));continue
            groups.setdefault(hit['source_id'],[]).append(hit)
        from matn_chat.block_rank import LexicalBlockRanker
        for key,rows in groups.items():
            # A chunk can mix checklist cells with narrative. Rank the complete
            # blocks for the question, then retain semantic-only candidates.
            lexical=LexicalBlockRanker().rank(question,rows)
            seen={h['chunk_id'] for h in lexical}
            semantic=sorted((h for h in rows if h['chunk_id'] not in seen),key=lambda h:(h.get('source_hybrid_rank',10**9),h['chunk_id']))
            groups[key]=lexical+semantic
        result=[]
        for i in range(max(map(len,groups.values()),default=0)):
            result.extend(rows[i] for rows in groups.values() if i<len(rows))
        self.calls.append(dict(policy='round-robin-source-hybrid-v1',new_model_calls=0,excluded=excluded))
        return result


# A full phrase match distinguishes Example 4 from Figure 4 and 10 seconds
# from 10 minutes. It contributes to ranking and carries no verification weight.

_EXACT_TERMS = re.compile(
    r'\b(?:example|figure|fig\.|table|section|appendix|chapter|algorithm|equation)\s+'
    r'(?:[A-Z]?\d+(?:[.-]\d+)*[A-Z]?|[A-Z]\b)'
    r'|\b(?:\d+\.\d+(?:\.\d+)*|[A-Z]{2,}-\d[\w.-]*)\b'
    r'|\b\d+(?:[.,]\d+)*\s*(?:%|(?:percent(?:age points?)?|seconds?|minutes?|hours?|days?|'
    r'weeks?|months?|years?|ms|GB|GiB|MB|MiB|kg|km|USD|EGP|million|billion)\b)'
    r'|["“][^"”\n]+["”]|(?<!\w)[‘\'][^’\'\n]+[’\'](?!\w)', re.IGNORECASE,
)


def _exact_phrases(question):
    return [re.compile(r'(?<!\w)' + re.escape(term).replace(r'\ ', r'\s+') + r'(?!\w)', re.I)
            for term in dict.fromkeys(' '.join(m.group().strip('"“”\'‘’').split())
                                      for m in _EXACT_TERMS.finditer(question)) if term]


class ContextualHybridSearch(HybridSearch):
    """RRF over contextual BM25 and contextual dense vectors for each source."""

    def __init__(self, search, policy, *, documents=(), source_metadata=None, **kwargs):
        super().__init__(search, **kwargs)
        self.policy = policy
        self.documents = documents
        self.source_metadata = source_metadata or {}

    def query(self, notebook, sources, question, **kwargs):
        rows = self.repo.selected_chunks(notebook, sources)
        indexed = self.repo.vectors(sources, 'doc-input-v1')
        phrases = _exact_phrases(str(question))
        components = self.policy.get('components', {})
        named = (matched_document(question, self.documents, self.source_metadata, self.policy)
                 if components.get('scope_documents') else None)
        hits, coverage = [], []
        try:
            for source in sources:
                local = [row for row in rows if row['source_id'] == source]
                texts = {row['chunk_id']: row['context_prefix'] + '\n\n' + row['text'] for row in local}
                exact = {key: sum(bool(phrase.search(text)) for phrase in phrases)
                         for key, text in texts.items()}
                lexical = bm25(local, str(question), prefix=True)
                boosted = sorted(lexical, key=lambda item: (-exact[item[0]], -item[1], item[0]))
                by_id = {row['chunk_id']: row for row in local}
                if not by_id:
                    coverage.append(dict(source=source, candidates=0, hybrid_candidates=0))
                    continue
                complete_index = all((source, key) in indexed for key in by_id)
                pool = (local if complete_index else
                        [by_id[key] for key, _ in boosted[:self.policy['candidate_depth_per_source']]])
                if complete_index:
                    table = indexed
                    query_vector, = self.lookup([query_input(str(question))])
                else:
                    missing = [row for row in pool if (source, row['chunk_id']) not in indexed]
                    found = self.lookup([texts[row['chunk_id']] for row in missing] +
                                        [query_input(str(question))])
                    table = {**indexed, **{(source, row['chunk_id']): vec
                                          for row, vec in zip(missing, found[:-1], strict=True)}}
                    query_vector = found[-1]
                dense = cosine(pool, query_vector, table)
                ranked = fuse(boosted, dense)
                ranked = sorted(ranked, key=lambda item: (
                    -(item[1] + self.policy['exact_term_boost'] * exact[item[0]]), item[0]))
                hits.extend(dict(by_id[key], hybrid_score=score, exact_matches=exact[key],
                                 source_hybrid_rank=rank,
                                 document_match=named is not None and by_id[key].get('doc_id') == named)
                            for rank, (key, score) in enumerate(
                                ranked[:self.policy['hit_depth_per_source']], 1))
                coverage.append(dict(source=source, candidates=len(pool),
                                     hybrid_candidates=len(ranked), indexed_dense=complete_index))
        finally:
            if hits or rows:
                self.release()
        hits.sort(key=lambda hit: (-hit['document_match'], hit['source_hybrid_rank'], -hit['exact_matches'],
                                   -hit['hybrid_score'], hit['source_id'], hit['chunk_id']))
        self.coverage.append(dict(question=str(question), sources=coverage, policy='contextual-rrf-v3', matched_document=named))
        return dict(hits=hits, source_coverage=coverage)


def _scope_words(text):
    return re.findall(r'[^\W_]+', str(text).casefold())


def matched_document(question, documents, metadata, policy):
    """Match unique source names, filenames or distinctive title phrases."""
    query = _scope_words(question)
    query_text = ' '.join(query)
    generic = set(policy['document_scope_stopwords'])
    minimum = policy['document_scope_min_words']
    maximum = policy['document_acronym_max_characters']
    aliases, acronyms = {}, {}
    for document in documents:
        source = metadata.get(document.doc_id, {})
        fields = [document.title]
        for key in ('title', 'short_title', 'publisher', 'organization', 'authors', 'file'):
            value = source.get(key)
            if isinstance(value, str):
                fields.append(value)
            elif isinstance(value, (list, tuple)):
                fields.extend(name for name in value if isinstance(name, str))
        headings = [element for element in document.elements
                    if element.block.page_index == 0 and str(getattr(element.role, 'value', element.role)) == 'heading']
        sizes = [getattr(getattr(e.block, 'style', None), 'font_size_pt', None) or 0 for e in headings]
        largest = max(sizes, default=0)
        fields.extend(e.block.text for e,size in zip(headings,sizes,strict=True) if size == largest)
        aliases[document.doc_id] = [_scope_words(value) for value in fields if value]
        organizations = [source[key] for key in ('publisher','organization','short_title')
                         if isinstance(source.get(key),str)]
        names = {word.casefold() for value in fields
                 if value in organizations or not value.isupper() or len(_scope_words(value)) == 1
                 for word in re.findall(r'\b[A-Z]+\b', value)
                 if minimum <= len(word) <= maximum}
        for value in organizations:
            words = [word for word in _scope_words(value) if word not in generic and len(word) > 1]
            if len(words) == 1 and value == source.get('short_title'):
                names.add(words[0])
            if minimum <= len(words) <= maximum:
                names.add(''.join(word[0] for word in words))
        filenames = [document.title] if '_' in document.title else []
        filenames.append(source.get('file') or '')
        names.update(word for value in filenames for word in _scope_words(value)
                     if word.isalpha() and minimum <= len(word) <= maximum)
        acronyms[document.doc_id] = names - generic

    # Ordinary words such as "what baseline" cannot spell an organization.
    spelled = set()
    capitals = re.finditer(r'\b[A-Z][A-Za-z]+(?:\s+(?:[A-Z][A-Za-z]+|of|the|for|and))+', str(question))
    for match in capitals:
        words = [word for word in _scope_words(match[0]) if word not in generic]
        spelled.update(''.join(word[0] for word in words[start:start+length])
                       for length in range(minimum,maximum+1)
                       for start in range(len(words)-length+1))

    matched = set()
    for doc_id,fields in aliases.items():
        other = {word for other_id,values in aliases.items() if other_id != doc_id
                 for words in values for word in words}
        other_acronyms = set().union(*(names for other_id,names in acronyms.items() if other_id != doc_id))
        unique_acronyms = acronyms[doc_id] - other - other_acronyms
        if unique_acronyms & (set(query) | spelled):
            matched.add(doc_id)
        for words in fields:
            distinctive = [word for word in words if word not in generic and not word.isdigit()]
            exact = len(distinctive) >= minimum and f" {' '.join(words)} " in f' {query_text} '
            short = any(f" {' '.join(words[i:i+minimum])} " in f' {query_text} '
                        and all(word not in generic and not word.isdigit() for word in words[i:i+minimum])
                        and any(word not in other for word in words[i:i+minimum])
                        for i in range(len(words)-minimum+1))
            if exact or short:
                matched.add(doc_id)
    comparison = re.search(policy['cross_document_pattern'], str(question), re.I)
    return next(iter(matched)) if len(matched) == 1 and not comparison else None
