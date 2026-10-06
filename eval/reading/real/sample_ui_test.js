// Inert DOM and synthetic files only: autosave, resume, keyboard and disk failure.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element {
 constructor(){this.value='';this.textContent='';this.children=[];this.disabled=false;this.hidden=false;this.tagName='DIV';}
 append(...xs){this.children.push(...xs);} replaceChildren(...xs){this.children=xs;}
 addEventListener(type, fn){this[type]=fn;}
}
const ids={},document={getElementById:id=>ids[id]??(ids[id]=new Element()),createElement:()=>new Element(),addEventListener(type,fn){this[type]=fn;}};
const items=[0,1,2].map(i=>({id:'initial:fixture_p0000:t'+i,page:'fixture_p0000',reader1:'20',reader2:'28',layer:i===0?'20 | 2020':'',bbox:[1,2,3,4],context:'Year 20',crop:'crop.png',context_crop:'line.png'}));
const fixture=[{batch:'initial',manifest_sha256:'test-digest',items}];
let disk={doc_key:'fixture',page_index:0,status:'template',numbers:[],blocks:['preserve'],tables:['preserve']},writes=0,fail=false;
const handle={getFile:async()=>({text:async()=>JSON.stringify(disk)}),createWritable:async()=>({write:async s=>{if(fail)throw Error('Disk full');disk=JSON.parse(s);writes++;},close:async()=>{}})};
const context=vm.createContext({document,window:{showDirectoryPicker:async()=>({getFileHandle:async()=>handle})},console,Date,Map,Set,JSON});
const html=fs.readFileSync(require('node:path').join(__dirname,'sample_ui.html'),'utf8');
for(const match of html.matchAll(/id="([^"]+)"/g))document.getElementById(match[1]);
vm.runInContext(html.split('<script>')[1].split('</script>')[0].replace('__SAMPLE_DATA__',JSON.stringify(fixture)),context);
async function key(key){await document.keydown({key,target:{tagName:'BODY'},preventDefault(){}});}
(async()=>{
 assert.match(ids.progress.textContent,/0 \/ 3/);
 await key('1');assert.equal(writes,0);assert.match(ids.status.textContent,/folder/);
 ids.owner.value='Synthetic owner';await ids.folder.onclick();
 assert.equal(vm.runInContext('Object.keys(answers).length',context),0);
 assert.equal(ids.layerPick.children.length,2); // separate readings; key 3 opens choice, never guesses
 assert.match(ids.r3.textContent,/20 \| 2020/); // owner sees the suggestion before choosing it
 await key('3');assert.equal(writes,0);assert.equal(ids.layerPick.hidden,false);
 await key('1');assert.equal(writes,1);assert.equal(vm.runInContext('position',context),1);
 assert.equal(disk.status,'template');assert.deepEqual(disk.numbers,[]);assert.deepEqual(disk.blocks,['preserve']);
 assert.equal(disk.sample_reviews.initial.answers[items[0].id].value_as_printed,'20');
 await key('3');assert.equal(writes,1); // no embedded reading
 await key('T');assert.equal(ids.typedBox.hidden,false);
 ids.typed.value='21';await ids.typedSave.onclick();assert.equal(writes,2);
 await key('Backspace');assert.equal(vm.runInContext('position',context),1);
 await key('2');assert.equal(writes,3);assert.equal(disk.sample_reviews.initial.answers[items[1].id].value_as_printed,'28');
 fail=true;await key('X');assert.equal(vm.runInContext('position',context),2);assert.equal(writes,3);assert.match(ids.status.textContent,/Disk full/);
 fail=false;await key('X');assert.equal(writes,4);assert.match(ids.progress.textContent,/3 \/ 3/);
 assert.equal(disk.sample_reviews.initial.status,'sampled GT complete');
 assert.equal(disk.sample_reviews.initial.answers[items[2].id].kind,'illegible');
 // Reopening the folder loads the GT file and resumes, with no browser draft overriding disk.
 await ids.folder.onclick();assert.equal(vm.runInContext('position',context),3);
 await key('Backspace');assert.equal(vm.runInContext('position',context),2);
 ids.typed.tagName='INPUT';await document.keydown({key:'1',target:ids.typed,preventDefault(){throw Error('typing intercepted');}});assert.equal(writes,4);
 disk.sample_reviews.initial.manifest_sha256='wrong';await ids.folder.onclick();assert.match(ids.status.textContent,/manifest/);
 await key('1');assert.equal(writes,4);
 console.log('Sample UI: autosave/resume/keyboard/blinding and failure tests passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
