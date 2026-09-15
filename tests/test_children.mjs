import test from 'node:test';
import assert from 'node:assert/strict';
import {validateProject, insertBlankStep, setParent, descendantIds, ancestorIds, childrenOf, taskSize, addDependency, removeTask, autoLayout, moveBranch, toYaml, stepOutline, setStepNumber} from '../web/model.mjs';
const fresh=()=>validateProject({schema_version:1,project:{name:'Test'},tasks:[{id:'a',title:'A'},{id:'b',title:'B'},{id:'c',title:'C',parent_id:'a'},{id:'d',title:'D',parent_id:'c'}]});
test('children and descendants have independent stable IDs',()=>{const p=fresh();assert.deepEqual(childrenOf(p,'a').map(t=>t.id),['c']);assert.deepEqual([...descendantIds(p,'a')],['c','d']);assert.deepEqual(ancestorIds(p,'d'),['c','a']);});
test('parenthood creates no dependency or status rollup',()=>{const p=fresh();for(const t of p.tasks)assert.deepEqual(t.depends_on,[]);p.tasks[3].status='done';assert.equal(validateProject(p).tasks[0].status,'todo');});
test('add child inserts a saveable blank ordinary task',()=>{const p=fresh(),r=insertBlankStep(p,{x:13.3,y:55.7},null,'a');assert.equal(r.document.tasks.at(-1).parent_id,'a');assert.deepEqual(r.document.tasks.at(-1).depends_on,[]);assert.equal(r.document.tasks.at(-1).title,'Untitled step');assert.deepEqual(r.document.layout.positions[r.id],{x:13,y:56});assert.equal(p.tasks.length,4);});
test('add root is independent; add dependent creates no parent',()=>{const p=fresh();assert.equal(insertBlankStep(p,{x:0,y:0}).document.tasks.at(-1).parent_id,undefined);const r=insertBlankStep(p,{x:0,y:0},'a');assert.equal(r.document.tasks.at(-1).parent_id,undefined);assert.deepEqual(r.document.tasks.at(-1).depends_on,['a']);});
test('unknown parent rejected without mutation',()=>{const p=fresh();assert.throws(()=>setParent(p,'c','missing'),/parent/);assert.equal(p.tasks[2].parent_id,'a');});
test('self and descendant parents rejected',()=>{for(const parent of ['a','c','d'])assert.throws(()=>setParent(fresh(),'a',parent),/cycle/);});
test('invalid parent types rejected',()=>{for(const v of ['',[],{},17,true]){const p=fresh();p.tasks[1].parent_id=v;assert.throws(()=>validateProject(p),/parent/);}});
test('reparent preserves dependency edges and metadata',()=>{let p=fresh();p.tasks[2].notes='Keep';p=addDependency(p,'b','d');const q=setParent(p,'c','b');assert.equal(q.tasks[2].parent_id,'b');assert.equal(q.tasks[2].notes,'Keep');assert.deepEqual(q.tasks[3].depends_on,['b']);assert.deepEqual(ancestorIds(q,'d'),['c','b']);});
test('promoting to root retains descendants',()=>{const p=setParent(fresh(),'c');assert.equal(p.tasks[2].parent_id,undefined);assert.equal(p.tasks[3].parent_id,'c');});
test('child dependencies can cross hierarchy branches',()=>{const p=addDependency(fresh(),'d','b');assert.deepEqual(p.tasks[1].depends_on,['d']);assert.equal(p.tasks[3].parent_id,'c');});
test('dependency and parent graphs validated separately',()=>{const p=addDependency(fresh(),'d','a');assert.deepEqual(p.tasks[0].depends_on,['d']);assert.throws(()=>addDependency(p,'a','d'),/cycle/);});
test('children have one compact readable size, independent of depth',()=>{const p=fresh();assert.ok(taskSize(p.tasks[2]).width<taskSize(p.tasks[0]).width);assert.deepEqual(taskSize(p.tasks[2]),taskSize(p.tasks[3]));assert.equal(taskSize(p.tasks[3]).height,136);});
test('deep parentage is flat data, not a fixed two-level structure',()=>{let p=fresh();for(let i=0;i<80;i++){const r=insertBlankStep(p,{x:i,y:i},null,p.tasks.at(-1).id);p=r.document;}assert.equal(ancestorIds(p,p.tasks.at(-1).id).length,82);assert.equal(p.tasks.length,84);});
test('deleting root promotes direct children, preserves grandchildren',()=>{const p=removeTask(fresh(),'a');assert.equal(p.tasks.find(t=>t.id==='c').parent_id,undefined);assert.equal(p.tasks.find(t=>t.id==='d').parent_id,'c');assert.equal(p.tasks.length,3);validateProject(p);});
test('deleting nested parent promotes its children to grandparent',()=>{let p=addDependency(fresh(),'c','b');p=removeTask(p,'c');assert.equal(p.tasks.find(t=>t.id==='d').parent_id,'a');assert.deepEqual(p.tasks.find(t=>t.id==='b').depends_on,[]);validateProject(p);});
test('branch movement retains spacing and leaves other roots unchanged',()=>{const p=autoLayout(fresh()),q=moveBranch(p,'c',34,21);for(const id of ['c','d']){assert.equal(q.layout.positions[id].x,p.layout.positions[id].x+34);assert.equal(q.layout.positions[id].y,p.layout.positions[id].y+21);}assert.deepEqual(q.layout.positions.a,p.layout.positions.a);assert.deepEqual(q.layout.positions.b,p.layout.positions.b);});
test('hierarchy auto-layout has no overlapping cards',()=>{let p=fresh();for(let i=0;i<9;i++)p=insertBlankStep(p,{x:0,y:0},null,i<4?'a':'c').document;p=autoLayout(p);for(let i=0;i<p.tasks.length;i++)for(let j=0;j<i;j++){const a=p.layout.positions[p.tasks[i].id],b=p.layout.positions[p.tasks[j].id],as=taskSize(p.tasks[i]),bs=taskSize(p.tasks[j]);assert.ok(a.x+as.width<=b.x||b.x+bs.width<=a.x||a.y+as.height<=b.y||b.y+bs.height<=a.y);}for(const t of p.tasks.filter(t=>t.parent_id))assert.ok(p.layout.positions[t.id].y>p.layout.positions[t.parent_id].y);});
test('legacy checklist entries convert preserving text and status',()=>{const p=fresh();p.tasks[0].substeps=[{id:'check',title:'Review',status:'done',notes:'Retain notes'}];const q=validateProject(p);assert.equal(q.tasks.length,5);assert.equal(q.tasks[0].substeps,undefined);assert.equal(p.tasks[0].substeps.length,1);assert.equal(q.tasks.at(-1).parent_id,'a');assert.equal(q.tasks.at(-1).notes,'Retain notes');assert.equal(q.tasks.at(-1).status,'done');assert.deepEqual(q.tasks.at(-1).depends_on,[]);assert.deepEqual(validateProject(q),q);});
test('legacy unknown metadata is preserved, ID collisions resolved',()=>{const p=fresh();p.tasks.push({id:'a_check',title:'Existing'});p.tasks[0].substeps=[{id:'check',title:'New',tag:'Important'}];const q=validateProject(p);assert.equal(q.tasks.at(-1).id,'a_check_2');assert.equal(q.tasks.at(-1).legacy_substep.tag,'Important');assert.equal(q.tasks.at(-1).legacy_substep.id,'check');});
test('empty legacy lists removed without creating children',()=>{const p=fresh();p.tasks[0].substeps=[];assert.equal(validateProject(p).tasks.length,4);assert.equal(validateProject(p).tasks[0].substeps,undefined);});
test('legacy validation still refuses corrupt entries',()=>{const p=fresh();p.tasks[0].substeps=[{id:'x',title:'X',status:'bad'}];assert.throws(()=>validateProject(p),/status/);});
test('500-task limit includes converted children; no silent data loss',()=>{const p={schema_version:1,project:{name:'Large'},tasks:Array.from({length:500},(_,i)=>({id:`t${i}`,title:'Task'}))};p.tasks[0].substeps=[{id:'x',title:'X'}];assert.throws(()=>validateProject(p),/500-step/);assert.throws(()=>insertBlankStep(validateProject({...p,tasks:p.tasks.map(t=>({id:t.id,title:t.title}))}),{x:0,y:0}),/500/);});
test('parent IDs and child notes included in YAML export',()=>{const p=fresh();p.tasks[3].notes='A: B\nKeep';const s=toYaml(p);assert.match(s,/parent_id: "c"/);assert.match(s,/A: B\\nKeep/);});

test('outline groups parents before children even when the file is interleaved',()=>{
  const p=fresh(),before=cloneForTest(p),rows=stepOutline(p);
  assert.deepEqual(rows.map(r=>[r.task.id,r.number,r.depth]),[['a','1',0],['c','1.1',1],['d','1.1.1',2],['b','2',0]]);
  assert.deepEqual(p,before);
});
function cloneForTest(p){return JSON.parse(JSON.stringify(p));}
test('changing an occupied root number swaps roots and updates every descendant',()=>{
  const p=fresh(),q=setStepNumber(p,'a',2);
  assert.deepEqual(stepOutline(q).map(r=>[r.task.id,r.number]),[['b','1'],['a','2'],['c','2.1'],['d','2.1.1']]);
  assert.equal(p.tasks[0].step_number,undefined);
  assert.deepEqual(q.tasks.map(t=>[t.id,t.parent_id,t.depends_on]),p.tasks.map(t=>[t.id,t.parent_id,t.depends_on]));
  assert.deepEqual(q.layout,p.layout);
  assert.deepEqual(validateProject(q),q);
  assert.match(toYaml(q),/step_number: 2/);
});
test('explicit numbering reserves numbers while added roots take a free number',()=>{
  let p=setStepNumber(fresh(),'a',7);p=insertBlankStep(p,{x:0,y:0}).document;
  assert.deepEqual(stepOutline(p).filter(r=>!r.depth).map(r=>r.number),['1','2','7']);
  assert.equal(stepOutline(p).find(r=>r.task.id==='d').number,'7.1.1');
});
test('invalid, duplicate, and child number edits are rejected',()=>{
  for(const n of [0,-1,1.5,NaN,Infinity,true,'2'])assert.throws(()=>setStepNumber(fresh(),'a',n),/whole number/);
  assert.throws(()=>setStepNumber(fresh(),'c',4),/main steps/);
  const p=fresh();p.tasks[0].step_number=2;p.tasks[1].step_number=2;
  assert.throws(()=>validateProject(p),/unique/);
});
test('reparenting derives numbers from the new branch; promotion gets a free root number',()=>{
  const p=setStepNumber(fresh(),'a',7),q=setParent(p,'a','b');
  assert.equal(q.tasks[0].step_number,undefined);
  assert.equal(stepOutline(q).find(r=>r.task.id==='d').number,'2.1.1.1');
  const promoted=removeTask(q,'b');validateProject(promoted);
  assert.equal(stepOutline(promoted).find(r=>r.task.id==='d').number,'1.1.1');
});
