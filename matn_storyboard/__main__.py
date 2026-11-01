"""Opt-in CLI: run a saved-source task or apply structured versioned edits."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import time
from jsonschema import Draft202012Validator
from matn_contracts.structure import DocumentStructure
from matn_chat.__main__ import ReadOnlyNotebook
from matn_chat.reliable import CandidateSearch, AnswerRequest, build_reliable_handles
from matn_chat.block_rank import LexicalBlockRanker
from matn_chat.readiness import write, lock
from matn_rag.search import Search
from matn_verification.rules import fingerprint
from eval.chat.token_budget import TokenCounter
from .core import (validate_task, pack, evidence_pack, Workflow, digest,
                   save_version, render_markdown)
from .runtime import Calls, Generator, Native


def load(notebook, sources='all'):
    repo=ReadOnlyNotebook(notebook)
    try:
        ids=[r[0] for r in repo.db.execute('select id from notebooks order by id')]
        if len(ids)!=1: raise ValueError('ONE_NOTEBOOK_REQUIRED')
        name=ids[0]; rows=repo.source_rows(name)
        aliases={k:r['id'] for r in rows for k in (r['id'],r['doc_id'])}
        selected=repo.source_ids(name) if sources=='all' else [aliases[s] for s in sources.split(',')]
        repo.validate_selection(name,selected)
        manifest_path=Path(str(notebook)+'.structures.json')
        manifest=json.loads(manifest_path.read_bytes()); documents=[]
        for row in rows:
            if row['id'] not in selected: continue
            path=Path(manifest['documents'][row['doc_id']])
            if not path.is_absolute(): path=manifest_path.parent/path
            d=DocumentStructure.model_validate_json(path.read_bytes())
            if d.doc_id!=row['doc_id'] or json.loads(row['metadata'])['fingerprint']!=fingerprint(d):
                raise ValueError('SNAPSHOT_INDEX_BINDING')
            documents.append(d)
        return repo,name,selected,documents,manifest
    except BaseException:
        repo.db.close(); raise


def prepare(notebook,task,folder,arm='candidate',sources='all'):
    task=validate_task(task); folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    repo,name,selected,documents,manifest=load(notebook,sources)
    counter=None
    try:
        # Existing opt-in lexical mode, identical retrieval for both packing arms.
        # No new query or corpus embeddings and no persisted index writes.
        search=CandidateSearch(Search(repo,None,lexical_only=True),LexicalBlockRanker(),documents)
        result=search.query(name,selected,AnswerRequest(task['goal']))
        handles=build_reliable_handles(documents,result['hits'])
        counter=TokenCounter(); kept,body,audit=pack(task,handles,arm,counter)
        pack_value=evidence_pack(task,documents,kept,manifest.get('source_revisions'))
        write(folder/'evidence-pack.json',pack_value);write(folder/'payload.json',body)
        write(folder/'retrieval.json',dict(audit=search.audit,handles=handles))
        write(folder/'packing.json',audit)
        write(folder/'input.json',dict(notebook=str(Path(notebook).resolve()),sources=sources,
              task=task,arm=arm,pack_sha256=digest(pack_value),payload_sha256=digest(body),
              tokenizer=counter.metadata,method='same BM25 candidate retrieval; current pack_ranked vs explicit-facet ordering'))
    finally:
        if counter:counter.close()
        repo.db.close()



def bound_workflow(documents, pack_value, native):
    """Dispatch a saved pack to its own content contract, including edits."""
    from .units import POLICY, identity
    if pack_value.get('configuration') == POLICY:
        from .unit_composition import ComposedWorkflow
        from .unit_markdown import readable
        return ComposedWorkflow(documents, pack_value, native), readable
    return Workflow(documents, pack_value, native), render_markdown


def plan(folder, review, output):
    """Create a new planned preparation; retain the original folder verbatim."""
    from .planning import attach, payload
    folder=Path(folder); output=Path(output)
    inputs=json.loads((folder/'input.json').read_bytes())
    pack_value=json.loads((folder/'evidence-pack.json').read_bytes())
    repo,_,_,documents,_=load(inputs['notebook'],inputs['sources'])
    try:
        value=attach(pack_value,review['items'],reviewer=review['reviewer'])
        bound_workflow(documents,value,None)  # validate against actual snapshots
        body=payload(value)
        output.mkdir(parents=True,exist_ok=False)
        write(output/'evidence-pack.json',value);write(output/'payload.json',body)
        write(output/'input.json',dict(inputs,pack_sha256=digest(value),payload_sha256=digest(body),
            plan_origin=str(folder.resolve()),review_sha256=digest(review)))
    finally:repo.db.close()


def generate(folder,ledger):
    folder=Path(folder); input_value=json.loads((folder/'input.json').read_bytes())
    pack_value=json.loads((folder/'evidence-pack.json').read_bytes()); body=json.loads((folder/'payload.json').read_bytes())
    if digest(pack_value)!=input_value['pack_sha256'] or digest(body)!=input_value['payload_sha256']:
        raise ValueError('PREPARED_INPUT_BINDING')
    repo,_,_,documents,_=load(input_value['notebook'],input_value['sources'])
    calls=Calls(ledger);native=None;start=time.time()
    try:
        raw=Generator(calls).generate(body);write(folder/'raw.json',raw)
        if raw.get('done') is not True or raw.get('done_reason')!='stop' or raw.get('thinking'):
            raise ValueError('GENERATION_INCOMPLETE')
        draft=json.loads(raw['response']);Draft202012Validator(body['format']).validate(draft)
        write(folder/'draft.json',draft)
        from .core import verifier_identity
        native=Native(calls,verifier_identity());flow,renderer=bound_workflow(documents,pack_value,native)
        version=flow.build(draft);path=save_version(folder/'versions',version)
        write(folder/'result.json',version);(folder/'storyboard-v1.md').write_text(renderer(version))
        write(folder/'run.json',dict(complete=True,version_path=str(path),seconds=time.time()-start))
    except BaseException as exc:
        write(folder/'run.json',dict(complete=False,error=repr(exc),seconds=time.time()-start));raise
    finally:
        if native:native.close()
        repo.db.close()


def edit(folder,parent,operations,ledger,output,*,phase='experiments'):
    folder=Path(folder)
    from .units import POLICY, style_version
    if parent.get('configuration')==POLICY and all(op['op']=='style' for op in operations):
        from .unit_markdown import readable
        result=style_version(parent,operations)
        save_version(folder/'versions',result);write(output,result)
        Path(output).with_suffix('.md').write_text(readable(result));return result
    inputs=json.loads((folder/'input.json').read_bytes())
    pack_value=json.loads((folder/'evidence-pack.json').read_bytes())
    body={k:v for k,v in parent.items() if k!='version'}
    if digest(body)!=parent['version']:raise ValueError('PARENT_VERSION_INTEGRITY')
    repo,_,_,documents,_=load(inputs['notebook'],inputs['sources']);native=None
    try:
        from .core import verifier_identity
        native=Native(Calls(ledger,phase=phase),verifier_identity())
        flow,renderer=bound_workflow(documents,pack_value,native)
        result=flow.edit(parent,operations)
        save_version(folder/'versions',result);write(output,result)
        Path(output).with_suffix('.md').write_text(renderer(result));return result
    finally:
        if native:native.close()
        repo.db.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    prep=s.add_parser('prepare');prep.add_argument('--notebook',required=True);prep.add_argument('--task',required=True)
    prep.add_argument('--out',required=True);prep.add_argument('--arm',choices=['current','candidate'],default='candidate');prep.add_argument('--sources',default='all')
    run=s.add_parser('generate');run.add_argument('--folder',required=True);run.add_argument('--ledger',required=True)
    pl=s.add_parser('plan');pl.add_argument('--folder',required=True);pl.add_argument('--review',required=True);pl.add_argument('--out',required=True)
    e=s.add_parser('edit');e.add_argument('--folder',required=True);e.add_argument('--ledger')
    e.add_argument('--phase',choices=['experiments','validation'],default='experiments');e.add_argument('--parent',required=True);e.add_argument('--operations',required=True);e.add_argument('--out',required=True)
    a=p.parse_args()
    if a.command=='prepare':prepare(a.notebook,json.loads(Path(a.task).read_bytes()),a.out,a.arm,a.sources)
    elif a.command=='plan':plan(a.folder,json.loads(Path(a.review).read_bytes()),a.out)
    elif a.command=='edit':
        parent=json.loads(Path(a.parent).read_bytes());operations=json.loads(Path(a.operations).read_bytes())
        from .units import POLICY
        if parent.get('configuration')==POLICY and all(op['op']=='style' for op in operations):
            edit(a.folder,parent,operations,None,a.out,phase=a.phase)
        else:
            if not a.ledger:p.error('--ledger is required for factual edits')
            with lock(Path(a.ledger)/'run.lock'):
                edit(a.folder,parent,operations,a.ledger,a.out,phase=a.phase)
    else:
        # One writer per phase ledger, generation and native calls sequential.
        with lock(Path(a.ledger)/'run.lock'):
            generate(a.folder,a.ledger)
