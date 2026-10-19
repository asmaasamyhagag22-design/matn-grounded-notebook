"""Offline derivative diagnostics; never call models or rewrite generation checkpoints."""
from __future__ import annotations
import argparse
import copy
from collections import Counter
import hashlib
import json
from pathlib import Path

from matn_rag.contracts import canonical
from matn_verification.contracts import NORMALIZER_VERSION, VERIFIER_VERSION
from matn_verification.rules import fingerprint, verify
from .coverage import load_documents
from .realistic import render_packet, retrieved_spans, save


def replay_row(row, spans, documents):
    result=copy.deepcopy(row)
    if row['status']!='completed':return result
    fps={d.doc_id:fingerprint(d) for d in documents}
    by={e.block.block_id:e.block.text for d in documents for e in d.elements}
    result['diagnostics']=[]
    for sentence in row['sentences']:
        req={'sentence':sentence['text'],'claims':sentence['claims'],'selected_doc_ids':list(fps),
             'fingerprints':fps,'retrieved_spans':[{k:s[k] for k in ('block_id','start','end')} for s in spans]}
        receipt=verify(documents,req).model_dump(mode='json')
        resolved=[];allowed=True
        for claim in sentence['claims']:
            for c in claim['citations']:
                allowed &= any(c['block_id']==s['block_id'] and s['start']<=c['start']<c['end']<=s['end'] for s in spans)
                text=by.get(c['block_id'])
                if text is not None and 0<=c['start']<c['end']<=len(text):
                    resolved.append({**c,'quote':text[c['start']:c['end']]})
        result['diagnostics'].append({'receipt':receipt,'resolved':resolved,'citations_within_retrieved_spans':bool(allowed)})
    return result


def run(root=Path('out/v1')):
    docs=tuple(load_documents().values())
    identity=json.loads((root/'generation-settings.json').read_text())
    assert {d.doc_id:fingerprint(d) for d in docs}==identity['snapshot_fingerprints'],'SNAPSHOT_MISMATCH'
    original={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('questions','raw','inputs') for p in sorted((root/folder).glob('*.json'))}
    questions=json.loads(Path('eval/rag/frozen/questions.json').read_text())['items']
    assert hashlib.sha256(Path('eval/rag/frozen/questions.json').read_bytes()).hexdigest()==identity['questions_sha256']
    rows=[]
    for question in questions:
        row=json.loads((root/'questions'/f"{question['id']}.json").read_text())
        inp=json.loads((root/'inputs'/f"{question['id']}.json").read_text())
        binding=hashlib.sha256(canonical({'identity':identity,'question_id':row['id'],'payload':inp['payload'],'retrieval':inp['retrieval']})).hexdigest()
        assert row['binding']==binding,'CHECKPOINT_BINDING_MISMATCH'
        spans=retrieved_spans(inp['retrieval']['hits'],docs)
        derived=replay_row(row,spans,docs)
        save(root/'replayed-questions'/f"{row['id']}.json",derived);rows.append(derived)
    packet=root/'realistic-labeling-packet.md'
    archive=root/'realistic-labeling-packet.generation-v1.md'
    if not archive.exists():archive.write_bytes(packet.read_bytes())
    packet.write_text(render_packet(rows)+'\nDiagnostics replay: '+VERIFIER_VERSION+' / '+NORMALIZER_VERSION+'; original generation checkpoints unchanged.\n')
    for path,sha in original.items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha,'ORIGINAL_CHANGED'
    receipts=[d['receipt'] for r in rows for d in r.get('diagnostics',[])]
    per_layer=Counter((c['layer'],c['verdict']) for r in receipts for c in r['checks'] if c['target']=='sentence')
    summary={'state':'UNLABELED / NOT FROZEN','questions':len(rows),'generation_statuses':dict(Counter(r['status'] for r in rows)),
             'sentences':sum(len(r['sentences']) for r in rows),'atomic_claims':sum(len(s['claims']) for r in rows for s in r['sentences']),
             'empty_completed_answers':sum(r['status']=='completed' and not r['sentences'] for r in rows),
             'receipt_statuses':dict(Counter(r['status'] for r in receipts)),
             'sentence_layer_verdicts':{layer:dict((v,n) for (l,v),n in per_layer.items() if l==layer) for layer in sorted({l for l,v in per_layer})},
             'sentence_reasons':dict(Counter(reason for r in receipts for c in r['checks'] if c['target']=='sentence' for reason in c['reasons'])),
             'verifier_version':VERIFIER_VERSION,'normalizer_version':NORMALIZER_VERSION,
             'diagnostic_rules_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in map(Path,identity['rules_sha256'])},
             'generation_identity_sha256':hashlib.sha256(canonical(identity)).hexdigest(),
             'original_generation_rules_sha256':identity['rules_sha256'],'original_file_sha256':original,
             'models_called':0,'original_files_unchanged':True,
             'deferred':[{'id':r['id'],'reason':r.get('reason')} for r in rows if r['status']!='completed']}
    save(root/'replay-summary.json',summary)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path('out/v1'))
    summary=run(parser.parse_args().root)
    print(json.dumps({k:v for k,v in summary.items() if k!='original_file_sha256'},indent=2))
