"""The real UI renderer distinguishes an older selection and ignores stale GETs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest


def node_run(script,source):
    node=os.environ.get('MATN_NODE') or shutil.which('node')
    if not node:pytest.skip('JavaScript runtime required')
    result=subprocess.run([node,'-e',script],input=json.dumps(dict(source=source)),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_panel_follows_new_edit_and_explicitly_labels_a_selected_older_version():
    source=Path('matn_app/static/app.js').read_text();source=source[source.index('function renderDeckPanel('):source.index('function openCitation(')]
    script=r'''
const vm=require('node:vm'),fs=require('node:fs'),input=JSON.parse(fs.readFileSync(0,'utf8')),ids={};
const el=(tag,cls,text)=>({tag,cls,text,children:[],append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},setAttribute(k,v){this[k]=v}});
const ctx={el,$:id=>ids[id]??(ids[id]=el('div')),boot:{templates:[]},selectedTemplate:'ministry_light',deckCard:(d,p)=>({displayedVersion:d.version}),act(){}};
vm.createContext(ctx);vm.runInContext(input.source,ctx);
const c={active_deck:1,decks:[1,2,3].map(version=>({version,template:'ministry_light'})),catalogs:['public'],evidence:{citations:[{}]}};
ctx.renderDeckPanel(c);const older=JSON.parse(JSON.stringify(ids['#deck-content']));
c.active_deck=3;ctx.renderDeckPanel(c);process.stdout.write(JSON.stringify({older,newest:ids['#deck-content']}));
'''
    value=node_run(script,source)
    assert 'Viewing v1 (latest v3)' in json.dumps(value['older'])
    assert any(c.get('displayedVersion')==1 for c in value['older']['children'])
    assert any(c.get('displayedVersion')==3 for c in value['newest']['children'])
    assert 'Viewing v1' not in json.dumps(value['newest'])


def test_out_of_order_refresh_cannot_replace_the_newer_deck_state():
    source=Path('matn_app/static/app.js').read_text();source=source[source.index('async function refresh('):source.index('function textWithCitations(')]
    script=r'''
const vm=require('node:vm'),fs=require('node:fs'),input=JSON.parse(fs.readFileSync(0,'utf8')),pending=[],rendered=[];
const ctx={current:'c',state:null,refreshSequence:0,screen:{scrollHeight:100,scrollTop:0,clientHeight:100},api:()=>new Promise(r=>pending.push(r)),renderConversation:c=>rendered.push(c.active_deck),toast:e=>{throw Error(e)}};
vm.createContext(ctx);vm.runInContext(input.source,ctx);
(async()=>{const first=ctx.refresh(),second=ctx.refresh();pending[1]({id:'c',active_deck:3,updated_at:3});await second;pending[0]({id:'c',active_deck:1,updated_at:1});await first;process.stdout.write(JSON.stringify({rendered,state:ctx.state}));})().catch(e=>{console.error(e);process.exit(1)});
'''
    value=node_run(script,source)
    assert value['rendered']==[3] and value['state']['active_deck']==3
