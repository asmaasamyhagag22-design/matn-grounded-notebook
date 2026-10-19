"""V2 local immutable corpora; tracked manifests contain hashes, not source text."""
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path('out/v2')


def sha(value):
    return hashlib.sha256(value if isinstance(value,bytes) else value.encode()).hexdigest()


def save(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n')


def match_labels(claims, labels):
    key=lambda c:(c['question_id'],c['atomic_claim'],c['claim_sha256'])
    by={key(c):c for c in claims}
    if len(by)!=len(claims) or len({key(l) for l in labels})!=len(labels):
        raise ValueError('duplicate identity')
    if set(by)!={key(l) for l in labels}: raise ValueError('unmatched identity')
    for label in labels:
        if by[key(label)]['split']!=label['split']: raise ValueError('split mismatch')
        if label['label'] not in ('supported','unsupported','partial','unclear'): raise ValueError('invalid label')
    return labels


def freeze_realistic(label_path):
    source=Path(label_path); labels=json.loads(source.read_text())
    from .coverage import load_documents
    docs=load_documents(); by={e.block.block_id:e.block.text for d in docs.values() for e in d.elements}
    claims=[]; files={}
    for path in sorted(Path('out/v1/questions').glob('*.json')):
        row=json.loads(path.read_text()); files[str(path)]=sha(path.read_bytes())
        for si,sentence in enumerate(row['sentences'],1):
            for ci,claim in enumerate(sentence['claims'],1):
                refs=[]
                for ref in claim['citations']:
                    text=by.get(ref['block_id'],''); a,z=ref['start'],ref['end']
                    quote=text[a:z] if 0<=a<z<=len(text) else None
                    refs.append({**ref,'declared_quote':quote,'evidence_sha256':sha(quote) if quote is not None else None})
                claims.append(dict(question_id=row['id'],atomic_claim=f'{si}.{ci}',claim_sha256=sha(claim['text']),
                    split=row['split'],text=claim['text'],sentence=sentence['text'],citations=refs))
    match_labels(claims,labels['items'])
    lookup={(l['question_id'],l['atomic_claim']):l for l in labels['items']}
    for c in claims:c['reviewer']=lookup[c['question_id'],c['atomic_claim']]
    assert Counter(c['reviewer']['label'] for c in claims)==Counter(labels['counts'])
    local=ROOT/'realistic-v1.json'; save(local,claims)
    packet=Path('out/v1/realistic-labeling-packet.md')
    manifest=dict(version='realistic-v1',provenance=labels['provenance'],label_rule=labels['label_rule'],
        labels_file_sha256=sha(source.read_bytes()),packet_sha256=sha(packet.read_bytes()),
        reviewer_packet_sha256=labels['packet_sha256'],packet_matches=sha(packet.read_bytes())==labels['packet_sha256'],
        unmatched=[],generation_questions=60,no_claim_questions=labels['no_claim_questions'],counts=labels['counts'],
        counts_by_split=labels['counts_by_split'],local_artifact=str(local),local_sha256=sha(local.read_bytes()),
        original_questions_sha256=files,
        items=[{k:v for k,v in c.items() if k in ('question_id','atomic_claim','claim_sha256','split')}|
               {'label':c['reviewer']['label'],'citation_sha256':sha(json.dumps(c['citations'],sort_keys=True))} for c in claims])
    save('eval/verification/realistic/manifest-v1.json',manifest)
    # Keep label reasons (which may reproduce source text) local.
    save(ROOT/'reviewer-labels.json',labels)
    return manifest


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('labels')
    print(json.dumps(freeze_realistic(parser.parse_args().labels)['counts']))
