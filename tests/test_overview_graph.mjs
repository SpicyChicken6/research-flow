import test from 'node:test';
import assert from 'node:assert/strict';
import {validateProject, overviewGraph, dependencyStages, overviewStepLayout, stageLayout, taskSize} from '../web/model.mjs';
import {overviewConnector} from '../web/layers.mjs';

const fresh = () => validateProject({schema_version: 1, project: {name: 'Overview'},
  tasks: [
    {id: 'question', title: 'Define question'},
    {id: 'prepare', title: 'Prepare data', layer: 'overview', depends_on: ['question']},
    {id: 'normalize', title: 'Normalize', layer: 'operation', overview_id: 'prepare', depends_on: ['prepare'],
      records: [{id: 'attempt', recorded_at: '2026-10-16', status: 'recorded', method: 'Preserve this account'}]},
    {id: 'scale', title: 'Scale', layer: 'processing', operation_id: 'normalize', depends_on: ['normalize']},
    {id: 'analyze', title: 'Analyze', layer: 'overview', depends_on: ['scale']},
    {id: 'report', title: 'Report', layer: 'overview', depends_on: ['analyze', 'normalize']},
  ],
  ideas: [{id: 'review', title: 'Review method', kind: 'question', status: 'open', created_at: '2026-10-16', related_task_id: 'normalize'}],
  custom: {owner: 'Researcher'}, layout: {positions: {question: {x: 1, y: 2}, scale: {x: 500, y: 300}}},
});

test('overview graph contains only effective overview tasks and direct visible dependencies', () => {
  const p = fresh(), q = overviewGraph(p);
  assert.deepEqual(q.tasks.map(task => task.id), ['question', 'prepare', 'analyze', 'report']);
  assert.deepEqual(q.tasks.map(task => task.depends_on), [[], ['question'], [], ['analyze']]);
  assert.deepEqual([...dependencyStages(q)], [['question', 0], ['prepare', 1], ['analyze', 0], ['report', 1]]);
  assert.deepEqual(p.tasks.find(task => task.id === 'analyze').depends_on, ['scale']);
});

test('hidden paths never become inferred overview dependencies', () => {
  const p = fresh(), q = overviewGraph(p);
  assert.deepEqual(q.tasks.find(task => task.id === 'analyze').depends_on, []);
  assert.equal(q.tasks.find(task => task.id === 'report').depends_on.includes('prepare'), false);
  assert.equal(q.tasks.find(task => task.id === 'analyze').depends_on.includes('prepare'), false);
});

test('visible overview parentage survives and hidden parentage is removed only in the view', () => {
  const p = fresh();
  p.tasks.find(task => task.id === 'prepare').parent_id = 'question';
  p.tasks.find(task => task.id === 'analyze').parent_id = 'normalize';
  const q = overviewGraph(p);
  assert.equal(q.tasks.find(task => task.id === 'prepare').parent_id, 'question');
  assert.equal(q.tasks.find(task => task.id === 'analyze').parent_id, undefined);
  assert.equal(p.tasks.find(task => task.id === 'analyze').parent_id, 'normalize');
});

test('projection preserves unchanged task identities and all source history and metadata', () => {
  const p = fresh(), before = structuredClone(p);
  const freeze = value => { if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); } return value; };
  freeze(p);
  const q = overviewGraph(p);
  assert.notEqual(q, p);
  assert.notEqual(q.tasks, p.tasks);
  assert.equal(q.tasks[0], p.tasks[0]);
  assert.equal(q.tasks[1], p.tasks[1]);
  assert.notEqual(q.tasks[2], p.tasks[4]);
  assert.equal(q.project, p.project);
  assert.equal(q.layout, p.layout);
  assert.equal(q.ideas, p.ideas);
  assert.equal(q.custom, p.custom);
  assert.deepEqual(p, before);
  assert.equal(p.tasks[2].records[0].method, 'Preserve this account');
});

test('legacy roots remain overview, legacy children remain hidden, and explicit child overviews appear', () => {
  const p = validateProject({schema_version: 1, project: {name: 'Legacy'}, tasks: [
    {id: 'a', title: 'A'}, {id: 'b', title: 'B', parent_id: 'a'},
    {id: 'c', title: 'C', parent_id: 'b', layer: 'overview'},
  ]});
  assert.deepEqual(overviewGraph(p).tasks.map(task => task.id), ['a', 'c']);
  assert.equal(overviewGraph(p).tasks[1].parent_id, undefined);
  assert.equal(p.tasks[2].parent_id, 'b');
});

test('empty and operation-only projects yield an empty overview graph', () => {
  for (const tasks of [[], [{id: 'operation', title: 'Operation', layer: 'operation'}]]) {
    const p = validateProject({schema_version: 1, project: {name: 'Empty overview'}, tasks});
    assert.deepEqual(overviewGraph(p).tasks, []);
    assert.equal(p.tasks.length, tasks.length);
  }
});

test('overview columns follow explicit step numbers even when dependencies point backward', () => {
  const project=validateProject({schema_version:1,project:{name:'Numbered'},tasks:[
    {id:'last',title:'Last',step_number:9},
    {id:'first',title:'First',step_number:1,depends_on:['last']},
    {id:'middle',title:'Middle',step_number:5},
  ]});
  const scene=overviewStepLayout(project);
  assert.deepEqual(scene.stages.map(stage=>stage.taskIds),[['first'],['middle'],['last']]);
  assert.deepEqual(scene.stages.map(stage=>stage.label),['Step 1','Step 5','Step 9']);
  assert.ok(scene.positions.first.x<scene.positions.middle.x && scene.positions.middle.x<scene.positions.last.x);
  assert.deepEqual(project.tasks.find(task=>task.id==='first').depends_on,['last']);
  assert.deepEqual(project.tasks.find(task=>task.id==='middle').depends_on,[]);
});

test('overview labels retain hidden root gaps and nested numbering from the full outline', () => {
  const project=validateProject({schema_version:1,project:{name:'Full outline'},tasks:[
    {id:'hidden',title:'Hidden root',layer:'operation',step_number:2},
    {id:'hidden_child',title:'Hidden child',parent_id:'hidden'},
    {id:'nested',title:'Nested overview',layer:'overview',parent_id:'hidden_child'},
    {id:'sibling',title:'Sibling overview',layer:'overview',parent_id:'hidden'},
    {id:'later',title:'Later',step_number:4},
    {id:'first',title:'First'},
  ]});
  const scene=overviewStepLayout(project);
  assert.deepEqual(scene.stages.map(stage=>[stage.index,stage.taskIds[0],stage.label]),[
    [0,'first','Step 1'],[1,'nested','Step 2.1.1'],[2,'sibling','Step 2.2'],[3,'later','Step 4'],
  ]);
  assert.deepEqual(Object.keys(scene.positions),['first','nested','sibling','later']);
});

test('columns fit projected card sizes and align their vertical centers', () => {
  const project=validateProject({schema_version:1,project:{name:'Measured'},tasks:[
    {id:'root',title:'Root'},
    {id:'visible_child',title:'Visible parent',layer:'overview',parent_id:'root'},
    {id:'hidden',title:'Hidden',layer:'operation'},
    {id:'hidden_child',title:'Hidden parent',layer:'overview',parent_id:'hidden'},
  ]});
  const scene=overviewStepLayout(project),visible=overviewGraph(project).tasks;
  const centers=scene.stages.map((stage,index)=>{
    const id=stage.taskIds[0],size=taskSize(visible.find(task=>task.id===id)),position=scene.positions[id];
    assert.equal(stage.width,size.width+48);
    assert.equal(position.x-stage.x,24);
    assert.ok(position.y>=48+24 && position.y+size.height<=stage.height-24);
    if(index)assert.equal(stage.x-(scene.stages[index-1].x+scene.stages[index-1].width),84);
    return position.y+size.height/2;
  });
  assert.equal(new Set(centers).size,1);
  assert.equal(scene.stages.find(stage=>stage.taskIds[0]==='visible_child').width,260);
  assert.equal(scene.stages.find(stage=>stage.taskIds[0]==='hidden_child').width,288);
  assert.equal(scene.stages.find(stage=>stage.taskIds[0]==='hidden_child').height,244);
});

test('overview layout ignores saved positions while preserving frozen workflow metadata', () => {
  const project=fresh();
  project.layout.layer_positions={prepare:{x:-125.5,y:400},normalize:{x:500,y:-250}};
  const before=structuredClone(project),expected=overviewStepLayout(project);
  const freeze=value=>{if(value && typeof value==='object'){Object.values(value).forEach(freeze);Object.freeze(value);}return value;};
  freeze(project);
  assert.deepEqual(overviewStepLayout(project),expected);
  assert.deepEqual(project,before);
  const moved=structuredClone(project);
  moved.layout.positions.question={x:99999,y:-88888};moved.layout.layer_positions.prepare={x:700,y:900};
  assert.deepEqual(overviewStepLayout(moved),expected);
});

test('overview layout handles empty and operation-only documents without phantom columns', () => {
  for(const tasks of [[],[{id:'operation',title:'Operation',layer:'operation'}]]){
    const project=validateProject({schema_version:1,project:{name:'Empty overview'},tasks});
    assert.deepEqual(overviewStepLayout(project),{positions:{},stages:[]});
  }
});

test('step columns leave dependency-stage layout available with its existing semantics', () => {
  const project=validateProject({schema_version:1,project:{name:'Two layouts'},tasks:[
    {id:'first',title:'First',step_number:1,depends_on:['second']},
    {id:'second',title:'Second',step_number:2},
    {id:'independent',title:'Independent',step_number:3},
  ]});
  const before=stageLayout(project),steps=overviewStepLayout(project);
  assert.equal(steps.stages.length,3);
  assert.equal(before.stages.length,2);
  assert.ok(before.positions.first.x>before.positions.second.x);
  assert.ok(steps.positions.first.x<steps.positions.second.x);
  assert.deepEqual(stageLayout(project),before);
});

const sampleConnector=path=>{
  const tokens=path.match(/[MLCQ]|-?(?:\d*\.)?\d+(?:e[+-]?\d+)?/gi),points=[];
  let cursor=0,current;
  const point=()=>({x:Number(tokens[cursor++]),y:Number(tokens[cursor++])});
  while(cursor<tokens.length){
    const command=tokens[cursor++];
    if(command==='M'){current=point();points.push(current);continue;}
    const start=current,first=point(),second=command==='Q'||command==='C'?point():null,last=command==='C'?point():second||first;
    for(let sample=1;sample<=120;sample++){
      const t=sample/120,u=1-t;
      points.push(Object.fromEntries(['x','y'].map(axis=>[axis,command==='L'?u*start[axis]+t*last[axis]:command==='Q'?u*u*start[axis]+2*u*t*first[axis]+t*t*last[axis]:u*u*u*start[axis]+3*u*u*t*first[axis]+3*u*t*t*second[axis]+t*t*t*last[axis]])));
    }
    current=last;
  }
  return points;
};
const assertClearOverviewConnector=(source,target,nodes)=>{
  const edge=overviewConnector(source,target,nodes),samples=sampleConnector(edge.path);
  assert.equal(edge.sourceSide,'right');assert.equal(edge.targetSide,'left');
  assert.deepEqual(edge.start,{x:source.x+source.width,y:source.y+source.height/2});
  assert.deepEqual(edge.end,{x:target.x,y:target.y+target.height/2});
  assert.ok(samples[1].x>edge.start.x,'leaves the source toward its output side');
  assert.ok(samples.at(-2).x<edge.end.x,'enters the target from its input side');
  for(const sample of samples)for(const node of nodes){
    assert.ok(!(sample.x>node.x+1e-6 && sample.x<node.x+node.width-1e-6 && sample.y>node.y+1e-6 && sample.y<node.y+node.height-1e-6),`connector crosses ${node.id}`);
  }
  return edge;
};
const numberedNodes=()=>{
  const project=validateProject({schema_version:1,project:{name:'Connections'},tasks:[{id:'a',title:'A'},{id:'b',title:'B'},{id:'c',title:'C'}]});
  const scene=overviewStepLayout(project);
  return overviewGraph(project).tasks.map(task=>({id:task.id,...scene.positions[task.id],...taskSize(task)}));
};

test('overview forward shortcuts use rounded local routes around intermediate cards',()=>{
  const nodes=numberedNodes(),edge=assertClearOverviewConnector(nodes[0],nodes[2],nodes);
  assert.match(edge.path,/ Q /);
  assert.ok(edge.points.some(point=>point.y<nodes[1].y));
  assert.ok(edge.points.every(point=>point.y>=48),'route fits below the step header');
});

test('overview backward edges avoid both endpoint cards even with no intermediate obstacle',()=>{
  const all=numberedNodes();
  for(const nodes of [[all[0],all[2]],all]){
    const before=structuredClone(nodes),edge=assertClearOverviewConnector({...nodes.at(-1)},{...nodes[0]},nodes);
    assert.match(edge.path,/ Q /);
    assert.deepEqual(nodes,before);
  }
});

test('overview same-column edges keep fixed ports and route outside both cards',()=>{
  const nodes=[{id:'top',x:24,y:72,width:240,height:148},{id:'bottom',x:24,y:300,width:240,height:148}];
  for(const [source,target] of [[nodes[0],nodes[1]],[nodes[1],nodes[0]]]){
    const edge=assertClearOverviewConnector(source,target,nodes);
    assert.match(edge.path,/ Q /);
    assert.ok(edge.points.some(point=>point.x>source.x+source.width));
    assert.ok(edge.points.some(point=>point.x<target.x));
  }
});
