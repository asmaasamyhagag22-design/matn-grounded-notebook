"""Final slide interpretation over already source-bound units; no new facts."""
from copy import deepcopy
import hashlib
from pathlib import Path
from matn_verification.contracts import Evidence
from .core import digest
from .units import UnitWorkflow

POLICY='checked-unit-slide-composition-v1'


class ComposedWorkflow(UnitWorkflow):
    def build(self,draft,*,parent=None,style=None,changed_atoms=()):
        result=super().build(draft,parent=parent,style=style,changed_atoms=changed_atoms)
        policy=dict(version=POLICY,code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        prior={(s.get('composition') or {}).get('binding'):s['composition'] for s in (parent or {}).get('slides',[]) if (s.get('composition') or {}).get('binding')}
        used=set()
        for slide in result['slides']:
            if not slide['displayed']:
                slide['composition']=dict(status='not_run',reason='atomic_support_or_context_missing');continue
            parts=[];citations=[]
            for checked in slide['checks']:
                display=checked['display']
                parts.extend(c['quote'].strip() for c in display['context'])
                parts.append(display['text'])
                for c in [ref for ctx in display['context'] for ref in ctx.get('citations',[ctx])]+[display['support']]+display.get('alias_definitions',[])+display.get('context_alias_definitions',[]):
                    if c not in citations:citations.append(c)
            visible=' '.join(parts)
            binding=digest(dict(visible=visible,evidence=citations,policy=policy,identity=self.identity,sources=self.pack['sources'],atoms=[c['binding'] for c in slide['checks']]))
            if binding in prior:
                composition=deepcopy(prior[binding]);used.add(binding)
            else:
                evidence=tuple(Evidence.model_validate_json(__import__('json').dumps(c)) for c in citations)
                check=self.native(visible,evidence,'visible-slide')
                composition=dict(binding=binding,visible=visible,evidence=citations,check=check.model_dump(mode='json'),status='verified' if check.verdict=='pass' else 'abstained',reused=False)
            slide['composition']=composition;slide['displayed']=composition['status']=='verified'
        result['composition_policy']=policy
        result['reused_composition_receipts']=sorted(used)
        result['invalidated_composition_receipts']=sorted(set(prior)-used)
        result.pop('version');result['version']=digest(result);return result
