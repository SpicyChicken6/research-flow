import test from 'node:test';
import assert from 'node:assert/strict';
import {validateProject} from '../web/model.mjs';
import {computeLayerCanvas,resolveLayerSelection,renderLayeredView,renderMethodDetails} from '../web/layers.mjs';

const record=(id)=>({id,method:'Recorded method',recorded_at:'2026-10-16',status:'completed'});
const fresh=()=>validateProject({schema_version:1,project:{name:'Canvas'},tasks:[
  {id:'question',title:'Question',layer:'overview'},
  {id:'analysis',title:'Analysis',layer:'overview',depends_on:['question']},
  {id:'reading',title:'Read literature',layer:'operation',overview_id:'question'},
  {id:'qc',title:'Quality control',layer:'operation',overview_id:'analysis'},
  {id:'normalize',title:'Normalization',layer:'operation',overview_id:'analysis',depends_on:['qc']},
  {id:'scale',title:'Scale counts',layer:'processing',operation_id:'normalize',records:[record('scale_run')]},
  {id:'log',title:'Log transform',layer:'processing',operation_id:'normalize',depends_on:['scale']},
  {id:'filter',title:'Filter low quality',layer:'processing',operation_id:'qc'},
]});
const selected={overviewId:'analysis',operationId:'normalize',processingId:'scale',selectedId:'scale'};

test('canvas shows all overview, focused operations, and processing across those operations',()=>{
  const scene=computeLayerCanvas(fresh(),selected);
  assert.deepEqual(scene.nodes.filter(node=>node.layer==='overview').map(node=>node.id),['question','analysis']);
  assert.deepEqual(scene.nodes.filter(node=>node.layer==='operation').map(node=>node.id),['qc','normalize']);
  assert.deepEqual(scene.nodes.filter(node=>node.layer==='processing').map(node=>node.id),['filter','scale','log']);
  assert.ok(!scene.nodes.some(node=>node.id==='reading'));
  assert.equal(scene.state.overviewId,'analysis');
});

test('compiled rectangles are contained and do not overlap, including large sibling groups',()=>{
  const project=fresh();
  for(let i=0;i<20;i++)project.tasks.push({id:`extra_${i}`,title:`Extra ${i}`,layer:'processing',operation_id:'normalize',status:'todo',depends_on:[]});
  const scene=computeLayerCanvas(project,selected);
  assert.ok(scene.width<1600,'large processing groups wrap instead of stretching into a single row');
  assert.ok(new Set(scene.nodes.filter(node=>node.ownerId==='normalize').map(node=>node.y)).size>1);
  for(const node of scene.nodes){
    assert.ok(node.x>=scene.bounds.x && node.y>=scene.bounds.y && node.x+node.width<=scene.bounds.x+scene.bounds.width && node.y+node.height<=scene.bounds.y+scene.bounds.height);
    for(const other of scene.nodes)if(node!==other)assert.ok(node.x+node.width<=other.x || other.x+other.width<=node.x || node.y+node.height<=other.y || other.y+other.height<=node.y,`${node.id} overlaps ${other.id}`);
  }
});

test('automatic arrangement balances complete branches around their overview and fans children outward',()=>{
  const project=fresh(), before=structuredClone(project), scene=computeLayerCanvas(project,selected), byId=new Map(scene.nodes.map(node=>[node.id,node]));
  const overview=byId.get('analysis'), operations=scene.nodes.filter(node=>node.layer==='operation');
  assert.ok(operations.some(node=>node.y+node.height<overview.y));
  assert.ok(operations.some(node=>node.y>overview.y+overview.height));
  const spine=scene.nodes.filter(node=>node.layer==='overview');
  assert.equal(new Set(spine.map(node=>node.y)).size,1);
  assert.ok(spine.every((node,index)=>!index || node.x>spine[index-1].x));
  for(const operation of operations){
    const children=scene.nodes.filter(node=>node.ownerId===operation.id), above=operation.y<overview.y;
    assert.ok(Math.abs(operation.x-overview.x)<400,'branches remain close to their owning overview');
    for(const child of children)assert.ok(above?child.y<operation.y:child.y>operation.y);
    for(const y of new Set(children.map(node=>node.y))){
      const row=children.filter(node=>node.y===y);
      if(row.length>1)assert.equal((Math.min(...row.map(node=>node.x))+Math.max(...row.map(node=>node.x+node.width)))/2,operation.x+operation.width/2);
    }
  }
  assert.deepEqual(computeLayerCanvas(project,{...selected,operationId:'qc',selectedId:'qc'}).nodes,scene.nodes,'selection does not jitter arrangement');
  assert.deepEqual(computeLayerCanvas(project,selected),scene,'repeated arrangement is deterministic');
  assert.deepEqual(project,before);
});

test('many uneven branches reserve their complete footprints without collisions',()=>{
  const project=fresh();
  for(let i=0;i<12;i++){
    const id=`operation_${i}`;project.tasks.push({id,title:id,layer:'operation',overview_id:'analysis',status:'todo',depends_on:[]});
    for(let child=0;child<i%5;child++)project.tasks.push({id:`${id}_${child}`,title:'Processing',layer:'processing',operation_id:id,status:'todo',depends_on:[]});
  }
  const scene=computeLayerCanvas(project,selected), overview=scene.nodes.find(node=>node.id==='analysis');
  assert.ok(scene.width<1700,'branch bands prevent an unnecessarily wide diagram');
  for(const node of scene.nodes){
    for(const other of scene.nodes)if(node!==other)assert.ok(node.x+node.width<=other.x || other.x+other.width<=node.x || node.y+node.height<=other.y || other.y+other.height<=node.y,`${node.id} overlaps ${other.id}`);
    if(node.layer==='processing'){
      const parent=scene.nodes.find(other=>other.id===node.ownerId);
      assert.ok(parent.y<overview.y?node.y<parent.y:node.y>parent.y);
    }
  }
});

test('single-child and unassigned-only scenes stay compact without invented owners',()=>{
  const project=validateProject({schema_version:1,project:{name:'Unassigned'},tasks:[
    {id:'operation',title:'Operation',layer:'operation'},
    {id:'child',title:'Child',layer:'processing',operation_id:'operation'},
    {id:'orphan_a',title:'Orphan A',layer:'processing'},
    {id:'orphan_b',title:'Orphan B',layer:'processing'},
    {id:'orphan_c',title:'Orphan C',layer:'processing'},
  ]});
  const scene=computeLayerCanvas(project,{overviewId:':unassigned'}), operation=scene.nodes.find(node=>node.id==='operation'), child=scene.nodes.find(node=>node.id==='child');
  assert.ok(Math.abs(child.x-operation.x)>operation.width,'single children sit diagonally beside their owner');
  assert.ok(Math.abs(child.y-operation.y)<200);
  assert.ok(scene.width<800 && scene.height<800);
  assert.deepEqual(scene.edges.map(edge=>`${edge.source}->${edge.target}`),['operation->child']);
  for(const node of scene.nodes)for(const other of scene.nodes)if(node!==other)assert.ok(node.x+node.width<=other.x || other.x+other.width<=node.x || node.y+node.height<=other.y || other.y+other.height<=node.y);
});

test('small processing groups flank their owner instead of adding another full level',()=>{
  const scene=computeLayerCanvas(fresh(),selected), owner=scene.nodes.find(node=>node.id==='normalize'), children=scene.nodes.filter(node=>node.ownerId==='normalize');
  assert.ok(children.some(node=>node.x+node.width<owner.x));
  assert.ok(children.some(node=>node.x>owner.x+owner.width));
  for(const child of children)assert.ok(Math.abs(child.y-owner.y)<owner.height,'diagonal offset keeps the local branch compact');
  assert.ok(scene.height<700);
});

test('new positions search inward from coordinate limits without altering saved pins',()=>{
  for(const sign of [-1,1]){
    const project=fresh();project.layout.layer_positions={normalize:{x:sign*10000000,y:sign*10000000}};
    const scene=computeLayerCanvas(project,selected), pin=scene.nodes.find(node=>node.id==='normalize');
    assert.deepEqual({x:pin.x,y:pin.y},project.layout.layer_positions.normalize);
    for(const node of scene.nodes){
      assert.ok(Math.abs(node.x)<=10000000 && Math.abs(node.y)<=10000000);
      for(const other of scene.nodes)if(node!==other)assert.ok(node.x+node.width<=other.x || other.x+other.width<=node.x || node.y+node.height<=other.y || other.y+other.height<=node.y);
    }
    project.layout.layer_positions=Object.fromEntries(scene.nodes.map(node=>[node.id,{x:node.x,y:node.y}]));
    assert.doesNotThrow(()=>validateProject(project),'freezing the visible layout remains valid');
  }
});

test('saved positions override arrangement without shifting raw coordinates or changing graph data',()=>{
  const project=fresh();
  project.layout.layer_positions={analysis:{x:30,y:20},normalize:{x:-420.5,y:-260.25},scale:{x:500,y:-450},reading:{x:-9000,y:-9000}};
  const before=structuredClone(project), scene=computeLayerCanvas(project,selected);
  for(const id of ['analysis','normalize','scale']){
    const node=scene.nodes.find(node=>node.id===id);
    assert.deepEqual({x:node.x,y:node.y},project.layout.layer_positions[id]);
  }
  assert.ok(scene.bounds.x<=-468.5);assert.ok(scene.bounds.y<=-498);
  assert.ok(scene.bounds.x>-9000,'hidden cards do not expand the visible canvas');
  for(const point of [...scene.nodes.flatMap(node=>[{x:node.x,y:node.y},{x:node.x+node.width,y:node.y+node.height}]),...scene.edges.flatMap(edge=>edge.points)]){
    assert.ok(point.x>=scene.bounds.x && point.x<=scene.bounds.x+scene.bounds.width);
    assert.ok(point.y>=scene.bounds.y && point.y<=scene.bounds.y+scene.bounds.height);
  }
  project.layout.layer_positions.qc={x:-1800,y:800};
  const changed=computeLayerCanvas(project,selected);
  assert.deepEqual(changed.nodes.find(node=>node.id==='normalize'),scene.nodes.find(node=>node.id==='normalize'));
  delete project.layout.layer_positions.qc;
  assert.deepEqual(project,before);
});

test('membership and dependencies attach to facing edges in all directions',()=>{
  const placements=[
    {x:400,y:0,sourceSide:'right',targetSide:'left'},
    {x:-400,y:0,sourceSide:'left',targetSide:'right'},
    {x:0,y:300,sourceSide:'bottom',targetSide:'top'},
    {x:0,y:-300,sourceSide:'top',targetSide:'bottom'},
    {x:400,y:60,sourceSide:'right',targetSide:'left'},
    {x:-400,y:-60,sourceSide:'left',targetSide:'right'},
    {x:60,y:300,sourceSide:'bottom',targetSide:'top'},
    {x:-60,y:-300,sourceSide:'top',targetSide:'bottom'},
  ];
  const onSide=(point,node,side)=>{
    if(side==='left'||side==='right')assert.equal(point.x,node.x+(side==='right'?node.width:0));
    else assert.equal(point.y,node.y+(side==='bottom'?node.height:0));
    assert.ok(point.x>=node.x && point.x<=node.x+node.width && point.y>=node.y && point.y<=node.y+node.height);
  };
  for(const placement of placements){
    const project=fresh();project.tasks.find(task=>task.id==='normalize').depends_on=['analysis'];
    project.layout.layer_positions={analysis:{x:0,y:0},normalize:{x:placement.x,y:placement.y}};
    const scene=computeLayerCanvas(project,selected), source=scene.nodes.find(node=>node.id==='analysis'), target=scene.nodes.find(node=>node.id==='normalize');
    const edges=scene.edges.filter(edge=>edge.source==='analysis' && edge.target==='normalize');
    assert.equal(edges.length,2);
    for(const edge of edges){
      assert.equal(edge.sourceSide,placement.sourceSide);assert.equal(edge.targetSide,placement.targetSide);
      onSide(edge.start,source,edge.sourceSide);onSide(edge.end,target,edge.targetSide);
      assert.ok(edge.path.startsWith(`M ${edge.start.x} ${edge.start.y}`));
      assert.ok(edge.path.endsWith(`${edge.end.x} ${edge.end.y}`));
    }
    assert.notDeepEqual(edges[0].start,edges[1].start,'membership and dependency do not conceal each other');
  }
});

test('new cards find space near their owner without moving saved cards',()=>{
  const project=fresh(), initial=computeLayerCanvas(project,selected);
  project.layout.layer_positions=Object.fromEntries(initial.nodes.map(node=>[node.id,{x:node.x,y:node.y}]));
  project.layout.layer_positions.normalize={x:-600,y:-500};
  // Keep another saved card close to the owner's new position.
  project.layout.layer_positions.scale={x:-600,y:-360};
  project.tasks.push({id:'new_processing',title:'New processing step',layer:'processing',operation_id:'normalize',status:'todo',depends_on:[]});
  const before=structuredClone(project), scene=computeLayerCanvas(project,selected), node=scene.nodes.find(node=>node.id==='new_processing');
  for(const other of scene.nodes){
    if(other===node)continue;
    assert.ok(node.x+node.width<=other.x || other.x+other.width<=node.x || node.y+node.height<=other.y || other.y+other.height<=node.y,`new card overlaps ${other.id}`);
    assert.deepEqual({x:other.x,y:other.y},project.layout.layer_positions[other.id]);
  }
  assert.ok(Math.hypot(node.x+600,node.y+500)<500,'new work stays close to its owner');
  assert.deepEqual(project,before);
});

test('a dependency skipping an aligned card routes around it and retains arrow direction',()=>{
  const project=fresh();project.tasks.find(task=>task.id==='log').depends_on=['filter'];
  project.layout.layer_positions={filter:{x:-300,y:-200},scale:{x:0,y:-200},log:{x:300,y:-200}};
  const scene=computeLayerCanvas(project,selected), edge=scene.edges.find(edge=>edge.kind==='dependency' && edge.source==='filter' && edge.target==='log');
  assert.equal(edge.sourceSide,'right');assert.equal(edge.targetSide,'left');
  assert.ok(edge.points.some(point=>point.y<-200 || point.y>-92));
  assert.ok(edge.path.includes(' Q '),'obstacle detours soften their corners');
});

test('near-aligned dependencies and diagonal memberships avoid the intervening card',()=>{
  const project=validateProject({schema_version:1,project:{name:'Moved above overview'},tasks:[
    {id:'overview',title:'Prepare',layer:'overview'},
    {id:'filter',title:'Filter',layer:'operation',overview_id:'overview'},
    {id:'normalize',title:'Normalize',layer:'operation',overview_id:'overview',depends_on:['filter']},
    {id:'scale',title:'Scale',layer:'processing',operation_id:'normalize'},
  ],layout:{layer_positions:{overview:{x:508,y:76},filter:{x:512,y:286},normalize:{x:508,y:-104},scale:{x:736,y:496}}}});
  const scene=computeLayerCanvas(project,{overviewId:'overview'}), obstacle=scene.nodes.find(node=>node.id==='overview');
  const edges=[scene.edges.find(edge=>edge.source==='filter' && edge.target==='normalize'),scene.edges.find(edge=>edge.source==='normalize' && edge.target==='scale')];
  for(const edge of edges){
    assert.ok(edge.path.includes(' Q '),'nearby obstacle routes have curved bends');
    for(let i=1;i<edge.points.length;i++){
      const a=edge.points[i-1],b=edge.points[i];
      const intersects=a.x===b.x
        ? a.x>obstacle.x && a.x<obstacle.x+obstacle.width && Math.min(a.y,b.y)<obstacle.y+obstacle.height && Math.max(a.y,b.y)>obstacle.y
        : a.y>obstacle.y && a.y<obstacle.y+obstacle.height && Math.min(a.x,b.x)<obstacle.x+obstacle.width && Math.max(a.x,b.x)>obstacle.x;
      assert.ok(!intersects,`${edge.kind} crosses Prepare`);
    }
    assert.ok(edge.points.some(point=>point.x===704),'uses the nearby gap beside Prepare');
    assert.ok(edge.points.every(point=>point.x>=508 && point.x<=828),'does not travel to an outer global corridor');
  }
  assert.equal(edges[0].sourceSide,'top');assert.equal(edges[0].targetSide,'bottom');
  assert.equal(edges[1].sourceSide,'bottom');assert.equal(edges[1].targetSide,'top');
});

test('free-position markup keeps raw negative coordinates and exposes fitting bounds',()=>{
  const project=fresh();project.layout.layer_positions={normalize:{x:-420.5,y:-260.25}};
  const scene=computeLayerCanvas(project,selected), markup=renderLayeredView(project,selected);
  assert.match(markup,/data-id="normalize" data-layer="operation" data-x="-420\.5" data-y="-260\.25" style="left:-420\.5px;top:-260\.25px/);
  assert.ok(markup.includes(`data-bounds-x="${scene.bounds.x}" data-bounds-y="${scene.bounds.y}"`));
  assert.ok(markup.includes(`viewBox="${scene.bounds.x} ${scene.bounds.y} ${scene.width} ${scene.height}" style="left:${scene.bounds.x}px;top:${scene.bounds.y}px"`));
  assert.match(markup,/data-action="layer-arrange"/);
  assert.ok(!markup.includes('flow-row-label'));
  assert.ok(!markup.includes('flow-row-empty'),'a missing layer does not place prose at reserved row coordinates');
  assert.match(markup,/Overview · Step/);
});

test('membership edges group work while dependency edges exactly preserve authored order',()=>{
  const project=fresh(), scene=computeLayerCanvas(project,selected);
  const edgeSet=kind=>scene.edges.filter(edge=>edge.kind===kind).map(edge=>`${edge.source}->${edge.target}`).sort();
  assert.deepEqual(edgeSet('dependency'),['qc->normalize','question->analysis','scale->log']);
  assert.deepEqual(edgeSet('membership'),['analysis->normalize','analysis->qc','normalize->log','normalize->scale','qc->filter']);
  assert.ok(!scene.edges.some(edge=>edge.kind==='dependency' && edge.source==='filter'));
});

test('rendered connections expose distinct styles and only dependencies have arrowheads',()=>{
  const markup=renderLayeredView(fresh(),selected);
  const membership=markup.match(/<path class="layer-membership-path"[^>]*>/g);
  const dependencies=markup.match(/<path class="layer-dependency-path"[^>]*>/g);
  assert.equal(membership.length,5);assert.equal(dependencies.length,3);
  assert.ok(membership.every(path=>!path.includes('marker-end')));
  assert.ok(dependencies.every(path=>path.includes('marker-end="url(#layer-dependency-arrow)"')));
  assert.match(markup,/data-action="layer-processing" data-id="scale" data-layer="processing"/);
  assert.match(markup,/id="layer-canvas"/);assert.match(markup,/id="layer-world"/);
});

test('processing selection retains its own history without mutating project or selection',()=>{
  const project=fresh(), selection={...selected,recordId:'scale_run'}, before=structuredClone(project), stateBefore=structuredClone(selection);
  const state=resolveLayerSelection(project,selection);
  assert.equal(state.processingId,'scale');assert.equal(state.recordTaskId,'scale');assert.equal(state.recordId,'scale_run');
  computeLayerCanvas(project,selection);renderLayeredView(project,selection);
  assert.deepEqual(project,before);assert.deepEqual(selection,stateBefore);
});

test('orphan processing is accessible even without unassigned operations',()=>{
  const project=fresh();project.tasks.push({id:'orphan',title:'Unassigned transform',layer:'processing',status:'todo',depends_on:[]});
  const state=resolveLayerSelection(project,{overviewId:':unassigned',processingId:'orphan'});
  assert.equal(state.overviewId,':unassigned');assert.equal(state.operations.length,0);
  assert.deepEqual(state.processing.map(task=>task.id),['orphan']);
  const scene=computeLayerCanvas(project,state);
  assert.ok(scene.nodes.some(node=>node.id==='orphan'));
  assert.ok(!scene.edges.some(edge=>edge.target==='orphan'));
  assert.match(renderLayeredView(project,state),/Unassigned \(1\)/);
});

test('empty and legacy projects remain navigable without adding model fields',()=>{
  const empty=validateProject({schema_version:1,project:{name:'Empty'},tasks:[]});
  assert.equal(computeLayerCanvas(empty).nodes.length,0);
  assert.match(renderLayeredView(empty),/Add an overview step/);
  const legacy=validateProject({schema_version:1,project:{name:'Legacy'},tasks:[{id:'main',title:'Main'},{id:'child',title:'Child',parent_id:'main'}]}), before=structuredClone(legacy);
  assert.deepEqual(computeLayerCanvas(legacy).nodes.map(node=>node.layer),['overview','operation']);
  assert.deepEqual(legacy,before);
});

test('hidden prerequisites are disclosed rather than represented by fabricated edges',()=>{
  const project=fresh();project.tasks.find(task=>task.id==='qc').depends_on=['reading'];
  const scene=computeLayerCanvas(project,selected);
  assert.ok(!scene.edges.some(edge=>edge.source==='reading'));
  assert.match(renderLayeredView(project,selected),/class="flow-offscope" title="1 prerequisite outside this view"/);
});

test('node labels, idea content, and method evidence are escaped at markup boundaries',()=>{
  const project=fresh();project.tasks.find(task=>task.id==='scale').title='<img src=x onerror="bad()">';
  project.ideas=[{id:'idea1',title:'<script>bad()</script>',kind:'question',status:'open',created_at:'2026-10-16',notes:'" onmouseover="bad()'}];
  const markup=renderLayeredView(project,selected,false,false,{open:true,filter:'all'});
  assert.ok(!markup.includes('<img src=x'));assert.ok(!markup.includes('<script>bad()'));
  assert.match(markup,/&lt;img src=x onerror=&quot;bad\(\)&quot;&gt;/);
  const task=project.tasks.find(task=>task.id==='scale');task.records[0].code='</dd><script>bad()</script>';
  assert.ok(!renderMethodDetails(task,'scale_run').includes('<script>bad()'));
});

test('records render in the inspector helper, not as a canvas section',()=>{
  const project=fresh(), task=project.tasks.find(task=>task.id==='scale');
  assert.ok(!renderLayeredView(project,selected).includes('class="method-details"'));
  const details=renderMethodDetails(task,'scale_run');
  assert.match(details,/data-action="layer-record-select" data-id="scale_run" data-task-id="scale"/);
  assert.match(details,/data-action="layer-record" data-id="scale"/);
  assert.match(details,/data-action="layer-use-record" data-id="scale_run" data-task-id="scale"/);
});
