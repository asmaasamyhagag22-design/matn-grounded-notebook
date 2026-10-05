// Offline unit test of our JavaScript with inert DOM objects; no browser, network or real GT writes.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
class Element {
  constructor(tag) { this.tag=tag; this.style={}; this.children=[]; this.events={}; this.value=''; this.checked=false; this.textContent=''; this.classList={add:()=>{}}; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children=children; }
  addEventListener(type, handler) { this.events[type]=handler; }
  querySelector(selector) { return this.children.find(c=>c.className===selector.slice(1)); }
}
const ids={};
const document={getElementById:id=>ids[id]??(ids[id]=new Element(id)), createElement:tag=>new Element(tag),body:{scrollHeight:0}};
const fixture=[{key:'synthetic_ui_fixture_p0000',template:{doc_key:'synthetic_ui_fixture',page_index:0,status:'template',numbers:[]},image:'fake.png',cropbox:[0,0,100,100],proposals:[{reader1:'20',reader2:'28',layer:'20 | 2020',bbox:[10,10,20,20],context:'test fixture',chosen:null,flagged:true}]}];
const html=fs.readFileSync(require('node:path').join(__dirname,'review_ui.html'),'utf8');
const script=html.split('<script>')[1].split('</script>')[0].replace('__REVIEW_DATA__',JSON.stringify(fixture));
const context=vm.createContext({document,window:{scrollTo:()=>{}},localStorage:{getItem:()=>null,setItem:()=>{}},setTimeout,Blob,URL,console});
vm.runInContext(script,context);
assert.match(ids.progress.textContent,/0 \/ 1/);
ids.save.onclick().then(async()=>{
  assert.match(ids.status.textContent,/Review every candidate/);
  const card=ids.items.children[0]; const picks=card.children.find(x=>x.className==='pick');
  assert.ok(picks.children.some(x=>x.textContent==='Pick OCR layer 20'));
  assert.ok(picks.children.some(x=>x.textContent==='Pick OCR layer 2020'));
  assert.ok(!picks.children.some(x=>x.textContent==='Pick OCR layer'));
  picks.children.find(x=>x.textContent==='Pick reader 2').onclick();
  assert.match(ids.progress.textContent,/1 \/ 1/);
  document.getElementById('owner').value='Synthetic test reviewer'; ids.complete.checked=true;
  const result=vm.runInContext('result()',context);
  assert.equal(result.numbers[0].value_as_printed,'28');
  assert.equal(result.verified_scope,'numbers only');
  assert.equal(vm.runInContext('pages[0].template.numbers.length',context),0);
  let saved=null;
  context.window.showDirectoryPicker=async()=>({name:'inert test folder',getFileHandle:async name=>({getFile:async()=>({text:async()=>JSON.stringify(fixture[0].template)}),createWritable:async()=>({write:async value=>{saved=value},close:async()=>{}})})});
  await ids.folder.onclick(); await ids.save.onclick();
  assert.equal(JSON.parse(saved).numbers[0].value_as_printed,'28');
  assert.match(ids.status.textContent,/Saved synthetic_ui_fixture_p0000.json/);
  saved=null;
  context.window.showDirectoryPicker=async()=>({name:'wrong inert folder',getFileHandle:async()=>({getFile:async()=>({text:async()=>JSON.stringify({doc_key:'wrong',page_index:0})}),createWritable:async()=>{throw Error('Must never write a mismatched template')}})});
  await ids.folder.onclick();await ids.save.onclick();assert.equal(saved,null);assert.match(ids.status.textContent,/Wrong folder\/file identity/);
  console.log('PASS: no preselected answers; incomplete-save refusal; pick/confirm; signed save; template preserved. No actual GT file written.');
}).catch(error=>{console.error(error);process.exitCode=1});
