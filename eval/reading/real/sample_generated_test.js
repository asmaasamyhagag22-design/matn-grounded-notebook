// Exercise every frozen item in the actual generated HTML with an inert DOM.
// Display only: no answer is chosen, no browser/network or GT file is touched.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element {
 constructor(){this.value='';this.textContent='';this.children=[];this.disabled=false;this.hidden=false;this.tagName='DIV';}
 append(...xs){this.children.push(...xs);}replaceChildren(...xs){this.children=xs;}
 addEventListener(type,fn){this[type]=fn;}
}
const ids={},document={getElementById:id=>ids[id]??(ids[id]=new Element()),createElement:()=>new Element(),addEventListener(type,fn){this[type]=fn;}};
const html=fs.readFileSync(require('node:path').join(__dirname,'review.html'),'utf8');
for(const match of html.matchAll(/id="([^"]+)"/g))document.getElementById(match[1]);
const context=vm.createContext({document,window:{},console,Date,Map,Set,JSON});
vm.runInContext(html.split('<script>')[1].split('</script>')[0],context);
const count=vm.runInContext('items.length',context);
assert.ok(count>=180);assert.match(ids.progress.textContent,new RegExp('0 / '+count));
assert.match(ids.status.textContent,/choose eval\/reading\/real\/gt/);
for(let i=0;i<count;i++){
 vm.runInContext('position='+i+';show()',context);
 assert.equal(ids.card.hidden,false);
 assert.match(ids.r1.textContent,/^1 · Reader 1: /);
 for(const name of ['crop','contextCrop']){
  assert.ok(ids[name].src.startsWith('data:image/png;base64,'));
  const bytes=Buffer.from(ids[name].src.split(',')[1],'base64');
  assert.deepEqual([...bytes.subarray(0,8)],[137,80,78,71,13,10,26,10]);
 }
 assert.equal(vm.runInContext('Object.keys(answers).length',context),0);
}
console.log('PASS: all '+count+' actual items render with embedded PNGs; no GT answer chosen or written.');
