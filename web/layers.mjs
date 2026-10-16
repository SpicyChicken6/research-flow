/** Pure presentation of the research graph. Layout never changes project data. */
import { STATUS, taskLayer, overviewSteps, operationsFor, processingStepsFor, stepOutline } from './model.mjs';

const layerEscape = (value = '') => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const layerKind = task => (task.operation_type || (taskLayer(task) === 'processing' ? 'Processing step' : 'Operation')).replaceAll('_',' ').replace(/^./, c => c.toUpperCase());
const layerStatus = task => `<span class="layer-status status-${layerEscape(task.status)}"><i></i>${layerEscape(STATUS[task.status]?.label || task.status)}</span>`;
const layerText = value => value ? `<p class="method-copy">${layerEscape(value)}</p>` : '<p class="method-missing">Not recorded</p>';
const layerFiles = files => files?.length ? files.map(file => `<div class="artifact-reference"><code>${layerEscape(file)}</code></div>`).join('') : '<p class="method-missing">No references recorded</p>';
const layerDate = value => { const date = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T12:00:00`) : new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, {month:'short',day:'numeric',year:'numeric'}); };

export function resolveLayerSelection(project, state = {}) {
  const stages = stepOutline(project).map(row => row.task).filter(task => taskLayer(task) === 'overview');
  const allOperations = project.tasks.filter(task => taskLayer(task) === 'operation');
  const assigned = new Set(stages.flatMap(stage => operationsFor(project, stage.id).map(task => task.id)));
  const unassigned = allOperations.filter(task => !assigned.has(task.id));
  const ownedProcessing = new Set(allOperations.flatMap(task => processingStepsFor(project, task.id).map(step => step.id)));
  const unassignedProcessing = project.tasks.filter(task => taskLayer(task) === 'processing' && !ownedProcessing.has(task.id));
  const hasUnassigned = unassigned.length > 0 || unassignedProcessing.length > 0;
  const overviewId = state.overviewId === ':unassigned' && hasUnassigned ? ':unassigned'
    : stages.some(task => task.id === state.overviewId) ? state.overviewId
    : stages.find(task => task.status === 'in_progress')?.id || stages[0]?.id || ':unassigned';
  const operations = overviewId === ':unassigned' ? unassigned : operationsFor(project, overviewId);
  const operationId = operations.some(task => task.id === state.operationId) ? state.operationId
    : operations.find(task => task.status === 'in_progress')?.id || operations[0]?.id || null;
  const processing = operations.flatMap(task => processingStepsFor(project, task.id));
  if(overviewId === ':unassigned')processing.push(...unassignedProcessing);
  const processingId = processing.some(task => task.id === state.processingId) ? state.processingId : null;
  const visible = [...stages,...operations,...processing];
  const selectedId = visible.some(task => task.id === state.selectedId) ? state.selectedId : null;
  const recordTask = processing.find(task => task.id === processingId) || operations.find(task => task.id === operationId);
  const records = recordTask?.records || [];
  const recordId = records.some(record => record.id === state.recordId) ? state.recordId
    : recordTask?.selected_record_id || records.at(-1)?.id || null;
  return {overviewId,operationId,processingId,selectedId,recordId,recordTaskId:recordTask?.id || null,stages,operations,processing,unassigned,unassignedProcessing};
}

const NODE_WIDTH = 184, NODE_HEIGHT = 108, NODE_GAP = 32, GROUP_GAP = 40, MARGIN = 48;
const OVERVIEW_Y = 76, BRANCH_GAP = 48, DIAGONAL_OFFSET = 56, POSITION_LIMIT = 10000000;
const rowWidth = count => count ? count * NODE_WIDTH + (count - 1) * NODE_GAP : 0;

function arrangeBranches(state, groups) {
  const positions=new Map(state.stages.map((task,index)=>[task.id,{x:MARGIN+index*(NODE_WIDTH+NODE_GAP),y:OVERVIEW_Y}]));
  const spineWidth=Math.max(NODE_WIDTH,rowWidth(state.stages.length));
  const anchor=positions.get(state.overviewId) || {x:MARGIN+(spineWidth-NODE_WIDTH)/2,y:OVERVIEW_Y};
  const center=anchor.x+NODE_WIDTH/2, sides=[{direction:-1,groups:[],area:0},{direction:1,groups:[],area:0}];
  // Balance the whole subtree, so a wide processing group gets its own space.
  for(const group of [...groups].sort((a,b)=>b.width*b.height-a.width*a.height || a.index-b.index)){
    const side=sides[0].area<=sides[1].area?sides[0]:sides[1];
    side.groups.push(group);side.area+=group.width*group.height;
  }
  const bandLimit=Math.max(720,Math.min(1100,spineWidth),...groups.map(group=>group.width));
  for(const side of sides){
    const bands=[];
    for(const group of side.groups.sort((a,b)=>a.index-b.index)){
      let band=bands.at(-1);
      if(!band || band.width+GROUP_GAP+group.width>bandLimit){band={groups:[],width:0,height:0};bands.push(band);}
      band.width+=(band.groups.length?GROUP_GAP:0)+group.width;band.height=Math.max(band.height,group.height);band.groups.push(group);
    }
    let innerY=side.direction<0?anchor.y-BRANCH_GAP:anchor.y+NODE_HEIGHT+BRANCH_GAP;
    for(const band of bands){
      let left=center-band.width/2;
      for(const group of band.groups){
        const ownerY=side.direction<0?innerY-NODE_HEIGHT:innerY;
        if(group.task)positions.set(group.task.id,{x:left-group.minX,y:ownerY});
        for(let index=0;index<group.children.length;index++){
          const local=group.placements[index],y=ownerY+side.direction*local.y;
          positions.set(group.children[index].id,{x:left-group.minX+local.x,y});
        }
        left+=group.width+GROUP_GAP;
      }
      innerY+=side.direction*(band.height+BRANCH_GAP);
    }
  }
  return positions;
}

function placeUnpinnedNodes(nodes, pinnedIds, arranged) {
  if(!pinnedIds.size)return;
  const byId=new Map(nodes.map(node=>[node.id,node])), occupied=nodes.filter(node=>pinnedIds.has(node.id));
  for(const node of nodes){
    if(pinnedIds.has(node.id))continue;
    const owner=byId.get(node.ownerId), planned=arranged.get(node.id), parentPlan=owner && arranged.get(owner.id);
    const origin=owner?{x:owner.x+planned.x-parentPlan.x,y:owner.y+planned.y-parentPlan.y}:{x:node.x,y:node.y};
    const available=point=>Math.abs(point.x)<=POSITION_LIMIT && Math.abs(point.y)<=POSITION_LIMIT && !occupied.some(other=>point.x<other.x+other.width+NODE_GAP && point.x+node.width+NODE_GAP>other.x && point.y<other.y+other.height+NODE_GAP && point.y+node.height+NODE_GAP>other.y);
    let position=origin;
    for(let ring=1;!available(position);ring++){
      const offsets=[];
      for(let y=-ring;y<=ring;y++)for(let x=-ring;x<=ring;x++)if(Math.abs(x)===ring || Math.abs(y)===ring)offsets.push({x,y});
      offsets.sort((a,b)=>Math.hypot(a.x*(NODE_WIDTH+NODE_GAP),a.y*(NODE_HEIGHT+NODE_GAP))-Math.hypot(b.x*(NODE_WIDTH+NODE_GAP),b.y*(NODE_HEIGHT+NODE_GAP)) || b.y-a.y || b.x-a.x);
      position=offsets.map(offset=>({x:origin.x+offset.x*(NODE_WIDTH+NODE_GAP),y:origin.y+offset.y*(NODE_HEIGHT+NODE_GAP)})).find(available) || position;
    }
    node.x=position.x;node.y=position.y;occupied.push(node);
  }
}

function segmentHitsCard(a,b,node,padding=8) {
  let low=0,high=1;
  for(const [axis,size] of [['x','width'],['y','height']]){
    const delta=b[axis]-a[axis], min=node[axis]-padding, max=node[axis]+node[size]+padding;
    if(!delta){if(a[axis]<=min || a[axis]>=max)return false;continue;}
    const t1=(min-a[axis])/delta,t2=(max-a[axis])/delta;
    low=Math.max(low,Math.min(t1,t2));high=Math.min(high,Math.max(t1,t2));
    if(low>=high)return false;
  }
  return low<high;
}

function curveHitsCard(points,node,depth=0,padding=8) {
  const xs=points.map(point=>point.x),ys=points.map(point=>point.y);
  if(Math.max(...xs)<=node.x-padding || Math.min(...xs)>=node.x+node.width+padding || Math.max(...ys)<=node.y-padding || Math.min(...ys)>=node.y+node.height+padding)return false;
  if(depth===8)return true;
  const middle=(a,b)=>({x:(a.x+b.x)/2,y:(a.y+b.y)/2});
  const a=middle(points[0],points[1]),b=middle(points[1],points[2]),c=middle(points[2],points[3]),d=middle(a,b),e=middle(b,c),f=middle(d,e);
  return curveHitsCard([points[0],a,d,f],node,depth+1,padding) || curveHitsCard([f,e,c,points[3]],node,depth+1,padding);
}

function roundedRoute(points,nodes,source,target) {
  const route=[];
  for(const point of points){
    if(route.length && point.x===route.at(-1).x && point.y===route.at(-1).y)continue;
    while(route.length>1){
      const a=route.at(-2),b=route.at(-1),dx=b.x-a.x,dy=b.y-a.y,nx=point.x-b.x,ny=point.y-b.y;
      if(dx*ny!==dy*nx || dx*nx+dy*ny<=0)break;
      route.pop();
    }
    route.push(point);
  }
  const commands=[`M ${route[0].x} ${route[0].y}`];
  for(let index=1;index<route.length-1;index++){
    const before=route[index-1],corner=route[index],after=route[index+1];
    const incoming=Math.hypot(corner.x-before.x,corner.y-before.y),outgoing=Math.hypot(after.x-corner.x,after.y-corner.y);
    let radius=Math.min(32,incoming/2,outgoing/2),entry,exit;
    // Rounding cuts inside the clear route: check the actual curve, not its chords.
    for(let attempt=0;attempt<10;attempt++){
      entry={x:corner.x+(before.x-corner.x)*radius/incoming,y:corner.y+(before.y-corner.y)*radius/incoming};
      exit={x:corner.x+(after.x-corner.x)*radius/outgoing,y:corner.y+(after.y-corner.y)*radius/outgoing};
      const cubic=[entry,{x:entry.x+(corner.x-entry.x)*2/3,y:entry.y+(corner.y-entry.y)*2/3},{x:exit.x+(corner.x-exit.x)*2/3,y:exit.y+(corner.y-exit.y)*2/3},exit];
      if(!nodes.some(node=>curveHitsCard(cubic,node,0,node===source || node===target?0:4)))break;
      radius=attempt===8?0:radius/2;
    }
    commands.push(`L ${entry.x} ${entry.y} Q ${corner.x} ${corner.y} ${exit.x} ${exit.y}`);
  }
  commands.push(`L ${route.at(-1).x} ${route.at(-1).y}`);
  return commands.join(' ');
}

function clearDogleg(start,end,source,target,nodes,horizontal,direction) {
  const channels=new Set(nodes.flatMap(node=>horizontal?[node.y-12,node.y+node.height+12]:[node.x-12,node.x+node.width+12]));
  const candidates=[];
  for(const stub of [18,8])for(const channel of channels){
    const points=horizontal?[start,{x:start.x+direction*stub,y:start.y},{x:start.x+direction*stub,y:channel},{x:end.x-direction*stub,y:channel},{x:end.x-direction*stub,y:end.y},end]:[start,{x:start.x,y:start.y+direction*stub},{x:channel,y:start.y+direction*stub},{x:channel,y:end.y-direction*stub},{x:end.x,y:end.y-direction*stub},end];
    const blocked=points.slice(1).some((point,index)=>nodes.some(node=>!(index===0 && node===source) && !(index===points.length-2 && node===target) && segmentHitsCard(points[index],point,node)));
    if(!blocked)candidates.push({points,length:points.slice(1).reduce((sum,point,index)=>sum+Math.abs(point.x-points[index].x)+Math.abs(point.y-points[index].y),0)});
  }
  candidates.sort((a,b)=>a.length-b.length);
  return candidates[0]?.points;
}

function connector(source, target, kind, nodes, ports={}) {
  const dx=target.x+target.width/2-source.x-source.width/2, dy=target.y+target.height/2-source.y-source.height/2;
  const gapX=Math.abs(dx)-(source.width+target.width)/2, gapY=Math.abs(dy)-(source.height+target.height)/2;
  const horizontal=ports.horizontal ?? (gapX>0 && gapY<=0 || (gapX>0 || gapY<=0) && Math.abs(dx)/(source.width+target.width)>=Math.abs(dy)/(source.height+target.height));
  const direction=ports.direction ?? ((horizontal?dx:dy)>=0?1:-1), offset=ports.offset ?? (kind==='dependency'?8:0);
  const sourceSide=horizontal?(direction>0?'right':'left'):(direction>0?'bottom':'top');
  const targetSide=horizontal?(direction>0?'left':'right'):(direction>0?'top':'bottom');
  const start=horizontal?{x:source.x+(direction>0?source.width:0),y:source.y+source.height/2+offset}:{x:source.x+source.width/2+offset,y:source.y+(direction>0?source.height:0)};
  const end=horizontal?{x:target.x+(direction>0?0:target.width),y:target.y+target.height/2+offset}:{x:target.x+target.width/2+offset,y:target.y+(direction>0?0:target.height)};
  const distance=Math.abs(horizontal?end.x-start.x:end.y-start.y), handle=Math.max(24,Math.min(128,distance/2));
  let points=horizontal?[start,{x:start.x+direction*handle,y:start.y},{x:end.x-direction*handle,y:end.y},end]:[start,{x:start.x,y:start.y+direction*handle},{x:end.x,y:end.y-direction*handle},end];
  let path=`M ${start.x} ${start.y} C ${points[1].x} ${points[1].y}, ${points[2].x} ${points[2].y}, ${end.x} ${end.y}`;
  // Use a nearby clear channel when the actual curve intersects another card.
  if(ports.forceRoute || nodes.some(node=>node!==source && node!==target && curveHitsCard(points,node))){
    const routed=clearDogleg(start,end,source,target,nodes,horizontal,direction);
    if(routed){points=routed;path=roundedRoute(points,nodes,source,target);}
  }
  return {kind,source:source.id,target:target.id,sourceSide,targetSide,start,end,points,path};
}

/** Numbered Graph columns always connect a right output to a left input. */
export function overviewConnector(source,target,nodes) {
  const obstacles=[...nodes.filter(node=>node.id!==source.id && node.id!==target.id),source,target];
  return connector(source,target,'dependency',obstacles,{horizontal:true,direction:1,offset:0,forceRoute:target.x<=source.x+source.width});
}

/** One solved scene supplies the node rectangles and both relationship types. */
export function computeLayerCanvas(project, selection = {}) {
  const state = resolveLayerSelection(project, selection);
  const makeGroup=(task,children,index)=>{
    const placements=[],span=NODE_WIDTH+NODE_GAP;
    if(task && children.length===1)placements.push({x:(index%2?-1:1)*span,y:DIAGONAL_OFFSET});
    else if(task && children.length>=2){
      placements.push({x:-span,y:DIAGONAL_OFFSET},{x:span,y:DIAGONAL_OFFSET});
      if(children.length===3)placements.push({x:0,y:NODE_HEIGHT+NODE_GAP});
    }
    const remaining=children.length-placements.length,columns=remaining<=3?remaining:Math.ceil(Math.sqrt(remaining*NODE_HEIGHT/NODE_WIDTH*1.8));
    for(let child=0;child<remaining;child++){
      const row=Math.floor(child/columns),column=child%columns,count=Math.min(columns,remaining-row*columns);
      placements.push({x:(NODE_WIDTH-rowWidth(count))/2+column*span,y:(task?DIAGONAL_OFFSET+NODE_HEIGHT+NODE_GAP:0)+row*(NODE_HEIGHT+NODE_GAP)});
    }
    const minX=Math.min(0,...placements.map(point=>point.x)),maxX=Math.max(NODE_WIDTH,...placements.map(point=>point.x+NODE_WIDTH));
    return {task,children,index,placements,minX,width:maxX-minX,height:NODE_HEIGHT+Math.max(0,...placements.map(point=>point.y))};
  };
  const groups = state.operations.map((task,index) => {
    const children = processingStepsFor(project,task.id);
    return makeGroup(task,children,index);
  });
  if(state.overviewId === ':unassigned' && state.unassignedProcessing.length)groups.push(makeGroup(null,state.unassignedProcessing,groups.length));
  const arranged=arrangeBranches(state,groups);
  const nodes = [], pinnedIds = new Set();
  const addNode = (task,layer,ownerId=null) => {
    let {x,y}=arranged.get(task.id);
    const saved=project.layout?.layer_positions?.[task.id];
    if(Number.isFinite(saved?.x) && Number.isFinite(saved?.y)){x=saved.x;y=saved.y;pinnedIds.add(task.id);}
    nodes.push({id:task.id,task,layer,ownerId,x,y,width:NODE_WIDTH,height:NODE_HEIGHT});
  };
  for(const task of state.stages)addNode(task,'overview');
  for(const group of groups){
    if(group.task)addNode(group.task,'operation',state.overviewId);
    for(const task of group.children)addNode(task,'processing',group.task?.id);
  }
  placeUnpinnedNodes(nodes,pinnedIds,arranged);
  const byId = new Map(nodes.map(node => [node.id,node])), edges = [];
  const membership = (source,target) => {
    const from = byId.get(source), to = byId.get(target); if(!from || !to)return;
    edges.push(connector(from,to,'membership',nodes));
  };
  for(const task of state.operations)membership(state.overviewId,task.id);
  for(const group of groups)if(group.task)for(const child of group.children)membership(group.task.id,child.id);
  for(const target of nodes)for(const sourceId of target.task.depends_on || []){
    const source = byId.get(sourceId); if(!source)continue;
    edges.push(connector(source,target,'dependency',nodes));
  }
  const points=[...nodes.flatMap(node=>[{x:node.x,y:node.y},{x:node.x+node.width,y:node.y+node.height}]),...edges.flatMap(edge=>edge.points)];
  const left=points.length?Math.min(...points.map(point=>point.x))-MARGIN:0, top=points.length?Math.min(...points.map(point=>point.y))-MARGIN:0;
  const width=points.length?Math.max(...points.map(point=>point.x))+MARGIN-left:1200, height=points.length?Math.max(...points.map(point=>point.y))+MARGIN-top:650;
  return {width,height,bounds:{x:left,y:top,width,height},nodes,edges,state};
}

export function renderIdeasList(project, filter='active', expandedId=null, readOnly=false) {
  const items=project.ideas || [], active=items.filter(item => item.status!=='resolved');
  const visible=items.filter(item => filter==='all' || (filter==='resolved' ? item.status==='resolved' : item.status!=='resolved'));
  const titles=new Map(project.tasks.map(task => [task.id,task.title]));
  const kinds={idea:'Idea',question:'Question',decision:'Decision'}, statuses={open:'Open',deferred:'Later',resolved:'Resolved'};
  return `<div class="ideas-toolbar"><label><span class="sr-only">Show ideas and questions</span><select id="ideas-filter"><option value="active" ${filter==='active'?'selected':''}>To revisit (${active.length})</option><option value="resolved" ${filter==='resolved'?'selected':''}>Resolved (${items.length-active.length})</option><option value="all" ${filter==='all'?'selected':''}>All items (${items.length})</option></select></label>${readOnly?'':`<button class="button" data-action="idea-add">Add item</button>`}</div>
  <div id="ideas-content" class="ideas-content">${visible.length?`<ul class="ideas-list">${visible.map(item => `<li class="idea-row ${item.status==='resolved'?'is-resolved':''}" data-idea-id="${layerEscape(item.id)}">
    <h3><button class="idea-summary" data-action="idea-toggle" data-id="${layerEscape(item.id)}" aria-expanded="${expandedId===item.id}" aria-controls="idea-details-${layerEscape(item.id)}" title="${layerEscape(item.title)}"><span class="idea-title">${layerEscape(item.title)}</span><span class="idea-state">${statuses[item.status]}</span><svg class="icon idea-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg></button></h3>
    <div class="idea-details" id="idea-details-${layerEscape(item.id)}" ${expandedId===item.id?'':'hidden'}>
    <div class="idea-meta"><span class="idea-kind">${kinds[item.kind]}</span>${item.related_task_id?`<button class="idea-link" data-action="idea-link" data-id="${layerEscape(item.id)}" title="Open linked step">${layerEscape(titles.get(item.related_task_id))}</button>`:'<span>Project-wide</span>'}</div>
    ${item.notes?`<p class="idea-notes">${layerEscape(item.notes)}</p>`:''}
    ${item.revisit_when?`<p class="idea-revisit"><strong>Revisit</strong><span>${layerEscape(item.revisit_when)}</span></p>`:''}
    ${item.resolution?`<p class="idea-resolution"><strong>Outcome</strong><span>${layerEscape(item.resolution)}</span></p>`:''}
    <div class="idea-row-actions">${readOnly?'':`<button data-action="idea-edit" data-id="${layerEscape(item.id)}" aria-label="Edit ${layerEscape(item.title)}">Edit</button>`}${readOnly?'':`<button data-action="idea-delete" data-id="${layerEscape(item.id)}" aria-label="Remove ${layerEscape(item.title)}">Remove</button>`}</div>
    </div>
  </li>`).join('')}</ul>`:`<div class="ideas-empty"><p>${filter==='resolved'?'No resolved items.':filter==='active'&&items.length?'Everything has been resolved.':'No ideas or questions yet.'}</p><p>${filter==='resolved'?'Resolved questions and their outcomes will appear here.':readOnly?'No items saved in this view.':'Add a question, idea, or decision to revisit later.'}</p></div>`}</div>`;
}

export function renderLayeredView(project,selection={},canUndo=false,canRedo=false,readOnly=false) {
  const scene=computeLayerCanvas(project,selection), state=scene.state;
  const visibleIds=new Set(scene.nodes.map(node => node.id)), numbers=new Map(stepOutline(project).map(row => [row.task.id,row.number]));
  const hasUnassigned=state.unassigned.length+state.unassignedProcessing.length>0;
  const nodeMarkup=scene.nodes.map(node => {
    const {task,layer}=node, selected=state.selectedId===task.id;
    const count=layer==='overview'?operationsFor(project,task.id).length:layer==='operation'?processingStepsFor(project,task.id).length:task.records?.length || 0;
    const suffix=(layer==='overview'?'operation':layer==='operation'?'step':'record')+(count===1?'':'s');
    const hiddenDependencies=(task.depends_on || []).filter(id => !visibleIds.has(id));
    const context=layer==='overview'&&state.overviewId===task.id;
    return `<button class="flow-node ${layer}-card ${selected?'is-active':''} ${context?'is-context':''}" data-action="layer-${layer}" data-id="${layerEscape(task.id)}" data-layer="${layer}" data-x="${node.x}" data-y="${node.y}" style="left:${node.x}px;top:${node.y}px;width:${node.width}px;height:${node.height}px" aria-pressed="${selected}" title="${layerEscape(task.title)}"><span class="flow-node-kind">${layer==='overview'?`Overview · Step ${layerEscape(numbers.get(task.id) || '')}`:layerEscape(layerKind(task))}</span><strong>${layerEscape(task.title)}</strong><span class="flow-node-bottom">${layerStatus(task)}<span>${count} ${suffix}</span></span>${hiddenDependencies.length?`<span class="flow-offscope" title="${hiddenDependencies.length} prerequisite${hiddenDependencies.length===1?'':'s'} outside this view" aria-label="${hiddenDependencies.length} prerequisites outside this view">+${hiddenDependencies.length} ↗</span>`:''}</button>`;
  }).join('');
  const edgeMarkup=scene.edges.map(edge => edge.kind==='membership'
    ? `<path class="layer-membership-path" data-source="${layerEscape(edge.source)}" data-target="${layerEscape(edge.target)}" d="${edge.path}"/>`
    : `<g class="layer-dependency" data-source="${layerEscape(edge.source)}" data-target="${layerEscape(edge.target)}"><path class="layer-dependency-path" data-source="${layerEscape(edge.source)}" data-target="${layerEscape(edge.target)}" d="${edge.path}" marker-end="url(#layer-dependency-arrow)"/><path class="layer-dependency-hit" data-action="layer-edge" data-source="${layerEscape(edge.source)}" data-target="${layerEscape(edge.target)}" d="${edge.path}" role="button" tabindex="0" aria-label="Dependency from ${layerEscape(project.tasks.find(task=>task.id===edge.source)?.title || edge.source)} to ${layerEscape(project.tasks.find(task=>task.id===edge.target)?.title || edge.target)}"/></g>`).join('');
  return `<div class="layer-canvas-toolbar"><div class="layer-add-tools" aria-label="${readOnly?'Research context':'Add research steps'}">${readOnly?'':`<button data-action="layer-add-overview"><i class="layer-key overview-key"></i>+ Overview</button>`}${readOnly?'':`<button data-action="layer-add-operation"><i class="layer-key operation-key"></i>+ Operation</button>`}${readOnly?'':`<button data-action="layer-add-processing"><i class="layer-key processing-key"></i>+ Processing</button>`}${hasUnassigned?`<button class="unassigned-card ${state.overviewId===':unassigned'?'is-active':''}" data-action="layer-overview" data-id=":unassigned" aria-pressed="${state.overviewId===':unassigned'}">Unassigned (${state.unassigned.length+state.unassignedProcessing.length})</button>`:''}</div><div class="layer-camera-tools">${readOnly?'':`<button data-action="undo" aria-label="Undo" ${canUndo?'':'disabled'}>↶</button>`}${readOnly?'':`<button data-action="redo" aria-label="Redo" ${canRedo?'':'disabled'}>↷</button>`}${readOnly?'':'<span class="layer-tool-divider"></span>'}${readOnly?'':`<button data-action="layer-arrange" title="Arrange visible cards">Arrange</button>`}<button data-action="layer-fit">Fit</button><button data-action="layer-zoom-out" aria-label="Zoom out">−</button><button data-action="layer-zoom-reset" id="layer-zoom-level" aria-label="Reset zoom">100%</button><button data-action="layer-zoom-in" aria-label="Zoom in">+</button></div></div>
  <div id="layer-canvas" class="layer-canvas" tabindex="-1" aria-label="Research layers canvas"><div id="layer-world" class="layer-world" data-width="${scene.width}" data-height="${scene.height}" data-bounds-x="${scene.bounds.x}" data-bounds-y="${scene.bounds.y}" data-bounds-width="${scene.bounds.width}" data-bounds-height="${scene.bounds.height}" style="width:${scene.width}px;height:${scene.height}px"><svg class="layer-edges" width="${scene.width}" height="${scene.height}" viewBox="${scene.bounds.x} ${scene.bounds.y} ${scene.width} ${scene.height}" style="left:${scene.bounds.x}px;top:${scene.bounds.y}px" aria-label="Membership and dependency connections"><defs><marker id="layer-dependency-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#68798c"/></marker></defs>${edgeMarkup}</svg>${scene.nodes.length?'':`<p class="flow-row-empty" style="top:76px;left:${MARGIN}px">${readOnly?'No overview steps saved.':'Add an overview step to start your workflow.'}</p>`}${nodeMarkup}</div></div>
  <footer class="layer-canvas-footer"><div class="layer-legend"><span><i class="legend-membership"></i>Part of</span><span><i class="legend-dependency"></i>Dependency</span></div><span>${readOnly?'Click for details · Drag empty space to pan':'Drag cards to arrange · Click for details · Drag empty space to pan'}</span></footer>`;
}

/** Evidence belongs in the inspector, leaving the graph available for navigation. */
export function renderMethodDetails(task,recordId=null,readOnly=false) {
  if(!task)return '<p class="method-missing">Select an operation or processing step.</p>';
  const records=task.records || [], record=records.find(item=>item.id===recordId) || records.find(item=>item.id===task.selected_record_id) || records.at(-1);
  const source=record || task;
  return `<div class="method-details"><div class="method-detail-heading"><span>${record?'Recorded work':'Planned method'}</span>${readOnly?'':`<button class="text-button" data-action="layer-record" data-id="${layerEscape(task.id)}">+ Record work</button>`}</div><section class="method-detail-section"><h3>${record?'Method performed':'Method'}</h3>${layerText(source.method)}${source.parameters?`<pre class="method-parameters">${layerEscape(source.parameters)}</pre>`:''}</section><section class="method-detail-section"><h3>Inputs</h3>${layerFiles(source.inputs)}</section><section class="method-detail-section"><h3>Outputs</h3>${layerFiles(source.outputs)}</section><section class="method-detail-section"><h3>${record?'Changes & observations':'Expected outcome'}</h3>${layerText(record?record.changes:task.goal)}</section><section class="method-detail-section"><h3>Rationale</h3>${layerText(source.rationale)}</section>${record?`<details class="record-technical"><summary>Implementation & evidence</summary><dl><dt>Code / command</dt><dd>${layerEscape(record.code || 'Not recorded')}</dd><dt>Software / environment</dt><dd>${layerEscape(record.software || 'Not recorded')}</dd><dt>Performed at</dt><dd>${layerEscape(record.performed_at || 'Not recorded')}</dd><dt>Recorded at</dt><dd>${layerEscape(record.recorded_at)}</dd><dt>Notes / checks</dt><dd>${layerEscape(record.notes || 'Not recorded')}</dd></dl></details>`:'<p class="record-disclaimer">No work recorded. Planning a step does not execute it.</p>'}<section class="record-history" aria-label="Work history"><div class="record-history-heading"><h3>Work history</h3><span>${records.length}</span></div>${records.length?[...records].reverse().map((item,index)=>`<button class="record-entry ${record?.id===item.id?'is-active':''}" data-action="layer-record-select" data-id="${layerEscape(item.id)}" data-task-id="${layerEscape(task.id)}" aria-pressed="${record?.id===item.id}"><span><strong>Record ${records.length-index}</strong><span class="record-state">${layerEscape(item.status)}</span></span><small>${layerEscape(layerDate(item.performed_at || item.recorded_at))}</small><span class="record-description">${layerEscape(item.method)}</span>${task.selected_record_id===item.id?'<span class="chosen-record">Selected result</span>':''}</button>`).join(''):'<p class="method-missing">No recorded attempts.</p>'}${!readOnly&&record&&task.selected_record_id!==record.id?`<button class="text-button choose-result" data-action="layer-use-record" data-id="${layerEscape(record.id)}" data-task-id="${layerEscape(task.id)}">Select this result</button>`:''}</section></div>`;
}
