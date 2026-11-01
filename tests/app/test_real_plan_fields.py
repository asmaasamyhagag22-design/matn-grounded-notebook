"""Exercise the actual plan-card renderer with a saved real --plan-only result."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest


def test_real_plan_only_output_populates_all_twelve_editor_fields():
    node=os.environ.get('MATN_NODE') or shutil.which('node')
    if not node:pytest.skip('JavaScript runtime required for the plan-renderer regression')
    root=next(p for p in Path(__file__).resolve().parents if (p/"matn_app").is_dir())
    value=json.loads((Path(__file__).with_name('fixtures')/'real_plan_only.json').read_bytes())
    source=(root/'matn_app/static/app.js').read_text()
    start=source.index('function planCard(');end=source.index('\nfunction renderWorking(',start)
    code=r'''
const vm=require('node:vm'), fs=require('node:fs');
const input=JSON.parse(fs.readFileSync(0,'utf8')), nodes=[];
const context={structuredClone,boot:{fake:true},el:(tag,cls,text)=>{const n={tag,children:[],text,append(...children){this.children.push(...children)},setAttribute(k,v){this[k]=v}};nodes.push(n);return n}};
vm.createContext(context);vm.runInContext(input.source,context);
context.planCard(input.item,true);
process.stdout.write(JSON.stringify(nodes.filter(n=>n['aria-label']?.startsWith('Axis ')).map(n=>({label:n['aria-label'],value:n.value,disabled:n.disabled}))));
'''
    result=subprocess.run([node,'-e',code],input=json.dumps(dict(source=source[start:end],item=value)),text=True,capture_output=True,check=True)
    rows=json.loads(result.stdout)
    assert len(rows)==12 and all(row['value'] and not row['disabled'] for row in rows)
    for i,axis in enumerate(value['plan']['facets']):
        assert [r['value'] for r in rows[3*i:3*i+3]]==[axis['label'],axis['success'],' | '.join(axis['searches'])]
