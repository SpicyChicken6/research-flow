import test from 'node:test';
import assert from 'node:assert/strict';
import {validateProject, addBranchDependency, addDependency, insertBlankStep, removeTask, setParent, taskSize, toYaml} from '../web/model.mjs';
const fresh=()=>validateProject({schema_version:1,project:{name:'Branches'},tasks:[
 {id:'main',title:'Main'}, {id:'child',title:'Child',parent_id:'main'},
 {id:'grand',title:'Grandchild',parent_id:'child'}, {id:'free',title:'Free'},
 {id:'other',title:'Other main'}, {id:'other_child',title:'Other child',parent_id:'other'}
],layout:{positions:{main:{x:0,y:0},child:{x:0,y:200},grand:{x:0,y:400},free:{x:300,y:200},other:{x:700,y:0},other_child:{x:700,y:200}}}});
const task=(p,id)=>p.tasks.find(t=>t.id===id);
test('outgoing dependency joins an ungrouped step to the same parent',()=>{
 const p=fresh(),q=addBranchDependency(p,'child','free');assert.equal(task(q,'free').parent_id,'main');assert.deepEqual(task(q,'free').depends_on,['child']);assert.equal(task(p,'free').parent_id,undefined);
});
test('incoming prerequisite can also join the child branch',()=>{const q=addBranchDependency(fresh(),'free','child');assert.equal(task(q,'free').parent_id,'main');assert.deepEqual(task(q,'child').depends_on,['free']);});
test('grandchild connection uses immediate containing parent, not extra nesting',()=>{const q=addBranchDependency(fresh(),'grand','free');assert.equal(task(q,'free').parent_id,'child');});
test('no additional dependency is created from the main step',()=>{const q=addBranchDependency(fresh(),'child','free');assert.deepEqual(task(q,'free').depends_on,['child']);assert.deepEqual(task(q,'main').depends_on,[]);});
test('connected step size immediately becomes child size',()=>{assert.deepEqual(taskSize(task(addBranchDependency(fresh(),'child','free'),'free')),{width:212,height:136});});
test('successive dependency additions extend the branch',()=>{let p=fresh();p.tasks.push({id:'tail',title:'Tail',depends_on:[]});p=validateProject(p);p=addBranchDependency(p,'child','free');p=addBranchDependency(p,'free','tail');assert.equal(task(p,'tail').parent_id,'main');});
test('connecting two roots does not invent parentage',()=>{const q=addBranchDependency(fresh(),'main','other');assert.equal(task(q,'main').parent_id,undefined);assert.equal(task(q,'other').parent_id,undefined);});
test('connecting existing branches preserves both explicit parents',()=>{const q=addBranchDependency(fresh(),'child','other_child');assert.equal(task(q,'child').parent_id,'main');assert.equal(task(q,'other_child').parent_id,'other');});
test('a root that already owns children is not adopted',()=>{const q=addBranchDependency(fresh(),'child','other');assert.equal(task(q,'other').parent_id,undefined);assert.deepEqual(task(q,'other').depends_on,['child']);});
test('a direct parent never becomes its own child',()=>{const q=addBranchDependency(fresh(),'child','main');assert.equal(task(q,'main').parent_id,undefined);});
test('an ancestor remains an ancestor even with reverse dependencies',()=>{const q=addBranchDependency(fresh(),'grand','main');assert.equal(task(q,'main').parent_id,undefined);});
test('mixed-branch prerequisites do not choose a parent by last-click wins',()=>{let p=addDependency(fresh(),'other_child','free');const q=addBranchDependency(p,'child','free');assert.equal(task(q,'free').parent_id,undefined);assert.deepEqual(task(q,'free').depends_on,['other_child','child']);});
test('already connected main-step leaf remains a main step',()=>{let p=addDependency(fresh(),'main','free');const q=addBranchDependency(p,'child','free');assert.equal(task(q,'free').parent_id,undefined);});
test('earlier same-branch neighbors are consistent with adoption',()=>{let p=fresh();p.tasks.push({id:'sibling',title:'Sibling',parent_id:'main',depends_on:[]});p=addDependency(validateProject(p),'sibling','free');const q=addBranchDependency(p,'child','free');assert.equal(task(q,'free').parent_id,'main');});
test('duplicate connections are a true no-op, not an implicit migration',()=>{const p=addDependency(fresh(),'child','free');assert.deepEqual(addBranchDependency(p,'child','free'),p);assert.equal(task(p,'free').parent_id,undefined);});
test('load and validation do not silently migrate old dependency relationships',()=>{const p=addDependency(fresh(),'child','free');assert.equal(task(validateProject(p),'free').parent_id,undefined);});
test('dependency cycles are rejected atomically before adoption',()=>{const p=addDependency(fresh(),'free','child');const before=JSON.stringify(p);assert.throws(()=>addBranchDependency(p,'child','free'),/cycle/);assert.equal(JSON.stringify(p),before);assert.equal(task(p,'free').parent_id,undefined);});
test('self-dependency remains invalid without mutations',()=>{const p=fresh();assert.throws(()=>addBranchDependency(p,'child','child'),/itself/);assert.equal(task(p,'child').parent_id,'main');});
test('invalid endpoints are rejected',()=>{assert.throws(()=>addBranchDependency(fresh(),'missing','child'),/Source/);assert.throws(()=>addBranchDependency(fresh(),'child','missing'),/Target/);});
test('blank Add connected step inherits container and one dependency',()=>{const {document:q,id}=insertBlankStep(fresh(),{x:50,y:80},'child');assert.equal(task(q,id).parent_id,'main');assert.deepEqual(task(q,id).depends_on,['child']);});
test('blank connected grandchild inherits its immediate container',()=>{const {document:q,id}=insertBlankStep(fresh(),{x:50,y:80},'grand');assert.equal(task(q,id).parent_id,'child');});
test('explicit Add child remains hierarchy-only',()=>{const {document:q,id}=insertBlankStep(fresh(),{x:50,y:80},null,'child');assert.equal(task(q,id).parent_id,'child');assert.deepEqual(task(q,id).depends_on,[]);});
test('blank independent step is still independent',()=>{const {document:q,id}=insertBlankStep(fresh(),{x:50,y:80});assert.equal(task(q,id).parent_id,undefined);assert.deepEqual(task(q,id).depends_on,[]);});
test('link edits do not change titles, notes or saved coordinates',()=>{const p=fresh();task(p,'free').notes='Keep my work';const q=addBranchDependency(p,'child','free');assert.equal(task(q,'free').notes,'Keep my work');assert.equal(task(q,'free').title,'Free');assert.deepEqual(q.layout,p.layout);});
test('deletion still promotes children and removes only affected links',()=>{let p=addBranchDependency(fresh(),'child','free');const q=removeTask(p,'child');assert.equal(task(q,'grand').parent_id,'main');assert.equal(task(q,'free').parent_id,'main');assert.deepEqual(task(q,'free').depends_on,[]);assert.equal(task(p,'grand').parent_id,'child');});
test('manual parent selection can override automatic membership',()=>{const p=addBranchDependency(fresh(),'child','free');const q=setParent(p,'free',null);assert.equal(task(q,'free').parent_id,undefined);assert.deepEqual(task(q,'free').depends_on,['child']);});
test('saved data serializes inherited membership with unchanged schema',()=>{const q=addBranchDependency(fresh(),'child','free');assert.equal(q.schema_version,1);assert.match(toYaml(q),/parent_id: "main"/);assert.deepEqual(validateProject(JSON.parse(JSON.stringify(q))),q);});
