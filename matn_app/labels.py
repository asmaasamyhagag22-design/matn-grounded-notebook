"""Owner labels bound to exact evidence; AI judgments stay hidden until a decision."""
import fcntl
import hashlib
import json
from pathlib import Path
import time
from .runtime import DATA_ROOT
from .store import read,write

DECISIONS=('Correct','Wrong','Borderline','Skip')
GROUP_ORDER={'disputed-holdouts':0,'answer-development':1,'historical-NQ':2,'new-holdouts':3,'answer-acceptance':4,'answers-v2':5,'answers-v2-blocked':6}


def binding(item):
    return hashlib.sha256(json.dumps({k:item.get(k) for k in ('id','text','question','span','spans','context')},sort_keys=True).encode()).hexdigest()


class LabelStore:
    def __init__(self,root=None):self.root=Path(root) if root else DATA_ROOT/'labels'
    def items(self):return read(self.root/'queue.json',[])
    def labels(self):return read(self.root/'owner-labels.json',dict(version=1,labels={},history=[]))
    def merge(self,items):
        self.root.mkdir(parents=True,exist_ok=True)
        with (self.root/'labels.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            old=self.items();by={i['id']:i for i in old}
            for item in items:
                if item['id'] in by and binding(item)!=binding(by[item['id']]):raise ValueError('LABEL_ITEM_CHANGED:'+item['id'])
                by[item['id']]=item
            result=sorted(by.values(),key=lambda i:(GROUP_ORDER.get(i['group'],99),i['id']))
            write(self.root/'queue.json',result)
        self.page();return self.summary()
    def page(self):
        source=Path(__file__).with_name('static')/'labels.html'
        self.root.mkdir(parents=True,exist_ok=True)
        target=self.root/'index.html'
        if not target.exists() or target.read_bytes()!=source.read_bytes():target.write_bytes(source.read_bytes())
        return target
    def public(self):
        labels=self.labels()['labels'];result=[]
        for item in self.items():
            row={k:item.get(k) for k in ('id','group','text','question','source_title','source_type','span','spans','context')}
            label=labels.get(item['id'])
            if label and label['binding']!=binding(item):raise ValueError('STALE_OWNER_LABEL')
            row['owner_label']=label
            if label and label['decision']!='Skip':row['ai_verdict']=item.get('ai_verdict')
            result.append(row)
        return dict(items=result,summary=self.summary())
    def submit(self,key,decision,note=''):
        if decision not in DECISIONS:raise ValueError('Unknown label decision')
        if not isinstance(note,str) or len(note)>4000:raise ValueError('Note too long')
        self.root.mkdir(parents=True,exist_ok=True)
        with (self.root/'labels.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            item=next((i for i in self.items() if i['id']==key),None)
            if item is None:raise ValueError('Unknown label item')
            value=self.labels();label=dict(decision=decision,note=note,at=time.time(),binding=binding(item),reviewer_type='owner')
            value['labels'][key]=label;value['history'].append(dict(id=key,**label));write(self.root/'owner-labels.json',value)
        summary=self.summary();write(self.root/'derived-review.json',summary)
        return dict(saved=True,summary=summary,owner_label=label,ai_verdict=item.get('ai_verdict') if decision!='Skip' else None)
    def summary(self):
        items=self.items();labels=self.labels()['labels'];groups={};false_blocks=correct=0
        for item in items:
            row=groups.setdefault(item['group'],dict(total=0,owner_labelled=0,correct=0,wrong=0,borderline=0,skipped=0,pending=0,AI_review=0))
            row['total']+=1;label=labels.get(item['id'])
            if label and label['binding']!=binding(item):raise ValueError('STALE_OWNER_LABEL')
            if label and label['decision']!='Skip':
                row['owner_labelled']+=1;row[label['decision'].lower()]+=1
                if item['group']=='answer-development' and label['decision']=='Correct':
                    correct+=1;false_blocks+=item.get('receipt',{}).get('status')!='verified'
            else:
                row['pending']+=1;row['AI_review']+=1
                if label:row['skipped']+=1
        # Labels change the quality judgment for their exact units; other gates
        # stay fixed. Never convert a subset or borderlines into a full PASS.
        for name,row in groups.items():
            row['owner_verdict']='FAIL' if row['wrong'] else 'PENDING' if row['pending'] or row['borderline'] else 'PASS'
            row['scope']='Labelled units only; full acceptance also requires its frozen coverage/timing/bench gates.'
        verdicts={}
        for key,base in read(self.root/'verdict-bases.json',{}).items():
            selected=[i for i in items if i['group']==base['group']];errors=borderline=unknown=owner_count=0
            for item in selected:
                label=labels.get(item['id']);ai=item.get('ai_verdict') or {}
                if label and label['decision']!='Skip':
                    owner_count+=1;errors+=label['decision']=='Wrong';borderline+=label['decision']=='Borderline'
                elif 'error' in ai:
                    errors+=bool(ai['error']);borderline+=bool(ai.get('borderline'))
                else:unknown+=1
            fixed=base.get('fixed_gates_pass')
            # Each pre-registered rule states how borderline counts; older
            # rules count it against PASS, answers v2 reports it separately.
            counted=borderline if base.get('borderline_is_error',True) else 0
            direct=None
            if base.get('direct_answers'):
                # Owner label on an answer's first sentence decides whether it
                # answers directly; otherwise the saved AI judgment stands.
                rule=base['direct_answers'];direct=0
                for qid,ai_direct in rule['ai_direct'].items():
                    label=labels.get(rule['first_sentence'].get(qid) or '')
                    if label and label['decision'] in ('Correct','Wrong'):direct+=label['decision']=='Correct'
                    else:direct+=bool(ai_direct)
                if direct<rule['minimum']:fixed=False
            status='FAIL' if fixed is False or errors or counted else 'PENDING' if fixed is None or unknown or not selected else 'PASS'
            verdicts[key]=dict(status=status,errors=errors,borderline=borderline,unreviewed=unknown,direct_answers=direct,
                borderline_is_error=base.get('borderline_is_error',True),
                owner_labelled=owner_count,AI_review=len(selected)-owner_count,fixed_gates_pass=fixed,
                review='Owner overrides apply only to their exact bound units; remaining judgments are AI review.')
        return dict(total=len(items),owner_labelled=sum(r['owner_labelled'] for r in groups.values()),
            pending=sum(r['pending'] for r in groups.values()),groups=groups,verdicts=verdicts,
            false_blocks=dict(owner_correct=correct,rejected_owner_correct=false_blocks,rate=false_blocks/correct if correct else None),
            review='Owner-labelled decisions and AI review are separate; pending items never inherit owner acceptance.')
