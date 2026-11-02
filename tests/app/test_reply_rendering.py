"""Exercise the actual chat renderer, including saved legacy copy responses."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest


def test_thread_renders_generated_prose_and_never_legacy_source_passages():
    node=os.environ.get('MATN_NODE') or shutil.which('node')
    if not node:pytest.skip('JavaScript runtime required')
    source=Path('matn_app/static/app.js').read_text()
    source=source[source.index('function renderConversation('):source.index('function clarificationCard(')]
    script=r'''
const vm=require('node:vm'),fs=require('node:fs'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const all=[],ids={};
function element(tag,cls,text){const n={tag,text,children:[],append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},closest(){return null}};all.push(n);return n;}
const ctx={document:{createTextNode:x=>x,activeElement:{closest(){return null}}},el:element,$:id=>ids[id]??(ids[id]=element('div')),
textWithCitations:(text)=>text,renderWorking(){},renderEvidence(){},renderDeckPanel(){}};
vm.createContext(ctx);vm.runInContext(input.source,ctx);
ctx.renderConversation({title:'Test',messages:[
{role:'assistant',kind:'answer',text:'RAW_PASSAGE_SHOULD_NOT_RENDER',result:{answer_kind:'verified_source_copies'}},
{role:'assistant',kind:'answer',text:'Written response in my own words.',result:{answer_kind:'generated_answer'}}]});
process.stdout.write(JSON.stringify(all));
'''
    result=subprocess.run([node,'-e',script],input=json.dumps(dict(source=source)),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert 'RAW_PASSAGE_SHOULD_NOT_RENDER' not in result.stdout
    assert 'Written response in my own words.' in result.stdout
