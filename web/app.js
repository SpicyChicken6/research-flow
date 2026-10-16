import { readAccessToken } from './connection.mjs';
import { STATUS, clone, validateProject, addDependency, addBranchDependency, removeTask, autoLayout, toYaml, insertBlankStep, childrenOf, descendantIds, ancestorIds, taskSize, setParent, stepOutline, setStepNumber, overviewStepLayout, dependencyPathIds, dependencyPathEdges } from './model.mjs';
import { taskLayer, overviewSteps, overviewGraph, operationsFor, processingStepsFor, addOperationRecord, selectOperationRecord } from './model.mjs';
import { addIdea, updateIdea, removeIdea } from './model.mjs';
import { resolveLayerSelection, computeLayerCanvas, renderLayeredView, renderMethodDetails, renderIdeasList, overviewConnector } from './layers.mjs';
// BEGIN LOGO MOTION — presentation only; no project or history state.
const LOGO_MOTION = Object.freeze({loadDuration:720, viewDuration:480});
function createLogoMotion(svg) {
  const dots = svg?.querySelector('[data-logo-dots]');
  const doc = svg?.ownerDocument;
  const win = doc?.defaultView;
  const preference = win?.matchMedia?.('(prefers-reduced-motion: reduce)');
  let active = null;
  let disposed = false;

  function stop() {
    if (!active) return;
    const animation = active;
    active = null;
    animation.onfinish = null;
    animation.oncancel = null;
    animation.cancel();
  }
  function play(reason = 'view') {
    // Rapid changes finish the current turn instead of stacking or restarting.
    // None of this blocks or delays the actual view change.
    if (disposed || !dots || typeof dots.animate !== 'function' ||
        doc.hidden || preference?.matches || active) return false;
    try {
      const animation = dots.animate([
        {transform:'rotate(0deg)'},
        {transform:'rotate(360deg)'}
      ], {
        duration:reason === 'load' ? LOGO_MOTION.loadDuration : LOGO_MOTION.viewDuration,
        easing:'cubic-bezier(0.4, 0, 0.2, 1)',
        iterations:1,
        fill:'none'
      });
      animation.id = 'research-flow-logo-turn';
      active = animation;
      animation.onfinish = () => {
        if (active === animation) active = null;
        animation.onfinish = null;
        animation.oncancel = null;
        // A full turn and the original pose are identical. Release the effect.
        animation.cancel();
      };
      animation.oncancel = () => { if (active === animation) active = null; };
      return true;
    } catch (_) {
      // A missing/failed animation must never interfere with the editor.
      return false;
    }
  }
  function onPreference() { if (preference?.matches) stop(); }
  function onVisibility() { if (doc.hidden) stop(); }
  preference?.addEventListener?.('change', onPreference);
  doc?.addEventListener('visibilitychange', onVisibility);
  win?.addEventListener('pagehide', stop);
  return {
    play, stop,
    destroy() {
      disposed = true;
      stop();
      preference?.removeEventListener?.('change', onPreference);
      doc?.removeEventListener('visibilitychange', onVisibility);
      win?.removeEventListener('pagehide', stop);
    }
  };
}
// END LOGO MOTION

const paths = {
  'view-layers': '<path d="m12 3 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 16l9 5 9-5"/>',
  'view-graph': '<circle cx="5" cy="12" r="3"/><circle cx="18" cy="5" r="3"/><circle cx="18" cy="19" r="3"/><path d="m7.6 10.6 7.8-4.2m-7.8 7 7.8 4.2"/>',
  'view-list': '<rect x="3" y="4" width="4" height="4" rx=".5"/><rect x="3" y="10" width="4" height="4" rx=".5"/><rect x="3" y="16" width="4" height="4" rx=".5"/><path d="M11 6h10M11 12h10M11 18h10"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  chevron: '<path d="m8 10 4 4 4-4"/>',
  up: '<path d="m6 14 6-6 6 6"/>',
  down: '<path d="m6 10 6 6 6-6"/>',
  checklist: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="m8 12 3 3 5-6"/>',
  minus: '<path d="M5 12h14"/>',
  map: '<rect x="3" y="4" width="18" height="16" rx="2"/><rect x="7" y="8" width="6" height="5" rx="1"/><path d="M13 10h4v6"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4M12 17h.01"/>',

  panel: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
  sidebar: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
  focus: '<path d="M8 3H3v5M16 3h5v5M21 16v5h-5M8 21H3v-5"/><circle cx="12" cy="12" r="3"/>',
  previous: '<path d="m14 6-6 6 6 6"/>',
  next: '<path d="m10 6 6 6-6 6"/>',
  note: '<path d="M5 3h14v14l-4 4H5zM15 21v-5h4M8 8h8M8 12h6"/>',
  graph: '<rect x="2" y="4" width="6" height="5" rx="1"/><rect x="16" y="4" width="6" height="5" rx="1"/><rect x="9" y="16" width="6" height="5" rx="1"/><path d="M5 9v3h14V9M12 12v4"/>',
  file: '<path d="M14 2H5v20h14V7zM14 2v6h5M8 12h8M8 16h6"/>',
  folder: '<path d="M3 6h7l2 2h9v12H3zM3 6V4h7l2 2"/>',
  code: '<path d="m8 6-6 6 6 6m8-12 6 6-6 6M14 3l-4 18"/>',
  save: '<path d="M4 3h14l3 3v15H3V3h1zM7 3v6h10V3M7 21v-8h10v8"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
  layout: '<rect x="3" y="3" width="6" height="6" rx="1"/><rect x="15" y="3" width="6" height="6" rx="1"/><rect x="15" y="15" width="6" height="6" rx="1"/><path d="M9 6h6M6 9v9h9"/>',
  fit: '<path d="M3 8V3h5M16 3h5v5M21 16v5h-5M8 21H3v-5"/>',
  undo: '<path d="m9 5-6 6 6 6M3 11h10a7 7 0 0 1 7 7"/>',
  redo: '<path d="m15 5 6 6-6 6m6-6H11a7 7 0 0 0-7 7"/>',
  edit: '<path d="m15 4 5 5M4 15 15 4a3.5 3.5 0 0 1 5 5L9 20l-6 1z"/>',
  arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  link: '<path d="m9 8 3-3a5 5 0 0 1 7 7l-3 3m-1 1-3 3a5 5 0 0 1-7-7l3-3M8 16l8-8"/>',
  trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  branch: '<circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="5" r="2"/><path d="M6 7v10M18 7c0 7-12 3-12 10"/>',
};

const NODE_W = 240, NODE_H = 148;
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const esc = (value = '') => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.graph}</svg>`;
const statusOptions = status => Object.entries(STATUS).map(([key, value]) => `<option value="${key}" ${key === status ? 'selected' : ''}>${value.label}</option>`).join('');
// Keep a pristine copy, not a serialization of the currently rendered controls.
const portable = location.protocol === 'file:' || window.RESEARCH_FLOW_PREVIEW;
const portableTemplate = portable ? '<!doctype html>\n' + document.documentElement.outerHTML : null;
let project = ensurePositions(validateProject(JSON.parse($('#initial-project').textContent)));
let baseline = JSON.stringify(project), revision = null, mode = 'loading', filePath = 'project.yaml';
let selected = null, selectedEdge = null, inspectorTab = 'plan', focusMode = false, view = 'graph';
let layerSelection = {}, recordingTaskId = null;
let layerCamera = {x:0,y:0,zoom:1,autoFit:true}, layerPointer = null;
let layerClickSuppressedUntil = 0;
let ideasOpen = false, ideasFilter = 'active', expandedIdeaId = null, editingIdeaId = null, deletingIdeaId = null;
let stageCache = null, stageProject = null;
let graphCache = null, graphProject = null;
let pointer = null, connectFrom = null, mapOpen = true;
let pendingDeletion = null;
let lastNodeClick = null;
// Disclosure state belongs to this view, never to the project file.
const collapsedBranches = new Set();
let dependencyBundles = new Map();
let transform = {x:40, y:140, zoom:1}, miniBounds = null;
let miniPointer = null, miniClick = null;
let history = [], future = [], lastGroup = '', groupTime = 0;
let busy = false, conflict = false, serverError = false, pollBusy = false;
let copyDownloaded = false, inspectorSelection = null;
let previewWarning = null;
const logoMotion = createLogoMotion($('.brand-logo'));
let lastLogoView = null;
const dirty = () => JSON.stringify(project) !== baseline;
const currentTask = () => project.tasks.find(t => t.id === selected);
function graphDocument() {
  if (graphProject !== project) {
    const projection=overviewGraph(project),byId=new Map(projection.tasks.map(task=>[task.id,task]));
    graphCache={...projection,tasks:stepOutline(project).map(({task})=>byId.get(task.id)).filter(Boolean)};
    graphProject=project;
  }
  return graphCache;
}
function stagedLayout() {
  if (stageProject !== project) { stageCache = overviewStepLayout(project); stageProject = project; }
  return stageCache;
}
const positionOf = id => stagedLayout().positions[id] || {x:0, y:0};
const edgeExists = key => { if (!key) return false; const [a,b] = key.split('|'); return project.tasks.some(t => t.id === b && t.depends_on.includes(a)); };
function ensurePositions(doc) {
  if(!doc.tasks.length)return doc;
  if(doc.tasks.every(t=>!doc.layout.positions[t.id]))return autoLayout(doc);
  const arranged=autoLayout(doc),byId=new Map(doc.tasks.map(t=>[t.id,t]));
  const filling=new Set();
  function fill(task) {
    if(doc.layout.positions[task.id]||filling.has(task.id))return;
    filling.add(task.id);
    const size=taskSize(task),parent=byId.get(task.parent_id);if(parent)fill(parent);
    let p=parent?{x:doc.layout.positions[parent.id].x+(taskSize(parent).width-size.width)/2,y:doc.layout.positions[parent.id].y+taskSize(parent).height+86}:{...arranged.layout.positions[task.id]};
    const collides=()=>doc.tasks.some(t=>{const q=doc.layout.positions[t.id],ts=taskSize(t);return q&&p.x<q.x+ts.width+26&&p.x+size.width+26>q.x&&p.y<q.y+ts.height+26&&p.y+size.height+26>q.y;});
    while(collides())p.y+=size.height+50;
    doc.layout.positions[task.id]={x:Math.round(p.x),y:Math.round(p.y)};
    filling.delete(task.id);
  }
  doc.tasks.forEach(fill);return doc;
}
function toast(message, error = false) {
  const el = document.createElement('div'); el.className = `toast${error ? ' error' : ''}`; el.textContent = message;
  $('#toasts').append(el); setTimeout(() => el.remove(), error ? 6500 : 3200);
}
function remember(before, group = '') {
  if (!group || group !== lastGroup || Date.now() - groupTime > 900) {
    history.push({document:before});
    if (history.length > 70) history.shift();
  }
  lastGroup = group; groupTime = Date.now(); future = [];
}
function change(fn, {group='', inspector=true, validate=false, graph=true} = {}) {
  const before = clone(project), next = clone(project);
  try {
    const result = fn(next) || next;
    if (validate) validateProject(result);
    if (JSON.stringify(before) === JSON.stringify(result)) return true;
    remember(before, group); project = result; refresh(inspector,graph); return true;
  } catch(error) { toast(error.message, true); return false; }
}
function restoreHistory(from,to) {
  if(!from.length)return;
  const entry=from.pop();
  to.push({document:clone(project)});
  project=entry.document;
  lastGroup='';refresh();if(view==='graph')fitGraph();
}
function undo() { restoreHistory(history,future); }
function redo() { restoreHistory(future,history); }
function focusedIds() {
  const t=currentTask(); if(!focusMode || !t)return null;
  const branch=new Set([t.id,...descendantIds(graphDocument(),t.id)]), ids=new Set(branch);
  for(const node of graphDocument().tasks) {
    if(branch.has(node.id))node.depends_on.forEach(id=>ids.add(id));
    if(node.depends_on.some(id=>branch.has(id)))ids.add(node.id);
  }
  ancestorIds(graphDocument(),t.id).forEach(id=>ids.add(id));
  return ids;
}
function representative(id) {
  let result=id;
  for(const parent of ancestorIds(graphDocument(),id))if(collapsedBranches.has(parent))result=parent;
  return result;
}
function visibleTasks() {
  const ids=focusedIds();
  return graphDocument().tasks.filter(t=>(!ids || ids.has(t.id)) && representative(t.id)===t.id);
}
function revealPath(id) {ancestorIds(graphDocument(),id).forEach(parent=>collapsedBranches.delete(parent));}
function toggleBranch(id) {
  const kids=childrenOf(graphDocument(),id);if(!kids.length)return;
  const focusIds=focusedIds();
  // A dependency neighbor's children may be outside the focused branch.
  // Expanding it makes that branch the focus instead of showing a dead control.
  if(focusIds&&kids.some(t=>!focusIds.has(t.id))) {
    selected=id;selectedEdge=null;collapsedBranches.delete(id);revealPath(id);
    refresh();fitGraph();return;
  }
  if(collapsedBranches.has(id))collapsedBranches.delete(id);
  else {
    collapsedBranches.add(id);
    if(selected && descendantIds(graphDocument(),id).has(selected)){selected=id;selectedEdge=null;}
    if(selectedEdge){const [a,b]=selectedEdge.split('|');if(representative(a)!==a||representative(b)!==b)selectedEdge=null;}
  }
  refresh();
}
function reparent(id,parent) {
  try {
    const source=clone(project);
    if(view==='graph')source.tasks.find(t=>t.id===id).layer='overview';
    const next=setParent(source,id,parent);
    revealPath(parent); if(parent)collapsedBranches.delete(parent);
    if(change(()=>next,{validate:true})) {revealPath(id);refresh();keepSelectedVisible();}
  }catch(error){toast(error.message,true);renderInspector();}
}
function revealBundle(key) {
  const edges=dependencyBundles.get(key);if(!edges?.length)return;
  for(const {source,target} of edges){revealPath(source);revealPath(target);}
  focusMode=false;selected=null;selectedEdge=`${edges[0].source}|${edges[0].target}`;
  showInspector();switchView('graph');refresh();fitGraph();
}

function showInspector() { ideasOpen=false; $('#ideas-panel').hidden=true; $('.canvas-column').inert=false; $('#inspector').hidden = false; }
function closeInspector() { $('#inspector').hidden = true; renderHeader(); }
function clearSelection() { selected=null; selectedEdge=null; focusMode=false; connectFrom=null; closeInspector(); refresh(); }
function navigateTo(id) {
  if (!project.tasks.some(t => t.id === id)) return;
  if(view==='layers'||(view==='graph'&&taskLayer(project.tasks.find(t=>t.id===id))!=='overview')){switchView('layers');layerSelectTask(id);return;}
  if (selected !== id) inspectorTab = 'plan';
  revealPath(id); selected=id; selectedEdge=null; connectFrom=null; showInspector(); refresh();
  if (focusMode) fitGraph(); else keepSelectedVisible();
}
function keepSelectedVisible(id=selected) {
  const task=graphDocument().tasks.find(t=>t.id===id);
  if (view !== 'graph' || !task || taskLayer(task)!=='overview') return;
  const p = positionOf(id), c = $('#canvas'), {width:NODE_W,height:NODE_H}=taskSize(task);
  const available = matchMedia('(max-width:700px)').matches && !$('#inspector').hidden ? Math.max(0, c.clientWidth-$('#inspector').offsetWidth) : c.clientWidth;
  if (available < 200) return; // Mobile details overlay must not move the user's canvas.
  const x=p.x*transform.zoom+transform.x, y=p.y*transform.zoom+transform.y;
  if (x < 30 || x+NODE_W*transform.zoom > available-30 || y < 80 || y+NODE_H*transform.zoom > c.clientHeight-80) {
    transform.x=available/2-(p.x+NODE_W/2)*transform.zoom;
    transform.y=c.clientHeight/2-(p.y+NODE_H/2)*transform.zoom;
    applyTransform();
  }
}
function renderHeader() {
  const logoView = view === 'list' ? 'list' : focusMode ? 'focus' : 'overview';
  if (lastLogoView !== null && logoView !== lastLogoView) logoMotion.play('view');
  lastLogoView = logoView;
  if (document.activeElement !== $('#project-title')) $('#project-title').value=project.project.name || '';
  document.title = `${project.project.name || 'Untitled project'} · Research Flow`;
  const label = busy ? 'Saving…' : mode === 'loading' ? 'Connecting…' : mode === 'error' ? 'File unavailable' : conflict ? 'File changed' : dirty() ? 'Unsaved changes' : mode === 'server' ? (previewWarning ? 'Saved · preview unavailable' : 'Saved') : copyDownloaded ? 'Copy downloaded' : 'In this tab';
  $('#save-state').innerHTML = `${dirty() ? '<span class="save-dot dirty"></span>' : ''}${label}`;
  $('#save-state').title = mode === 'server' ? (previewWarning || filePath) : 'Preview changes live in this tab. Save copy downloads a reopenable HTML with your edits.';
  $('#save-button').textContent = busy ? 'Saving…' : mode === 'server' ? 'Save' : 'Save copy';
  $('#save-button').title = mode === 'server' ? (previewWarning ? 'Retry saving the SVG preview · ⌘/Ctrl S' : 'Save workflow and SVG preview · ⌘/Ctrl S') : 'Download an editable HTML copy of this project · ⌘/Ctrl S';
  $('#save-button').disabled = busy || ['loading','error'].includes(mode) || (mode === 'server' && (conflict || (!dirty() && !previewWarning)));
  $('#add-button').disabled = ['loading','error'].includes(mode) || project.tasks.length>=500;
  $('#undo-button').disabled = !history.length; $('#redo-button').disabled = !future.length;
  $('#focus-button').hidden = !currentTask() || view !== 'graph';
  $('#focus-button').classList.toggle('focus-active', focusMode);
  $('#focus-button').setAttribute('aria-pressed', String(focusMode));
  $('#overview-button').classList.toggle('active', !focusMode && view === 'graph');
  $('#overview-button').setAttribute('aria-pressed', String(!focusMode && view === 'graph'));
  $('#ideas-panel').hidden=!ideasOpen;
  $('#ideas-button').classList.toggle('active',ideasOpen);
  $('#ideas-button').setAttribute('aria-expanded',String(ideasOpen));
  $('.canvas-column').inert=ideasOpen&&matchMedia('(max-width:700px)').matches;
  $('#details-button').hidden = !currentTask() && !selectedEdge;
  $('#details-button').classList.toggle('active', !$('#inspector').hidden);
  $('#details-button').setAttribute('aria-expanded', String(!$('#inspector').hidden));
  $('#list-button').classList.toggle('active', view === 'list');
  $('#list-button').setAttribute('aria-pressed', String(view === 'list'));
  $('#layers-button').classList.toggle('active', view === 'layers');
  $('#layers-button').setAttribute('aria-pressed', String(view === 'layers'));
  $('#arrange-button').hidden = view !== 'graph';
  const count=visibleTasks().length, total=view==='graph'?graphDocument().tasks.length:project.tasks.length;
  $('#view-context').textContent = view==='graph' ? `${count<total?`${count} of `:''}${total} overview step${total===1?'':'s'}` : `${total} step${total===1?'':'s'}`;
  const mo=$('#map-option'); mo.innerHTML = `${icon('map')}${mapOpen ? 'Hide' : 'Show'} minimap`; mo.setAttribute('aria-pressed',String(mapOpen));
  $('[data-action="layout"]').disabled = view !== 'graph';
}
function edgeGeometry(source,target) {
  const nodes=visibleTasks().map(task=>({id:task.id,...positionOf(task.id),...taskSize(task)}));
  const edge=overviewConnector(nodes.find(node=>node.id===source),nodes.find(node=>node.id===target),nodes);
  return {d:edge.path,x:(edge.start.x+edge.end.x)/2,y:(edge.start.y+edge.end.y)/2};
}
function hierarchyPath(parent,child) {
  const a=positionOf(parent),b=positionOf(child);
  const pa=taskSize(graphDocument().tasks.find(t=>t.id===parent)),ch=taskSize(graphDocument().tasks.find(t=>t.id===child));
  if(Math.abs(a.x-b.x)<Math.max(pa.width,ch.width)) {
    // A shared side gutter keeps sibling branches out of intervening cards.
    const gutter=Math.min(a.x,b.x)-14;
    return `M ${a.x} ${a.y+pa.height-20} H ${gutter} V ${b.y+20} H ${b.x}`;
  }
  const sx=a.x+pa.width/2,sy=a.y+pa.height,tx=b.x+ch.width/2,ty=b.y;
  const middle=(sy+ty)/2;
  return `M ${sx} ${sy} C ${sx} ${middle}, ${tx} ${middle}, ${tx} ${ty}`;
}
function visibleStageFrames() {
  const tasks=visibleTasks(); if (!tasks.length) return [];
  const shown=new Set(tasks.map(t=>t.id));
  const top=Math.min(...tasks.map(t=>positionOf(t.id).y))-72;
  const bottom=Math.max(...tasks.map(t=>positionOf(t.id).y+taskSize(t).height))+24;
  return stagedLayout().stages.filter(stage=>stage.taskIds.some(id=>shown.has(id)))
    .map(stage=>({...stage,y:top,height:bottom-top}));
}
function renderStages() {
  $('#stages').innerHTML=visibleStageFrames().map(stage=>
    `<section class="stage-column" data-stage="${stage.index}" aria-label="${esc(stage.label)}" style="left:${stage.x}px;top:${stage.y}px;width:${stage.width}px;height:${stage.height}px"><h2>${esc(stage.label)}</h2></section>`).join('');
}
function renderEdges() {
  const shown=new Set(visibleTasks().map(t=>t.id));dependencyBundles=new Map();
  const relatedEdges=selected&&!selectedEdge ? dependencyPathEdges(graphDocument(),selected) : new Set();
  let html=`<defs><marker id="arrowhead" viewBox="0 0 8 8" refX="10" refY="4" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L8 4L0 8" fill="#91a1b6"/></marker><marker id="selected-arrow" viewBox="0 0 8 8" refX="10" refY="4" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L8 4L0 8" fill="#276cdb"/></marker></defs>`;
  for(const t of graphDocument().tasks) {
    if(!t.parent_id||!shown.has(t.id)||!shown.has(t.parent_id))continue;
    const parent=graphDocument().tasks.find(p=>p.id===t.parent_id),d=hierarchyPath(t.parent_id,t.id);
    html+=`<g><path class="hierarchy-path ${[t.id,t.parent_id].includes(selected)?'related':''}" d="${d}"/><path class="hierarchy-hit" d="${d}" data-hierarchy="${esc(t.id)}" role="button" tabindex="0" aria-label="${esc(t.title)} belongs to ${esc(parent.title)}"><title>Part of: ${esc(parent.title)} — not a dependency</title></path></g>`;
  }
  const grouped=new Map();
  for(const t of graphDocument().tasks)for(const dep of t.depends_on) {
    const a=representative(dep),b=representative(t.id);
    if(a===b||!shown.has(a)||!shown.has(b))continue;
    const key=`${a}|${b}`;if(!grouped.has(key))grouped.set(key,[]);
    grouped.get(key).push({source:dep,target:t.id});
  }
  for(const [key,edges] of grouped) {
    const [a,b]=key.split('|'),g=edgeGeometry(a,b);
    const isBundle=edges.some(e=>e.source!==a||e.target!==b);
    if(isBundle) {
      dependencyBundles.set(key,edges);
      const label=`${edges.length} hidden link${edges.length===1?'':'s'}`;
      const desc=edges.map(e=>`${graphDocument().tasks.find(t=>t.id===e.source).title} → ${graphDocument().tasks.find(t=>t.id===e.target).title}`).join('; ');
      html+=`<g><path class="edge-path bundled ${edges.some(e=>relatedEdges.has(`${e.source}|${e.target}`))?'related':''}" d="${g.d}" marker-end="url(#arrowhead)"/><path class="edge-hit" d="${g.d}" data-bundle="${esc(key)}" role="button" tabindex="0" aria-label="Reveal ${label}: ${esc(desc)}"><title>${esc(desc)}</title></path><g class="bundle-label" data-bundle="${esc(key)}" role="button" tabindex="0" aria-label="Reveal ${label}"><rect x="${g.x-42}" y="${g.y-9}" width="84" height="18" rx="4"/><text x="${g.x}" y="${g.y+3}">${label}</text></g></g>`;
    } else {
      const source=graphDocument().tasks.find(t=>t.id===a),target=graphDocument().tasks.find(t=>t.id===b),chosen=key===selectedEdge,related=relatedEdges.has(key);
      html+=`<g><path class="edge-path ${chosen?'selected':related?'related':''}" d="${g.d}" marker-end="url(#${chosen?'selected-arrow':'arrowhead'})"/><path class="edge-hit" d="${g.d}" data-edge="${esc(key)}" tabindex="0" role="button" aria-label="Connection from ${esc(source.title)} to ${esc(target.title)}"><title>${esc(source.title)} → ${esc(target.title)} (dependency)</title></path></g>`;
    }
  }
  $('#edges').innerHTML=html;
}
function renderGraph() {
  const shown=new Set(visibleTasks().map(t=>t.id));
  const related=selected&&!selectedEdge ? dependencyPathIds(graphDocument(),selected) : new Set();
  renderStages();
  $('#nodes').innerHTML=graphDocument().tasks.map(t=>{
    const p=positionOf(t.id),size=taskSize(t),active=selected===t.id&&!selectedEdge,children=childrenOf(graphDocument(),t.id),collapsed=collapsedBranches.has(t.id)||children.some(c=>!shown.has(c.id));
    const childLabel=children.length===1?'1 child':`${children.length} children`;
    return `<article class="task-node ${t.parent_id?'child-node':''} ${active?'selected':related.has(t.id)?'related':''}" ${shown.has(t.id)?'':'hidden'} data-id="${esc(t.id)}" data-status="${esc(t.status)}" style="left:${p.x}px;top:${p.y}px;width:${size.width}px;height:${size.height}px" tabindex="0" aria-label="${esc(t.title)}, ${STATUS[t.status].label}${t.parent_id?', child step':''}" aria-roledescription="workflow step">
    <button class="port in" data-port="in" data-id="${esc(t.id)}" aria-label="Input for ${esc(t.title)}" title="Add an incoming dependency"></button>
    <div class="task-node-header"><span class="status-pill"><span class="status-dot ${esc(t.status)}"></span>${STATUS[t.status].label}</span></div>
    <h3 title="Double-click to rename" class="${t.title==='Untitled step'?'untitled':''}">${esc(t.title||'Untitled step')}</h3>
    <div class="node-meta"><p class="node-goal ${!t.goal?'placeholder':''}">${esc(t.goal || (t.title==='Untitled step'?'Click to name this step':''))}</p></div>
    ${t.outputs.length?`<div class="node-output" title="${esc(`Outputs: ${t.outputs.join(', ')}`)}">${icon('file')}<span>${esc(t.outputs[0])}</span>${t.outputs.length>1?`<span class="output-more">+${t.outputs.length-1}</span>`:''}</div>`:''}
    <div class="node-hierarchy-controls">${children.length?`<button class="children-toggle ${collapsed?'is-collapsed':''}" data-node-action data-action="toggle-children" data-id="${esc(t.id)}" aria-expanded="${!collapsed}" aria-label="${collapsed?'Show':'Hide'} children of ${esc(t.title)}" title="${collapsed?'Show':'Hide'} ${descendantIds(graphDocument(),t.id).size} descendant steps">${icon('chevron')}<span>${childLabel}</span></button>`:''}<button class="node-delete" data-node-action data-action="delete-card" data-id="${esc(t.id)}" aria-label="Delete step ${esc(t.title)}" title="Delete step">${icon('trash')}</button><button class="node-add-child" data-node-action data-action="add-child" data-id="${esc(t.id)}" aria-label="Add operation to ${esc(t.title)}" title="Add operation in Layers">${icon('plus')}</button></div>
    <button class="port out" data-port="out" data-id="${esc(t.id)}" aria-label="Output for ${esc(t.title)}" title="Drag to connect overview steps."></button></article>`;
  }).join('');
  renderEdges();applyTransform();updateConnectPrompt();$('#empty-state').hidden=graphDocument().tasks.length>0;
}

function applyTransform() { $('#world').style.transform=`translate(${transform.x}px,${transform.y}px) scale(${transform.zoom})`; $('#zoom-level').textContent=`${Math.round(transform.zoom*100)}%`; renderMinimap(); }
/** The map always represents the entire overview, regardless of Focus/collapse. */
function renderMinimap() {
  const wrap=$('#minimap-wrap');
  wrap.hidden=!mapOpen || !graphDocument().tasks.length || view!=='graph';
  if (wrap.hidden) {miniBounds=null;return;}
  const tasks=graphDocument().tasks, shown=new Set(visibleTasks().map(t=>t.id));
  const pos=tasks.map(t=>({...positionOf(t.id),...taskSize(t)}));
  const minX=Math.min(...pos.map(p=>p.x)), minY=Math.min(...pos.map(p=>p.y));
  const w=Math.max(...pos.map(p=>p.x+p.width))-minX, h=Math.max(...pos.map(p=>p.y+p.height))-minY;
  const scale=Math.min(160/Math.max(w,1),72/Math.max(h,1)), ox=(180-w*scale)/2, oy=(94-h*scale)/2;
  miniBounds={minX,minY,scale,ox,oy};
  const coords=id=>{const p=positionOf(id),s=taskSize(tasks.find(t=>t.id===id));return {x:ox+(p.x-minX)*scale,y:oy+(p.y-minY)*scale,w:s.width*scale,h:s.height*scale};};
  const points=new Map(tasks.map(t=>[t.id,coords(t.id)]));
  let links='';
  for(const t of tasks) {
    const b=points.get(t.id);
    if(t.parent_id) {const a=points.get(t.parent_id);links+=`<path class="mini-hierarchy" d="M ${a.x+a.w/2} ${a.y+a.h} L ${b.x+b.w/2} ${b.y}"/>`;}
    for(const id of t.depends_on){const a=points.get(id);links+=`<path class="mini-dependency" d="M ${a.x+a.w} ${a.y+a.h/2} L ${b.x} ${b.y+b.h/2}"/>`;}
  }
  const cards=tasks.map(t=>{const p=points.get(t.id),active=t.id===selected;return `<rect class="mini-node ${active?'is-selected':''} ${shown.has(t.id)?'':'is-context'}" data-mini-task="${esc(t.id)}" x="${p.x}" y="${p.y}" width="${Math.max(p.w,1.5)}" height="${Math.max(p.h,1.5)}" rx="1"><title>${esc(t.title)}${shown.has(t.id)?'':' — outside current view'}</title></rect>`;}).join('');
  const vx=ox+(-transform.x/transform.zoom-minX)*scale,vy=oy+(-transform.y/transform.zoom-minY)*scale;
  const vw=$('#canvas').clientWidth/transform.zoom*scale,vh=$('#canvas').clientHeight/transform.zoom*scale;
  const clipX=Math.max(1,vx),clipY=Math.max(1,vy),clipW=Math.max(0,Math.min(179,vx+vw)-clipX),clipH=Math.max(0,Math.min(93,vy+vh)-clipY);
  const viewport=`<rect class="mini-viewport" x="${clipX}" y="${clipY}" width="${clipW}" height="${clipH}" rx="2"/>`;
  $('#minimap').innerHTML=links+viewport+cards;
}
function navigateMinimap(event,taskId=null) {
  if(!miniBounds)return;
  // Enter/Space on the whole map reveals a genuine global overview.
  if(event.detail===0) {
    collapsedBranches.clear();focusMode=false;switchView('graph');fitGraph();return;
  }
  const r=$('#minimap').getBoundingClientRect(),{minX,minY,scale,ox,oy}=miniBounds;
  const id=taskId || event.target.closest('[data-mini-task]')?.dataset.miniTask;
  let x,y;
  if(id) {
    const task=graphDocument().tasks.find(t=>t.id===id);if(!task)return;
    const p=positionOf(id),s=taskSize(task);x=p.x+s.width/2;y=p.y+s.height/2;
    if(focusMode&&!focusedIds()?.has(id))focusMode=false;
    revealPath(id);refresh(false);
  } else {
    // The title is not part of the plot; clicking it restores the full overview.
    if(event.clientY<r.top){collapsedBranches.clear();focusMode=false;switchView('graph');fitGraph();return;}
    x=((event.clientX-r.left)/r.width*180-ox)/scale+minX;
    y=((event.clientY-r.top)/r.height*94-oy)/scale+minY;
    if(focusMode){focusMode=false;refresh(false);}
  }
  const c=$('#canvas');
  transform.x=c.clientWidth/2-x*transform.zoom;transform.y=c.clientHeight/2-y*transform.zoom;
  applyTransform();
}
function startMinimapDrag(event) {
  if(event.button!==0 || event.isPrimary===false || pointer || miniPointer || !miniBounds)return;
  const matrix=$('#minimap').getScreenCTM();if(!matrix)return;
  miniClick=null;
  miniPointer={pointerId:event.pointerId,clientX:event.clientX,clientY:event.clientY,
    inverse:matrix.inverse(),scale:miniBounds.scale,transform:{...transform},moved:false,
    taskId:event.target.closest('[data-mini-task]')?.dataset.miniTask};
  // Capture the stable wrapper: the SVG contents redraw on every camera movement.
  $('#minimap-wrap').setPointerCapture(event.pointerId);
}
function moveMinimapDrag(event) {
  if(!miniPointer || event.pointerId!==miniPointer.pointerId)return;
  const drag=miniPointer,dx=event.clientX-drag.clientX,dy=event.clientY-drag.clientY;
  if(Math.hypot(dx,dy)>3)drag.moved=true;
  if(!drag.moved)return;
  event.preventDefault();$('#minimap-wrap').classList.add('dragging');
  const start=new DOMPoint(drag.clientX,drag.clientY).matrixTransform(drag.inverse);
  const end=new DOMPoint(event.clientX,event.clientY).matrixTransform(drag.inverse);
  transform.x=drag.transform.x-(end.x-start.x)/drag.scale*drag.transform.zoom;
  transform.y=drag.transform.y-(end.y-start.y)/drag.scale*drag.transform.zoom;
  applyTransform();
}
function finishMinimapDrag(event,cancelled=false) {
  if(!miniPointer || event.pointerId!==miniPointer.pointerId)return;
  miniClick={suppress:miniPointer.moved||cancelled,taskId:miniPointer.taskId};miniPointer=null;
  const wrap=$('#minimap-wrap');wrap.classList.remove('dragging');
  if(wrap.hasPointerCapture(event.pointerId))wrap.releasePointerCapture(event.pointerId);
}
function clickMinimap(event) {
  const gesture=miniClick;miniClick=null;
  if(event.detail!==0 && gesture?.suppress){event.preventDefault();return;}
  navigateMinimap(event,event.detail!==0?gesture?.taskId:null);
}

function fitGraph() {
  const tasks=visibleTasks(), c=$('#canvas'); if (!tasks.length || !c.clientWidth || !c.clientHeight) return;
  const pos=[...tasks.map(t=>({...positionOf(t.id),...taskSize(t)})),...visibleStageFrames()], minX=Math.min(...pos.map(p=>p.x)), minY=Math.min(...pos.map(p=>p.y));
  const w=Math.max(...pos.map(p=>p.x+p.width))-minX, h=Math.max(...pos.map(p=>p.y+p.height))-minY;
  const px=c.clientWidth<700?30:88, top=96, bottom=96;
  transform.zoom=Math.min(1.05,Math.max(.12,Math.min((c.clientWidth-px)/w,Math.max(90,c.clientHeight-top-bottom)/h)));
  transform.x=(c.clientWidth-w*transform.zoom)/2-minX*transform.zoom;
  transform.y=top+(c.clientHeight-top-bottom-h*transform.zoom)/2-minY*transform.zoom;
  applyTransform();
}
function frameGraphOpening() {
  if(!matchMedia('(max-width:700px)').matches)return;
  const tasks=graphDocument().tasks;
  const task=tasks.find(t=>t.id===(selected||layerSelection.overviewId))||tasks[0];
  if(!task)return;
  const p=positionOf(task.id),size=taskSize(task),canvas=$('#canvas');
  transform.zoom=.95;
  transform.x=canvas.clientWidth/2-(p.x+size.width/2)*transform.zoom;
  transform.y=canvas.clientHeight/2-(p.y+size.height/2)*transform.zoom;
  applyTransform();
}
function zoom(factor, x=$('#canvas').clientWidth/2, y=$('#canvas').clientHeight/2) {
  const z=Math.min(2.5,Math.max(.12,transform.zoom*factor)), ratio=z/transform.zoom;
  transform.x=x-(x-transform.x)*ratio; transform.y=y-(y-transform.y)*ratio; transform.zoom=z; applyTransform();
}
function pointInWorld(x,y) { const r=$('#canvas').getBoundingClientRect(); return {x:(x-r.left-transform.x)/transform.zoom,y:(y-r.top-transform.y)/transform.zoom}; }
function dependencyRow(t, source, target) {
  return `<div class="dependency-row"><span class="status-dot ${t.status}"></span><button class="dependency-name" data-action="select" data-id="${esc(t.id)}" title="Edit ${esc(t.title)}">${esc(t.title)}</button><button class="icon-button" data-action="remove-dependency" data-source="${esc(source)}" data-target="${esc(target)}" title="Remove connection" aria-label="Remove connection ${esc(source)} to ${esc(target)}">${icon('close')}</button></div>`;
}
function renderFamily(task) {
  const descendants=descendantIds(project,task.id),kids=childrenOf(project,task.id);
  const graphKids=childrenOf(graphDocument(),task.id);
  const choices=project.tasks.filter(t=>t.id!==task.id&&!descendants.has(t.id));
  const parent=project.tasks.find(t=>t.id===task.parent_id);
  return `<section class="inspector-section family-section"><div class="family-heading"><h3>Hierarchy</h3><button class="text-button" data-action="add-child" data-id="${esc(task.id)}">${icon('plus')} ${taskLayer(task)==='overview'?'Add operation':'Add child'}</button></div>
  ${!parent?`<label class="field-label">Step number<input id="step-number" type="number" min="1" step="1" value="${stepOutline(project).find(row=>row.task.id===task.id).number}"></label><p class="field-help">Children inherit this number. An existing main-step number swaps with this one.</p>`:''}
  <label class="field-label">Part of<select id="parent-step" aria-label="Parent step"><option value="">No parent · main step</option>${choices.map(t=>`<option value="${esc(t.id)}" ${t.id===task.parent_id?'selected':''}>${esc(t.title)}</option>`).join('')}</select></label>
  ${parent?`<button class="family-parent" data-action="select" data-id="${esc(parent.id)}">${icon('up')} Open ${esc(parent.title)}</button>`:''}
  ${kids.length?`<div class="family-heading"><span class="connection-group-label">Children</span>${view==='graph'&&graphKids.length?`<button class="text-button" data-action="toggle-children" data-id="${esc(task.id)}">${collapsedBranches.has(task.id)?'Show on canvas':'Collapse branch'}</button>`:''}</div>${kids.map(t=>`<div class="dependency-row"><span class="status-dot ${esc(t.status)}"></span><button class="dependency-name" data-action="select" data-id="${esc(t.id)}">${esc(t.title)}</button><button class="icon-button" data-action="select" data-id="${esc(t.id)}" aria-label="Open child ${esc(t.title)}">${icon('next')}</button></div>`).join('')}`:''}
  </section>`;
}

function renderInspector() {
  const task=currentTask(), container=$('#inspector'), key=selectedEdge || selected;
  const scroll=inspectorSelection===key ? $('#inspector .inspector-content')?.scrollTop || 0 : 0;
  inspectorSelection=key;
  const heading=label=>`<div class="inspector-heading"><span class="inspector-heading-label">${label}</span><button class="icon-button" data-action="close-inspector" aria-label="Close details" title="Close details">${icon('close')}</button></div>`;
  if (selectedEdge) {
    const [source,target]=selectedEdge.split('|');
    const choices=id=>(view==='graph'?graphDocument().tasks:project.tasks).map(t=>`<option value="${esc(t.id)}" ${t.id===id ? 'selected' : ''}>${esc(t.title)}</option>`).join('');
    container.innerHTML=`${heading('Connection')}<div class="inspector-content"><div class="connection-direction">${icon('link')} Dependency</div><p class="connection-summary">The step under <strong>To</strong> depends on the step under <strong>From</strong>.</p><form id="connection-form"><label class="field-label">From<select id="connection-source">${choices(source)}</select></label><label class="field-label">To<select id="connection-target">${choices(target)}</select></label><p id="connection-error" class="inline-error" role="alert"></p><div class="connection-actions"><button class="button primary" type="submit">Update connection</button><button class="button" data-action="reverse-edge" type="button">Reverse</button></div></form></div><div class="inspector-footer"><button class="delete-task" data-action="delete-edge">${icon('trash')} Remove connection</button></div>`;
    return;
  }
  if (!task) { container.innerHTML=''; container.hidden=true; return; }
  const hasMethods=taskLayer(task)!=='overview';
  if(inspectorTab==='methods'&&!hasMethods)inspectorTab='plan';
  const candidates=(view==='graph'?graphDocument().tasks:project.tasks).filter(t=>t.id!==task.id && !task.depends_on.includes(t.id)).filter(t=>{ try{addDependency(project,t.id,task.id);return true;}catch{return false;} });
  const downstream=project.tasks.filter(t=>t.depends_on.includes(task.id));
  container.innerHTML=`${heading('Step details')}<div class="inspector-content"><div class="id-line">${view==='layers'?({'overview':'OVERVIEW','operation':'OPERATION','processing':'PROCESSING STEP'}[taskLayer(task)]):task.parent_id?'CHILD STEP':'MAIN STEP'}</div><textarea class="title-input" rows="2" data-field="title" aria-label="Step title" placeholder="Name this step…" maxlength="200">${task.title==='Untitled step'?'':esc(task.title)}</textarea>
    <div class="inspector-tabs" role="tablist" aria-label="Step information"><button role="tab" id="plan-tab" data-action="inspector-tab" data-tab="plan" aria-selected="${inspectorTab==='plan'}" aria-controls="plan-panel" tabindex="${inspectorTab==='plan'?0:-1}" class="${inspectorTab==='plan'?'active':''}">Plan</button><button role="tab" id="resources-tab" data-action="inspector-tab" data-tab="resources" aria-selected="${inspectorTab==='resources'}" aria-controls="resources-panel" tabindex="${inspectorTab==='resources'?0:-1}" class="${inspectorTab==='resources'?'active':''}">Notes & files</button>${hasMethods?`<button role="tab" id="methods-tab" data-action="inspector-tab" data-tab="methods" aria-selected="${inspectorTab==='methods'}" aria-controls="methods-panel" tabindex="${inspectorTab==='methods'?0:-1}" class="${inspectorTab==='methods'?'active':''}">Methods</button>`:''}</div>
    <div id="plan-panel" role="tabpanel" aria-labelledby="plan-tab" ${inspectorTab!=='plan'?'hidden':''}><label class="field-label">Status<select data-field="status">${statusOptions(task.status)}</select></label><label class="field-label">Goal<textarea rows="3" data-field="goal" placeholder="What should this step achieve?">${esc(task.goal)}</textarea></label>
    ${layerMetadataFields(task)}
    ${renderFamily(task)}
    <section class="inspector-section"><h3>Dependencies</h3><div class="connection-group-label">Depends on</div>${task.depends_on.map(id=>dependencyRow(project.tasks.find(t=>t.id===id),id,task.id)).join('') || '<p class="no-connections">No incoming connections</p>'}<select class="dependency-add" id="add-dependency" aria-label="Add incoming dependency"><option value="">+ Add connection</option>${candidates.map(t=>`<option value="${esc(t.id)}">${esc(t.title)}</option>`).join('')}</select>
    ${downstream.length ? `<div class="connection-group-label">Required by</div>${downstream.map(t=>dependencyRow(t,task.id,t.id)).join('')}` : ''}
    <button class="connected-add" data-action="add-after">${icon('plus')} Add dependent step</button></section></div>
    <div id="resources-panel" role="tabpanel" aria-labelledby="resources-tab" ${inspectorTab!=='resources'?'hidden':''}><label class="field-label">Notes<textarea rows="6" data-field="notes" placeholder="Decisions, observations, references…">${esc(task.notes)}</textarea></label><label class="field-label">Inputs<textarea rows="3" data-field="inputs" placeholder="One file path or reference per line">${esc(task.inputs.join('\n'))}</textarea></label><label class="field-label">Outputs<textarea rows="3" data-field="outputs" placeholder="One file path or reference per line">${esc(task.outputs.join('\n'))}</textarea></label>
    ${task.agent_instructions ? `<details><summary>Existing handoff notes</summary><textarea rows="4" data-field="agent_instructions" aria-label="Agent instructions">${esc(task.agent_instructions)}</textarea></details>`:''}</div>${hasMethods?`<div id="methods-panel" role="tabpanel" aria-labelledby="methods-tab" ${inspectorTab!=='methods'?'hidden':''}>${renderMethodDetails(task,layerSelection.recordId)}</div>`:''}${view==='layers'?renderLayerPosition(task):''}</div>
    <div class="inspector-footer"><button class="delete-task" data-action="delete-task">${icon('trash')} Delete step</button></div>`;
  $('#inspector .inspector-content').scrollTop=scroll; resizeTitle();
}
function resizeTitle() { const el=$('#inspector .title-input'); if(el){el.style.height='0px';el.style.height=`${Math.max(32,Math.min(180,el.scrollHeight+2))}px`;} }
function renderList() {
  const rows=stepOutline(project);
  $('#list-view').innerHTML=rows.length ? `<table><thead><tr><th>Step</th><th>Status</th><th class="table-deps">Depends on</th></tr></thead><tbody>${rows.map(({task:t,depth,number})=>`<tr data-depth="${depth}" class="${selected===t.id?'is-selected':''}"><td><div class="table-step" style="padding-inline-start:${depth*22}px"><span class="table-number">${number}</span><button class="table-task" data-action="select" data-id="${esc(t.id)}" ${depth?`aria-label="${esc(t.title)}, child of ${esc(project.tasks.find(p=>p.id===t.parent_id)?.title)}"`:''}>${esc(t.title)}</button></div></td><td><select data-table-status="${esc(t.id)}" aria-label="Status of ${esc(t.title)}">${statusOptions(t.status)}</select></td><td class="table-deps">${t.depends_on.map(id=>esc(project.tasks.find(d=>d.id===id)?.title || id)).join('<br>') || '—'}</td></tr>`).join('')}</tbody></table>` : '<div class="list-empty">No steps yet.</div>';
}
function renameStep(id) {
  navigateTo(id);
  const node=$$('.task-node').find(el=>el.dataset.id===id),task=currentTask();
  if(!node || !task)return;
  const heading=node.querySelector('h3'),input=document.createElement('input');
  input.className='node-title-input';input.value=task.title;input.setAttribute('aria-label','Step name');
  heading.hidden=true;heading.after(input);
  let finished=false;
  function finish(cancel=false){
    if(finished)return;finished=true;
    const title=input.value.trim() || 'Untitled step';
    input.remove();heading.hidden=false;
    if(!cancel){
      heading.textContent=title;heading.classList.toggle('untitled',title==='Untitled step');
      node.querySelectorAll('[aria-label]').forEach(el=>el.setAttribute('aria-label',el.getAttribute('aria-label').replace(task.title,()=>title)));
      if(!task.goal)node.querySelector('.node-goal').textContent=title==='Untitled step'?'Click to name this step':'';
      node.setAttribute('aria-label',`${title}, ${STATUS[task.status].label}${task.parent_id?', child step':''}`);
      // Keep the clicked card controls mounted while blur commits the name.
      change(doc=>{doc.tasks.find(t=>t.id===id).title=title;},{graph:false});
    }
  }
  input.addEventListener('blur',()=>finish());
  input.addEventListener('keydown',event=>{
    if(event.isComposing)return;
    if(event.key==='Enter'||event.key==='Escape'){
      event.preventDefault();event.stopPropagation();finish(event.key==='Escape');
      $$('.task-node').find(el=>el.dataset.id===id)?.focus({preventScroll:true});
    }
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s')finish();
  });
  input.focus({preventScroll:true});input.select();
}

function refresh(inspector=true,graph=true) {
  if(view==='graph')normalizeGraphSelection();
  for(const id of collapsedBranches)if(!project.tasks.some(t=>t.id===id))collapsedBranches.delete(id);
  if(selected)revealPath(selected);
  if(selected && !currentTask()){ selected=null;focusMode=false; }
  if(selectedEdge && !edgeExists(selectedEdge))selectedEdge=null;
  if(!selected && !selectedEdge)$('#inspector').hidden=true;
  renderHeader();if(graph)renderGraph();else{renderEdges();renderMinimap();}if(inspector)renderInspector();if(view==='list')renderList();if(view==='layers')renderLayers();if(ideasOpen)renderIdeas();
}

function renderLayers() {
  if(currentTask()&&!selectedEdge)layerSelection={...layerSelection,...layerTaskContext(currentTask())};
  const current = resolveLayerSelection(project, layerSelection);
  layerSelection = {...layerSelection, overviewId:current.overviewId, operationId:current.operationId, processingId:current.processingId, recordId:current.recordId, selectedId:selectedEdge?null:selected};
  const focused = $('#layers-view').contains(document.activeElement) ? document.activeElement.closest('[data-action]') : null;
  const focusKey = focused ? {action:focused.dataset.action, id:focused.dataset.id, source:focused.dataset.source, target:focused.dataset.target} : null;
  const focusId = $('#layers-view').contains(document.activeElement) ? document.activeElement.id : null;
  $('#layers-view').innerHTML = renderLayeredView(layerPointer?.draft || project, layerSelection, !!history.length, !!future.length);
  if(layerCamera.autoFit)fitLayerCanvas();else applyLayerCamera();
  if(layerPointer?.type==='node'&&layerPointer.moved)$('#layer-world .flow-node[data-id="'+layerPointer.taskId+'"]')?.classList.add('is-dragging');
  if(focusKey)[...$('#layers-view').querySelectorAll('[data-action]')].find(el => el.dataset.action === focusKey.action && el.dataset.id === focusKey.id && el.dataset.source === focusKey.source && el.dataset.target === focusKey.target)?.focus({preventScroll:true});
  else if(focusId)document.getElementById(focusId)?.focus({preventScroll:true});
}
function applyLayerCamera() {
  const world=$('#layer-world');if(!world)return;
  world.style.transform=`translate(${layerCamera.x}px,${layerCamera.y}px) scale(${layerCamera.zoom})`;
  if($('#layer-zoom-level'))$('#layer-zoom-level').textContent=`${Math.round(layerCamera.zoom*100)}%`;
}
function fitLayerCanvas(fitAll = layerCamera.fitAll || false) {
  const viewport=$('#layer-canvas'),world=$('#layer-world');
  if(!viewport?.clientWidth||!viewport.clientHeight||!world)return;
  const w=Number(world.dataset.boundsWidth)||world.offsetWidth,h=Number(world.dataset.boundsHeight)||world.offsetHeight;
  const minX=Number(world.dataset.boundsX)||0,minY=Number(world.dataset.boundsY)||0;
  const fitZoom=Math.min(1,Math.max(.000001,Math.min((viewport.clientWidth-40)/w,(viewport.clientHeight-36)/h)));
  const readableMobile=!fitAll&&matchMedia('(max-width:700px)').matches;
  const z=readableMobile?Math.max(.85,fitZoom):fitZoom;
  const anchorId=selected||layerSelection.operationId||layerSelection.overviewId;
  const anchor=readableMobile?[...world.querySelectorAll('.flow-node')].find(node=>node.dataset.id===anchorId):null;
  const x=anchor?viewport.clientWidth/2-(anchor.offsetLeft+anchor.offsetWidth/2)*z:(viewport.clientWidth-w*z)/2-minX*z;
  const y=anchor?viewport.clientHeight/2-(anchor.offsetTop+anchor.offsetHeight/2)*z:(viewport.clientHeight-h*z)/2-minY*z;
  layerCamera={x,y,zoom:z,autoFit:true,fitAll};
  applyLayerCamera();
}
function zoomLayerCanvas(factor,x,y) {
  const viewport=$('#layer-canvas');if(!viewport)return;
  x??=viewport.clientWidth/2;y??=viewport.clientHeight/2;
  const z=Math.min(2,Math.max(.000001,layerCamera.zoom*factor)),ratio=z/layerCamera.zoom;
  layerCamera={x:x-(x-layerCamera.x)*ratio,y:y-(y-layerCamera.y)*ratio,zoom:z,autoFit:false};
  applyLayerCamera();
}

function layerPositionsSnapshot() {
  return Object.fromEntries(computeLayerCanvas(project,layerSelection).nodes.map(node=>[node.id,{x:node.x,y:node.y}]));
}
function layerPositionDraft(base, positions, id, x, y) {
  const doc=clone(base);
  doc.layout.layer_positions={...doc.layout.layer_positions};
  for(const [taskId,position] of Object.entries(positions))doc.layout.layer_positions[taskId]={...doc.layout.layer_positions[taskId],...position};
  const bounded=value=>Math.max(-10000000,Math.min(10000000,value));
  doc.layout.layer_positions[id]={...doc.layout.layer_positions[id],x:bounded(x),y:bounded(y)};
  return doc;
}
function moveLayerNode(id,x,y,group='') {
  if(!Number.isFinite(x)||!Number.isFinite(y))return;
  const positions=layerPositionsSnapshot();if(!positions[id])return;
  layerCamera.autoFit=false;
  change(()=>layerPositionDraft(project,positions,id,x,y),{validate:true,group});
}
function arrangeLayerCanvas() {
  const ids=Object.keys(layerPositionsSnapshot());
  change(doc=>{for(const id of ids)if(doc.layout.layer_positions)delete doc.layout.layer_positions[id];
    if(doc.layout.layer_positions&&!Object.keys(doc.layout.layer_positions).length)delete doc.layout.layer_positions;
  },{validate:true});
  fitLayerCanvas(true);
}
function renderLayerPosition(task) {
  const node=computeLayerCanvas(project,{...layerSelection,...layerTaskContext(task)}).nodes.find(node=>node.id===task.id);
  if(!node)return '';
  return `<details class="layer-position-editor"><summary>Canvas position</summary><div class="layer-position-fields"><label class="field-label">X<input type="number" step="any" min="-10000000" max="10000000" name="canvas_x" autocomplete="off" data-layer-coordinate="x" value="${node.x}" aria-label="Canvas X position"></label><label class="field-label">Y<input type="number" step="any" min="-10000000" max="10000000" name="canvas_y" autocomplete="off" data-layer-coordinate="y" value="${node.y}" aria-label="Canvas Y position"></label></div><p class="field-help">Drag a card, or focus it and use arrow keys. Hold Shift for larger moves.</p></details>`;
}

function renderIdeas() {
  const body=$('#ideas-body'),focused=body.contains(document.activeElement)?document.activeElement:null;
  const key=focused?{id:focused.id,action:focused.dataset.action,item:focused.dataset.id}:null;
  const scroll=$('#ideas-content')?.scrollTop || 0;
  body.innerHTML=renderIdeasList(project,ideasFilter,expandedIdeaId);
  $('#ideas-content').scrollTop=scroll;
  const target=key?.id?document.getElementById(key.id):key?.action?[...body.querySelectorAll('[data-action]')].find(el=>el.dataset.action===key.action&&el.dataset.id===key.item):null;
  if(key)(target||body.querySelector('[data-action="idea-add"]'))?.focus({preventScroll:true});
}
function openIdeas() {
  ideasOpen=true;layerCamera.autoFit=false;
  $('#inspector').hidden=true;
  renderIdeas();renderHeader();
  $('#ideas-heading').focus({preventScroll:true});
}
function closeIdeas(restoreFocus=true) {
  ideasOpen=false;renderHeader();
  if(restoreFocus)$('#ideas-button').focus({preventScroll:true});
}

function openIdeaDialog(id = null) {
  const item=(project.ideas||[]).find(idea=>idea.id===id);
  if(id&&!item)return;
  editingIdeaId=id;
  const form=$('#idea-form');form.reset();
  form.elements.related_task_id.innerHTML='<option value="">Project-wide</option>'+stepOutline(project).map(({task,number})=>`<option value="${esc(task.id)}">${esc(number)} · ${esc(task.title)}</option>`).join('');
  if(item)for(const key of ['title','kind','status','notes','revisit_when','resolution','related_task_id'])form.elements[key].value=item[key]||'';
  $('#idea-dialog-heading').textContent=item?'Edit idea or question':'Capture for later';
  $('#idea-submit').textContent=item?'Save changes':'Add item';
  $('#idea-error').textContent='';$('#idea-dialog').showModal();
  form.elements.title.focus();
}
function submitIdea(event) {
  event.preventDefault();const form=event.target;if(!form.reportValidity())return;
  const fields=new FormData(form), item={};
  for(const key of ['title','kind','status','notes','revisit_when','resolution'])item[key]=String(fields.get(key)||'').trim();
  const related=String(fields.get('related_task_id')||'');
  const now=new Date().toISOString();
  try {
    let next;
    if(editingIdeaId){
      const existing=(project.ideas||[]).find(idea=>idea.id===editingIdeaId);
      if(!existing)throw Error('This item is no longer in the project.');
      item.related_task_id=related||null;item.updated_at=now;
      if(item.status==='resolved'&&existing.status!=='resolved')item.resolved_at=now;
      next=updateIdea(project,editingIdeaId,item);
    }else{
      item.id=`idea_${crypto.randomUUID().replaceAll('-','')}`;item.created_at=now;
      if(related)item.related_task_id=related;
      if(item.status==='resolved')item.resolved_at=now;
      next=addIdea(project,item);
    }
    const id=editingIdeaId||item.id;
    ideasOpen=true;ideasFilter=item.status==='resolved'?'resolved':'active';expandedIdeaId=id;
    if(change(()=>next,{validate:true})){
      $('#idea-dialog').close();renderIdeas();renderHeader();
      const savedRow=[...$('#ideas-body').querySelectorAll('[data-action="idea-toggle"]')].find(el=>el.dataset.id===id);
      savedRow?.focus({preventScroll:true});
      savedRow?.scrollIntoView({block:'nearest'});
      toast('Saved to Ideas & questions.');
    }
  }catch(error){$('#idea-error').textContent=error.message;}
}
function confirmIdeaRemoval(id) {
  const item=(project.ideas||[]).find(idea=>idea.id===id);if(!item)return;
  deletingIdeaId=id;$('#delete-idea-title').textContent=item.title;$('#delete-idea-dialog').showModal();
}
function openIdeaLink(id) {
  const item=(project.ideas||[]).find(idea=>idea.id===id);
  if(!item?.related_task_id)return;
  closeIdeas(false);navigateTo(item.related_task_id);
  $('#inspector .title-input')?.focus({preventScroll:true});
}
function layerTaskContext(task) {
  const kind=taskLayer(task);
  let overviewId=task.id,operationId=null,processingId=null;
  if(kind!=='overview'){
    const operation=kind==='processing'?project.tasks.find(t=>taskLayer(t)==='operation'&&processingStepsFor(project,t.id).some(p=>p.id===task.id)):task;
    operationId=operation?.id||null;processingId=kind==='processing'?task.id:null;
    overviewId=overviewSteps(project).find(t=>operationsFor(project,t.id).some(op=>op.id===operationId))?.id||':unassigned';
  }
  return {overviewId,operationId,processingId};
}
function layerSelectTask(id, tab = null) {
  const task=project.tasks.find(t=>t.id===id);if(!task)return;
  const kind=taskLayer(task), {overviewId,operationId,processingId}=layerTaskContext(task);
  if(layerSelection.overviewId!==overviewId)layerCamera.autoFit=true;
  layerSelection={overviewId,operationId,processingId,selectedId:id};
  selected=id;selectedEdge=null;inspectorTab=tab||(kind==='overview'?'plan':'methods');showInspector();refresh();
}
function layerSelectOverview(id) {
  if(id===':unassigned'){layerSelection={overviewId:id};selected=null;selectedEdge=null;layerCamera.autoFit=true;closeInspector();refresh();return;}
  layerSelectTask(id);
}
function layerSelectOperation(id) {layerSelectTask(id);}
function layerEdit(id) {
  if(!project.tasks.some(t=>t.id===id))return;
  selected=id;selectedEdge=null;inspectorTab='plan';showInspector();refresh();
}
function addLayerStep(layer, dependency = null) {
  let newId;
  const ok=change(doc=>{
    const result=insertBlankStep(doc,{x:0,y:0},dependency); newId=result.id;
    const task=result.document.tasks.find(t=>t.id===newId);task.layer=layer;
    if(layer==='operation' && overviewSteps(doc).some(t=>t.id===layerSelection.overviewId))task.overview_id=layerSelection.overviewId;
    if(layer==='processing' && doc.tasks.some(t=>t.id===layerSelection.operationId&&taskLayer(t)==='operation'))task.operation_id=layerSelection.operationId;
    return validateProject(result.document);
  },{validate:true});
  if(!ok)return;
  layerCamera.autoFit=true;
  layerSelectTask(newId,'plan');$('#inspector .title-input')?.focus();
}
function layerMetadataFields(task) {
  const kind=taskLayer(task), stages=overviewSteps(project).filter(t=>t.id!==task.id);
  const operations=project.tasks.filter(t=>taskLayer(t)==='operation'&&t.id!==task.id);
  const membership=kind==='operation'?`<label class="field-label">Overview step<select data-layer-field="overview_id"><option value="">Use hierarchy / unassigned</option>${stages.map(t=>`<option value="${esc(t.id)}" ${task.overview_id===t.id?'selected':''}>${esc(t.title)}</option>`).join('')}</select></label>`:kind==='processing'?`<label class="field-label">Operation<select data-layer-field="operation_id"><option value="">Use hierarchy / unassigned</option>${operations.map(t=>`<option value="${esc(t.id)}" ${task.operation_id===t.id?'selected':''}>${esc(t.title)}</option>`).join('')}</select></label>`:'';
  return `<section class="inspector-section layer-fields"><h3>Workflow layer</h3><label class="field-label">Layer<select data-layer-field="layer">${[['overview','1 · Overview'],['operation','2 · Operation'],['processing','3 · Processing']].map(([value,label])=>`<option value="${value}" ${kind===value?'selected':''}>${label}</option>`).join('')}</select></label>${membership}${kind!=='overview'?`<label class="field-label">Operation type<input data-field="operation_type" list="operation-types" value="${esc(task.operation_type||'')}" placeholder="Analysis, literature, download…"></label><label class="field-label">Planned method<textarea rows="3" data-field="method" placeholder="How will this step be performed?">${esc(task.method||'')}</textarea></label><label class="field-label">Parameters / criteria<textarea rows="3" data-field="parameters" placeholder="Settings, search query, inclusion rules…">${esc(task.parameters||'')}</textarea></label><label class="field-label">Rationale<textarea rows="3" data-field="rationale" placeholder="Why this approach?">${esc(task.rationale||'')}</textarea></label><button class="text-button" data-action="layer-show-methods" data-id="${esc(task.id)}">View methods & records →</button>`:''}</section>`;
}
function methodTask() {return currentTask()&&taskLayer(currentTask())!=='overview'?currentTask():project.tasks.find(t=>t.id===(layerSelection.processingId||layerSelection.operationId));}

function openRecordDialog() {
  const task=methodTask();if(!task)return;
  recordingTaskId=task.id;
  const form=$('#record-work-form');form.reset();
  $('#record-operation-title').textContent=task.title;
  for(const key of ['method','parameters','rationale','inputs','outputs'])form.elements[key].value=Array.isArray(task[key])?task[key].join('\n'):task[key]||'';
  $('#record-error').textContent='';$('#record-work-dialog').showModal();
}
function submitWorkRecord(event) {
  event.preventDefault();const form=event.target;
  if(!form.reportValidity())return;
  const fields=new FormData(form), record={id:`record_${crypto.randomUUID().replaceAll('-','')}`,recorded_at:new Date().toISOString()};
  for(const field of ['method','parameters','rationale','changes','code','software','notes','status'])record[field]=String(fields.get(field)||'').trim();
  const performed=String(fields.get('performed_at')||'');if(performed)record.performed_at=new Date(performed).toISOString();
  for(const field of ['inputs','outputs'])record[field]=String(fields.get(field)||'').split('\n').map(s=>s.trim()).filter(Boolean);
  try {
    const next=addOperationRecord(project,recordingTaskId,record);
    if(change(()=>next,{validate:true})){layerSelection.recordId=record.id;$('#record-work-dialog').close();refresh();toast('Work recorded. Task progress is unchanged.');}
  } catch(error) {$('#record-error').textContent=error.message;}
}
function removeEdge(source,target) {
  selectedEdge=null;
  change(doc=>{const t=doc.tasks.find(t=>t.id===target); if(t)t.depends_on=t.depends_on.filter(d=>d!==source);});
}
function editEdge(source,target) {
  if(!selectedEdge)return;
  const before=selectedEdge, [oldSource,oldTarget]=before.split('|'), next=clone(project);
  try {
    if(source!==oldSource || target!==oldTarget) {
      if(next.tasks.find(t=>t.id===target)?.depends_on.includes(source))throw Error('That connection already exists.');
      next.tasks.find(t=>t.id===oldTarget).depends_on=next.tasks.find(t=>t.id===oldTarget).depends_on.filter(d=>d!==oldSource);
      const result=(view==='graph'?addDependency:addBranchDependency)(next,source,target);
      selectedEdge=`${source}|${target}`;
      const oldProject=project;
      if(!change(()=>result,{validate:true}))selectedEdge=before;
      else {announceParentChanges(oldProject,result);}
      if(focusMode){const ids=focusedIds();if(!ids?.has(source)||!ids?.has(target)){focusMode=false;refresh();fitGraph();}}
    }
  } catch(error) { $('#connection-error').textContent=error.message; }
}
function announceParentChanges(before,after) {
  const ids=new Map(before.tasks.map(t=>[t.id,t.parent_id]));
  for(const t of after.tasks)if(t.parent_id && ids.has(t.id) && ids.get(t.id)!==t.parent_id) {
    const name=after.tasks.find(p=>p.id===t.parent_id)?.title || 'this branch';
    const message=`“${t.title}” is now part of “${name}”. Undo reverses both changes.`;
    $('#edit-announcement').textContent=message;toast(message);
  }
}
function connect(source,target) {
  try {
    const before=project, next=(view==='graph'?addDependency:addBranchDependency)(project,source,target);connectFrom=null;
    if(change(()=>next,{validate:true}))announceParentChanges(before,next);
  } catch(error) { toast(error.message,true);connectFrom=null;updateConnectPrompt(); }
}
function updateConnectPrompt() {
  $('#connection-prompt').hidden=!connectFrom;
  $('#canvas').classList.toggle('connecting',!!connectFrom);
  $('#connection-message').textContent=connectFrom ? `Connect “${project.tasks.find(t=>t.id===connectFrom)?.title}” to another step.` : '';
  $$('.task-node').forEach(el=>el.classList.toggle('connect-source',el.dataset.id===connectFrom));
}
function selectEdge(key) { if(!edgeExists(key))return;key.split('|').forEach(revealPath);selectedEdge=key;connectFrom=null;showInspector();refresh(); }
function addBlankStep(dependency=null,parent=null) {
  if(['loading','error'].includes(mode))return;
  try {
    if(project.tasks.length>=500)throw Error('A workflow can contain at most 500 steps.');
    if(dependency&&!project.tasks.some(t=>t.id===dependency))throw Error('Dependency not found.');
    if(parent&&!project.tasks.some(t=>t.id===parent))throw Error('Parent not found.');
    parent ??= dependency ? project.tasks.find(t=>t.id===dependency)?.parent_id ?? null : null;
    closeInspector();
    // Graph placement is derived from numbering; stored legacy coordinates are inert.
    const result=insertBlankStep(project,{x:0,y:0},dependency,parent);
    result.document.tasks.find(t=>t.id===result.id).layer='overview';
    if(change(()=>result.document,{validate:true})) {
      selected=result.id;selectedEdge=null;connectFrom=null;inspectorTab='plan';revealPath(result.id);
      if(!dependency&&!parent)focusMode=false;
      switchView('graph');refresh();keepSelectedVisible();
      $(`.task-node[data-id="${result.id}"]`)?.focus({preventScroll:true});
      $('#edit-announcement').textContent=parent?'Child block added. Select it to name and edit it.':'Blank step added. Select it to name and edit it.';
    }
  }catch(error){toast(error.message,true);}
}

/** An in-page confirmation works even where native confirm() is suppressed. */
function requestDeleteStep(id=selected) {
  const task=project.tasks.find(t=>t.id===id),dialog=$('#delete-step-dialog');
  if(!task||dialog.open)return;
  pendingDeletion=id;
  $('#delete-step-name').textContent=task.title;
  const kids=childrenOf(project,id),count=project.tasks.reduce((n,t)=>n+t.depends_on.filter(d=>d===id||t.id===id).length,0);
  $('#delete-step-impact').textContent=`${count ? `${count} dependency connection${count===1?'':'s'} will also be removed. ` : ''}${kids.length ? `${kids.length} child step${kids.length===1?'':'s'} will move up one level; their contents and descendants are kept. ` : ''}You can undo this.`;
  $('#delete-step-error').textContent='';
  dialog.showModal();$('#delete-step-cancel').focus();
}
function confirmDeleteStep() {
  const id=pendingDeletion, task=project.tasks.find(t=>t.id===id);
  if(!task){$('#delete-step-error').textContent='This step is no longer in the project.';return;}
  // Pin the task ID on opening, and validate before making any destructive edit.
  try {
    const next=validateProject(removeTask(project,id));
    if(!change(()=>next,{validate:true}))return;
    connectFrom=null;selectedEdge=null;focusMode=false;collapsedBranches.delete(id);
    if(selected===id)selected=null;
    if(!selected)closeInspector();
    $('#delete-step-dialog').close();pendingDeletion=null;
    refresh();(view==='layers'?$('#layer-canvas'):$('#canvas'))?.focus({preventScroll:true});
    toast(`“${task.title}” deleted. Undo restores it.`);
    $('#edit-announcement').textContent='Step deleted. Undo restores the step and its connections.';
  }catch(error){$('#delete-step-error').textContent=error.message;}
}

function download(filename,content,type='text/plain') {
  const url=URL.createObjectURL(new Blob([content],{type})),a=document.createElement('a');a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),3000);
}
function exportBackup(format) {
  download(`project.${format}`,format==='json'?JSON.stringify(project,null,2)+'\n':toYaml(project)+'\n',format==='json'?'application/json':'application/yaml');
}
function portableHtml(snapshot) {
  if(!portableTemplate)throw Error('Use Save to save this project to its file.');
  const doc=new DOMParser().parseFromString(portableTemplate,'text/html');
  doc.querySelector('#initial-project').textContent=JSON.stringify(snapshot).replace(/</g,'\\u003c');
  doc.title=`${snapshot.project.name} · Research Flow`;
  return '<!doctype html>\n'+doc.documentElement.outerHTML;
}
const connectionToken = readAccessToken(portable);

async function request(path, options={}) {
  const r=await fetch(path,{...options,headers:{'Content-Type':'application/json','X-Research-Flow':'1',...(connectionToken ? {'X-Research-Flow-Token':connectionToken} : {}),...options.headers},cache:'no-store',signal:AbortSignal.timeout(7000)});
  const data=await r.json();if(!r.ok){const e=Error(data.error||'Request failed.');e.status=r.status;throw e;}return data;
}
function alertFile(message,changed=false) { conflict=changed;$('#file-alert-text').textContent=message;$('#file-alert').hidden=!message;renderHeader(); }
async function save() {
  if(busy || ['loading','error'].includes(mode))return;
  try {
    const snapshot=validateProject(project);
    if(mode==='preview') {
      const name=(snapshot.project.name.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,70)||'research-flow')+'.html';
      download(name,portableHtml(snapshot),'text/html');baseline=JSON.stringify(snapshot);copyDownloaded=true;renderHeader();toast('Editable copy downloaded. Reopen it to continue.');return;
    }
    if(conflict){toast('The file changed. Keep a draft copy, then reload this project.',true);return;}
    if(!dirty()&&!previewWarning)return;
    busy=true;renderHeader();
    const data=await request('/api/project',{method:'PUT',body:JSON.stringify({document:snapshot,revision,preview_layout:'stages'})});
    revision=data.revision;baseline=JSON.stringify(snapshot);filePath=data.file;serverError=false;previewWarning=data.preview_warning||null;alertFile('');
    if(previewWarning)toast(previewWarning,true);
  } catch(error) {if(error.status===409)alertFile(error.message,true);toast(error.message||'Save failed. Your draft is unchanged.',true);}
  finally {busy=false;renderHeader();}
}
async function loadDisk() {
  if(!['server','error'].includes(mode))return;
  if(dirty()&&!confirm('Reload this project and discard unsaved changes in this tab? Keep a draft copy first to preserve them.'))return;
  try {
    const data=await request('/api/project');project=ensurePositions(validateProject(data.document));baseline=JSON.stringify(project);revision=data.revision;filePath=data.file;
    mode='server';serverError=false;previewWarning=null;history=[];future=[];alertFile('');refresh();
  } catch(error){toast(error.message,true);}
}
async function checkExternal() {
  if(!['server','error'].includes(mode)||busy||pollBusy||pointer||miniPointer||layerPointer||document.hidden||$('dialog[open]'))return;
  pollBusy=true;
  try {
    const data=await request('/api/project');
    if($('dialog[open]')||pointer||miniPointer||layerPointer)return;
    if(data.revision!==revision) {
      if(dirty()&&mode==='server')alertFile('This project was edited elsewhere. Your unsaved changes are still here.',true);
      else {
        project=ensurePositions(validateProject(data.document));baseline=JSON.stringify(project);revision=data.revision;filePath=data.file;history=[];future=[];
        mode='server';serverError=false;previewWarning=null;alertFile('');refresh();
        $('#project-title').value=project.project.name;
      }
    } else if(serverError){serverError=false;alertFile('');}
  } catch(error){if(!serverError)alertFile(`Cannot read this project: ${error.message}. Your draft is unchanged.`,conflict);serverError=true;}
  finally{pollBusy=false;}
}
function normalizeGraphSelection() {
    const task=currentTask();
    if(task&&taskLayer(task)!=='overview') {
      const owner=layerTaskContext(task).overviewId;
      selected=graphDocument().tasks.some(t=>t.id===owner)?owner:null;
      if(!selected)focusMode=false;
      inspectorTab='plan';
    }
    if(selectedEdge&&!selectedEdge.split('|').every(id=>graphDocument().tasks.some(t=>t.id===id)))selectedEdge=null;
    if(connectFrom&&!graphDocument().tasks.some(t=>t.id===connectFrom))connectFrom=null;
}
function switchView(which) {
  if(which==='graph')normalizeGraphSelection();
  view=which;$('#canvas').hidden=view!=='graph';$('#list-view').hidden=view!=='list';$('#layers-view').hidden=view!=='layers';$('.canvas-column').classList.toggle('show-layers',view==='layers');if(view!=='graph')focusMode=false;refresh(false);}
const actions={
  overview:()=>{focusMode=false;connectFrom=null;selectedEdge=null;switchView('graph');if(!selected)closeInspector();else renderInspector();fitGraph();frameGraphOpening();},
  focus:()=>{if(!currentTask())return;selectedEdge=null;focusMode=!focusMode;switchView('graph');renderInspector();fitGraph();},
  'toggle-inspector':()=>{if(!currentTask()&&!selectedEdge)return;if($('#inspector').hidden)showInspector();else closeInspector();refresh();keepSelectedVisible();},
  'close-inspector':closeInspector,
  'inspector-tab':el=>{inspectorTab=el.dataset.tab;renderInspector();$(`#${inspectorTab}-tab`).focus();},
  select:el=>navigateTo(el.dataset.id),
  'add-child':el=>{
    const task=project.tasks.find(t=>t.id===(el.dataset.id||selected));if(!task)return;
    selected=task.id;selectedEdge=null;
    layerSelection={...layerSelection,...layerTaskContext(task)};
    switchView('layers');addLayerStep(taskLayer(task)==='overview'?'operation':'processing');
  },
  'toggle-children':el=>toggleBranch(el.dataset.id||selected),
  save, reload:loadDisk,
  add:()=>view==='layers'?addLayerStep('overview'):addBlankStep(), 'add-after':()=>{if(currentTask()&&(view==='layers'||taskLayer(currentTask())!=='overview')){layerSelection={...layerSelection,...layerTaskContext(currentTask())};switchView('layers');addLayerStep(taskLayer(currentTask()),selected);}else addBlankStep(selected);},
  'view-layers':()=>{closeInspector();switchView('layers');},
  'ideas-open':openIdeas,
  'ideas-toggle':()=>ideasOpen?closeIdeas():openIdeas(),
  'ideas-close':()=>closeIdeas(),
  'idea-toggle':el=>{
    const id=el.dataset.id;expandedIdeaId=expandedIdeaId===id?null:id;renderIdeas();
    const summary=[...$('#ideas-body').querySelectorAll('[data-action="idea-toggle"]')].find(button=>button.dataset.id===id);
    summary?.focus({preventScroll:true});summary?.scrollIntoView({block:'nearest'});
  },
  'idea-add':()=>openIdeaDialog(),
  'idea-edit':el=>openIdeaDialog(el.dataset.id),
  'idea-delete':el=>confirmIdeaRemoval(el.dataset.id),
  'idea-link':el=>openIdeaLink(el.dataset.id),
  'layer-overview':el=>layerSelectOverview(el.dataset.id),
  'layer-operation':el=>layerSelectOperation(el.dataset.id),
  'layer-processing':el=>layerSelectTask(el.dataset.id),
  'layer-edge':el=>{selectedEdge=`${el.dataset.source}|${el.dataset.target}`;showInspector();refresh();},
  'layer-arrange':arrangeLayerCanvas,
  'layer-fit':()=>fitLayerCanvas(true), 'layer-zoom-in':()=>zoomLayerCanvas(1.15), 'layer-zoom-out':()=>zoomLayerCanvas(1/1.15), 'layer-zoom-reset':()=>zoomLayerCanvas(1/layerCamera.zoom),
  'layer-edit-overview':()=>layerEdit(layerSelection.overviewId),
  'layer-edit-operation':()=>layerEdit(layerSelection.operationId),
  'layer-add-overview':()=>addLayerStep('overview'),
  'layer-add-operation':()=>addLayerStep('operation'),
  'layer-add-processing':()=>addLayerStep('processing'),
  'layer-record':openRecordDialog,
  'layer-record-select':el=>{layerSelection.recordId=el.dataset.id;renderInspector();[...$('#inspector').querySelectorAll('[data-action="layer-record-select"]')].find(button=>button.dataset.id===el.dataset.id)?.focus({preventScroll:true});},
  'layer-use-record':el=>change(doc=>selectOperationRecord(doc,el.dataset.taskId||methodTask()?.id,el.dataset.id||layerSelection.recordId),{validate:true}),
  'layer-show-methods':el=>{layerSelectTask(el.dataset.id,'methods');},
  'view-list':()=>switchView('list'),
  'toggle-map':()=>{mapOpen=!mapOpen;renderHeader();renderMinimap();},
  layout:()=>{refresh(false);fitGraph();},
  fit:fitGraph,'zoom-in':()=>zoom(1.15),'zoom-out':()=>zoom(1/1.15),'zoom-reset':()=>zoom(1/transform.zoom),undo,redo,
  'remove-dependency':el=>removeEdge(el.dataset.source,el.dataset.target),
  'delete-edge':()=>{if(selectedEdge)removeEdge(...selectedEdge.split('|'));},
  'reverse-edge':()=>{if(selectedEdge){const [a,b]=selectedEdge.split('|');editEdge(b,a);}},
  'delete-task':()=>requestDeleteStep(),
  'delete-card':el=>requestDeleteStep(el.dataset.id),
  'confirm-delete-step':confirmDeleteStep,
  'cancel-connect':()=>{connectFrom=null;updateConnectPrompt();renderEdges();},
  'export-json':()=>exportBackup('json'),'export-yaml':()=>exportBackup('yaml'),
  'close-dialog':el=>el.closest('dialog').close(),
  help:()=>{$('#help-mode').textContent=mode==='server'?'Save writes to this project’s YAML file and backs up the previous version. Changes from your text editor are detected automatically.':'Changes live in this browser tab. Save copy downloads an editable HTML with your current work; reopen that copy to continue. YAML and JSON backups are available under More.';$('#help-dialog').showModal();},
};
document.addEventListener('click',event=>{
  if(event.detail!==0&&performance.now()<layerClickSuppressedUntil&&event.target.closest('#layer-canvas')){event.preventDefault();return;}
  const el=event.target.closest('[data-action]');
  if(el && !el.disabled){event.preventDefault();const act=actions[el.dataset.action];if(act)Promise.resolve(act(el)).catch(e=>toast(e.message,true));}
  if(!event.target.closest('.more-menu')||el)$('#more-menu').open=false;
  // Keyboard activation of connection handles uses native button semantics.
  const port=event.target.closest('[data-port]');
  if(port && event.detail===0){if(port.dataset.port==='out'){connectFrom=port.dataset.id;updateConnectPrompt();}else if(connectFrom)connect(connectFrom,port.dataset.id);}
});
$('#project-title').addEventListener('input',e=>change(doc=>{doc.project.name=e.target.value;},{group:'project-name',inspector:false}));
$('#project-title').addEventListener('blur',()=>{if(!project.project.name.trim())change(doc=>{doc.project.name='Untitled project';},{group:'project-name',inspector:false});});
$('#project-title').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();e.target.blur();}});
$('#inspector').addEventListener('keydown',e=>{
  if(e.isComposing)return;
  if(e.target.matches('.title-input,#step-number')&&e.key==='Enter'&&!e.shiftKey){e.preventDefault();e.target.blur();}
  else if(e.key==='Escape'&&e.target.matches('input,textarea,select')){e.stopPropagation();e.target.blur();}
});
$('#inspector').addEventListener('input',e=>{
  const el=e.target;if(!el.dataset.field||!currentTask())return;
  const field=el.dataset.field,value=['inputs','outputs'].includes(field)?el.value.split('\n').map(x=>x.trim()).filter(Boolean):field==='title'&&!el.value.trim()?'Untitled step':el.value;
  change(doc=>{doc.tasks.find(t=>t.id===selected)[field]=value;},{group:`${selected}-${field}`,inspector:false});
  if(field==='title')resizeTitle();
});
$('#inspector').addEventListener('change',e=>{if(e.target.id==='add-dependency'&&e.target.value)connect(e.target.value,selected);if(e.target.id==='parent-step')reparent(selected,e.target.value||null);if(e.target.id==='step-number'){change(doc=>setStepNumber(doc,selected,Number(e.target.value)),{validate:true});renderInspector();}});
$('#inspector').addEventListener('change',e=>{
  const field=e.target.dataset.layerField;if(!field||!currentTask())return;
  const value=e.target.value, editedId=selected;
  change(doc=>{
    const task=doc.tasks.find(t=>t.id===editedId);
    if(field==='layer'){
      task.layer=value;
      if(value!=='operation')delete task.overview_id;
      if(value!=='processing')delete task.operation_id;
    }else if(value)task[field]=value;else delete task[field];
    return validateProject(doc);
  },{validate:true});
  const editedTask=project.tasks.find(t=>t.id===editedId);
  if(editedTask&&(view==='layers'||(view==='graph'&&taskLayer(editedTask)!=='overview'))){switchView('layers');layerSelectTask(editedId,'plan');}else renderInspector();
});
$('#inspector').addEventListener('change',event=>{
  const axis=event.target.dataset.layerCoordinate;if(!axis||!currentTask())return;
  const value=event.target.valueAsNumber;if(!Number.isFinite(value)||!event.target.checkValidity()){renderInspector();return;}
  const position=layerPositionsSnapshot()[selected];if(!position)return;
  moveLayerNode(selected,axis==='x'?value:position.x,axis==='y'?value:position.y);
  $('#inspector .layer-position-editor').open=true;
});
$('#record-work-form').addEventListener('submit',submitWorkRecord);
$('#record-work-dialog').addEventListener('close',()=>{recordingTaskId=null;});
$('#idea-form').addEventListener('submit',submitIdea);
$('#idea-dialog').addEventListener('close',()=>{editingIdeaId=null;});
$('#delete-idea-form').addEventListener('submit',event=>{
  event.preventDefault();const id=deletingIdeaId;
  if(id&&change(doc=>removeIdea(doc,id),{validate:true})){
    $('#delete-idea-dialog').close();$('#ideas-body [data-action="idea-add"]')?.focus({preventScroll:true});
  }
});
$('#delete-idea-dialog').addEventListener('close',()=>{deletingIdeaId=null;});
$('#ideas-body').addEventListener('change',event=>{
  if(event.target.id==='ideas-filter'){ideasFilter=event.target.value;renderIdeas();}
});
$('#layers-view').addEventListener('pointerdown',event=>{
  const viewport=event.target.closest('#layer-canvas'),node=event.target.closest('.flow-node');
  if(!viewport||event.button!==0||event.isPrimary===false||layerPointer)return;
  if(!node&&event.target.closest('button,a,input,select,[data-action]'))return;
  layerClickSuppressedUntil=0;
  if(document.activeElement?.matches('input,textarea,select'))document.activeElement.blur();
  layerPointer={id:event.pointerId,type:node?'node':'pan',taskId:node?.dataset.id,
    x:event.clientX,y:event.clientY,camera:{...layerCamera},moved:false,
    positions:node?layerPositionsSnapshot():null,before:project,draft:null};
  $('#layers-view').setPointerCapture(event.pointerId);event.preventDefault();
  if(node)$$('.flow-node').find(card=>card.dataset.id===node.dataset.id)?.focus({preventScroll:true});else viewport.classList.add('is-panning');
});
$('#layers-view').addEventListener('pointermove',event=>{
  if(!layerPointer||event.pointerId!==layerPointer.id)return;
  const drag=layerPointer,dx=event.clientX-drag.x,dy=event.clientY-drag.y;
  if(Math.hypot(dx,dy)>5)drag.moved=true;
  if(!drag.moved)return;
  layerCamera.autoFit=false;
  if(drag.type==='node'){
    const origin=drag.positions[drag.taskId];
    drag.draft=layerPositionDraft(drag.before,drag.positions,drag.taskId,origin.x+Math.round(dx/drag.camera.zoom),origin.y+Math.round(dy/drag.camera.zoom));
    renderLayers();
  }else{
    layerCamera.x=drag.camera.x+dx;layerCamera.y=drag.camera.y+dy;applyLayerCamera();
  }
});
function finishLayerPointer(event,cancelled=false) {
  if(!layerPointer||event.pointerId!==layerPointer.id)return;
  const drag=layerPointer;layerPointer=null;
  layerClickSuppressedUntil=performance.now()+350;
  const host=$('#layers-view');if(host.hasPointerCapture(event.pointerId))host.releasePointerCapture(event.pointerId);
  if(cancelled){layerCamera=drag.camera;renderLayers();return;}
  if(drag.type==='node'){
    if(drag.moved&&drag.draft){
      change(()=>drag.draft,{validate:true,inspector:false});
      if(!$('#inspector').hidden)renderInspector();
      $('#edit-announcement').textContent='Card moved. Undo restores its position.';
    }else layerSelectTask(drag.taskId);
  }
  $('#layer-canvas')?.classList.remove('is-panning');
}
$('#layers-view').addEventListener('pointerup',event=>finishLayerPointer(event));
for(const type of ['pointercancel','lostpointercapture'])$('#layers-view').addEventListener(type,event=>finishLayerPointer(event,true));
$('#layers-view').addEventListener('wheel',event=>{
  const viewport=event.target.closest('#layer-canvas');if(!viewport)return;
  event.preventDefault();if(layerPointer)return;
  if(event.ctrlKey||event.metaKey){const r=viewport.getBoundingClientRect();zoomLayerCanvas(Math.exp(-event.deltaY*.006),event.clientX-r.left,event.clientY-r.top);}
  else{layerCamera.x-=event.deltaX;layerCamera.y-=event.deltaY;layerCamera.autoFit=false;applyLayerCamera();}
},{passive:false});
$('#layers-view').addEventListener('focusin',event=>{
  const node=event.target.closest('.flow-node'),viewport=$('#layer-canvas');if(!node||!viewport||layerPointer)return;
  const n=node.getBoundingClientRect(),v=viewport.getBoundingClientRect();
  if(n.left<v.left||n.right>v.right||n.top<v.top||n.bottom>v.bottom){layerCamera.x+=v.left+v.width/2-(n.left+n.width/2);layerCamera.y+=v.top+v.height/2-(n.top+n.height/2);layerCamera.autoFit=false;applyLayerCamera();}
});
new ResizeObserver(()=>{if(view==='layers'&&layerCamera.autoFit)fitLayerCanvas();}).observe($('#layers-view'));
$('#inspector').addEventListener('submit',e=>{if(e.target.id==='connection-form'){e.preventDefault();editEdge($('#connection-source').value,$('#connection-target').value);}});
$('#inspector').addEventListener('keydown',e=>{if(e.target.matches('[role="tab"]')&&['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();const tabs=[...$('#inspector').querySelectorAll('[role="tab"]')].map(el=>el.dataset.tab);inspectorTab=tabs[(tabs.indexOf(inspectorTab)+(e.key==='ArrowRight'?1:tabs.length-1))%tabs.length];renderInspector();$(`#${inspectorTab}-tab`).focus();}});
$('#list-view').addEventListener('change',e=>{if(e.target.dataset.tableStatus)change(doc=>{doc.tasks.find(t=>t.id===e.target.dataset.tableStatus).status=e.target.value;});});
const canvas=$('#canvas');
// Keep navigation controls fixed when keyboard focus reaches off-screen cards.
canvas.addEventListener('focusin',event=>{const node=event.target.closest('.task-node');if(node&&!pointer)keepSelectedVisible(node.dataset.id);});
canvas.addEventListener('scroll',()=>{if(canvas.scrollLeft||canvas.scrollTop){canvas.scrollLeft=0;canvas.scrollTop=0;}},{passive:true});
const controlTarget=target=>target.closest('.canvas-footer,.minimap-wrap,.connection-prompt,.empty-state');
canvas.addEventListener('pointerdown',event=>{
  if(!event.target.closest('.node-title-input'))$('.node-title-input')?.blur();
  if(event.button!==0||controlTarget(event.target)||event.target.closest('[data-node-action],.node-title-input'))return;
  const port=event.target.closest('[data-port]'), node=event.target.closest('.task-node'), edge=event.target.closest('[data-edge]');
  const hierarchy=event.target.closest('[data-hierarchy]'),bundle=event.target.closest('[data-bundle]');
  if(hierarchy){navigateTo(hierarchy.dataset.hierarchy);event.preventDefault();return;}
  if(bundle){revealBundle(bundle.dataset.bundle);event.preventDefault();return;}
  if(port?.dataset.port==='out'){
    connectFrom=port.dataset.id;pointer={type:'connect',id:connectFrom,clientX:event.clientX,clientY:event.clientY,moved:false};updateConnectPrompt();
  } else if(connectFrom&&node){connect(connectFrom,node.dataset.id);event.preventDefault();return;}
  else if(port?.dataset.port==='in'){event.preventDefault();return;}
  else if(edge){selectEdge(edge.dataset.edge);event.preventDefault();return;}
  else if(node){pointer={type:'node',id:node.dataset.id,clientX:event.clientX,clientY:event.clientY,moved:false};}
  else{pointer={type:'pan',x:transform.x,y:transform.y,clientX:event.clientX,clientY:event.clientY,moved:false};canvas.classList.add('panning');}
  if(lastNodeClick && performance.now()-lastNodeClick.time<500 && Math.hypot(event.clientX-lastNodeClick.x,event.clientY-lastNodeClick.y)<8 && ['node','pan'].includes(pointer.type))pointer.renameId=lastNodeClick.id;
  canvas.setPointerCapture(event.pointerId);event.preventDefault();
});
canvas.addEventListener('pointermove',event=>{
  if(!pointer)return;
  const dx=event.clientX-pointer.clientX,dy=event.clientY-pointer.clientY;
  if(Math.abs(dx)+Math.abs(dy)>3)pointer.moved=true;
  if(pointer.type==='pan'){transform.x=pointer.x+dx;transform.y=pointer.y+dy;applyTransform();}
  if(pointer.type==='connect'&&pointer.moved){
    const p=positionOf(pointer.id),{width:NODE_W,height:NODE_H}=taskSize(graphDocument().tasks.find(t=>t.id===pointer.id)),end=pointInWorld(event.clientX,event.clientY);renderEdges();
    $('#edges').insertAdjacentHTML('beforeend',`<path class="edge-preview" d="M ${p.x+NODE_W} ${p.y+NODE_H/2} C ${p.x+300} ${p.y+NODE_H/2}, ${end.x-60} ${end.y}, ${end.x} ${end.y}"/>`);
    const target=document.elementFromPoint(event.clientX,event.clientY)?.closest('.task-node');$$('.task-node').forEach(n=>n.classList.toggle('connect-target',n===target && n.dataset.id!==pointer.id));
  }
});
function finishPointer(event,cancelled=false){
  if(!pointer)return;const action=pointer;pointer=null;canvas.classList.remove('panning');
  if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);
  if(action.moved || cancelled)lastNodeClick=null;
  if(action.renameId && !action.moved && !cancelled){lastNodeClick=null;renameStep(action.renameId);return;}
  if(action.type==='connect'){
    if(cancelled){connectFrom=null;}
    else if(action.moved){const node=document.elementFromPoint(event.clientX,event.clientY)?.closest('.task-node');if(node)connect(action.id,node.dataset.id);else connectFrom=null;}
    // A click leaves a keyboard/touch-friendly pending connection.
  }
  if(action.type==='node'){
    if(!action.moved&&!cancelled){lastNodeClick={id:action.id,x:event.clientX,y:event.clientY,time:performance.now()};navigateTo(action.id);}
  }
  if(action.type==='pan'&&!action.moved&&!cancelled){connectFrom=null;selectedEdge=null;if(!focusMode)selected=null;closeInspector();}
  refresh(false);
}
canvas.addEventListener('pointerup',e=>finishPointer(e));canvas.addEventListener('pointercancel',e=>finishPointer(e,true));
canvas.addEventListener('dblclick',event=>{
  if($('.node-title-input')||controlTarget(event.target)||event.target.closest('[data-port],[data-node-action],.node-title-input,[data-edge],[data-hierarchy],[data-bundle]'))return;
  // Pointer capture and selection redraws can retarget dblclick to the canvas.
  const recent=lastNodeClick && performance.now()-lastNodeClick.time<600 && Math.hypot(event.clientX-lastNodeClick.x,event.clientY-lastNodeClick.y)<8;
  const id=event.target.closest('.task-node')?.dataset.id || (recent?lastNodeClick.id:null);
  lastNodeClick=null;
  if(id)renameStep(id);else addBlankStep();
});
canvas.addEventListener('wheel',e=>{if(controlTarget(e.target))return;e.preventDefault();const r=canvas.getBoundingClientRect();if(e.shiftKey){transform.x-=e.deltaY;transform.y-=e.deltaX;applyTransform();}else zoom(Math.exp(-e.deltaY*.0015),e.clientX-r.left,e.clientY-r.top);},{passive:false});
$('#minimap-wrap').addEventListener('pointerdown',startMinimapDrag);
$('#minimap-wrap').addEventListener('pointermove',moveMinimapDrag);
$('#minimap-wrap').addEventListener('pointerup',finishMinimapDrag);
$('#minimap-wrap').addEventListener('pointercancel',event=>finishMinimapDrag(event,true));
$('#minimap-wrap').addEventListener('lostpointercapture',event=>finishMinimapDrag(event,true));
$('#minimap-wrap').addEventListener('click',clickMinimap);
$('#delete-step-dialog').addEventListener('close',()=>{if(!$('#delete-step-dialog').open)pendingDeletion=null;});

document.addEventListener('keydown',e=>{
  const editing=e.target.matches('input,textarea,select')||e.target.isContentEditable;
  if(layerPointer){e.preventDefault();if(e.key==='Escape'){finishLayerPointer({pointerId:layerPointer.id},true);}return;}
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();if($('dialog[open]'))return;document.activeElement?.blur();save();return;}
  if($('dialog[open]'))return;
  if(e.key==='Escape'&&ideasOpen&&$('#ideas-panel').contains(e.target)){e.preventDefault();closeIdeas();return;}
  if(editing)return;
  if(e.key==='Escape'){if($('#more-menu').open){$('#more-menu').open=false;return;}if(ideasOpen){e.preventDefault();closeIdeas();return;}if(connectFrom){actions['cancel-connect']();return;}clearSelection();return;}
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();e.shiftKey?redo():undo();return;}
  if(e.ctrlKey||e.metaKey||e.altKey)return;
  if(ideasOpen&&$('#ideas-panel').contains(e.target))return;
  if(e.key.toLowerCase()==='f'){e.preventDefault();e.shiftKey?actions.focus():view==='layers'?fitLayerCanvas(true):fitGraph();}
  if(e.key.toLowerCase()==='o'){e.preventDefault();actions.overview();}
  if(e.key.toLowerCase()==='n'){e.preventDefault();actions.add();}
  if(e.key==='?'){e.preventDefault();actions.help();}
  if(['Delete','Backspace'].includes(e.key)&&selectedEdge){e.preventDefault();actions['delete-edge']();}
  else if(['Delete','Backspace'].includes(e.key)&&e.target.matches('.task-node,.flow-node')){e.preventDefault();requestDeleteStep(e.target.dataset.id);}
  if(['Enter',' '].includes(e.key)&&e.target.matches('.task-node')){e.preventDefault();navigateTo(e.target.dataset.id);$('#inspector .title-input')?.focus();}
  if(['Enter',' '].includes(e.key)&&e.target.matches('[data-hierarchy]')){e.preventDefault();navigateTo(e.target.dataset.hierarchy);}
  if(['Enter',' '].includes(e.key)&&e.target.matches('[data-bundle]')){e.preventDefault();revealBundle(e.target.dataset.bundle);}
  if(['Enter',' '].includes(e.key)&&e.target.matches('[data-edge]')){e.preventDefault();selectEdge(e.target.dataset.edge);$('#connection-source')?.focus();}
  if(['Enter',' '].includes(e.key)&&e.target.matches('.layer-dependency-hit')){e.preventDefault();actions['layer-edge'](e.target);$('#connection-source')?.focus();}
  if(['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key)&&e.target.matches('.flow-node')){
    e.preventDefault();const id=e.target.dataset.id,position=layerPositionsSnapshot()[id],amount=e.shiftKey?40:10;
    if(position)moveLayerNode(id,position.x+(e.key==='ArrowRight'?amount:e.key==='ArrowLeft'?-amount:0),position.y+(e.key==='ArrowDown'?amount:e.key==='ArrowUp'?-amount:0),`layer-move-${id}`);
    $$('.flow-node').find(node=>node.dataset.id===id)?.focus({preventScroll:true});
  }
  if(['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key)&&e.target.matches('.task-node')){
    e.preventDefault();const nodes=$$('.task-node:not([hidden])'),index=nodes.indexOf(e.target);
    const next=nodes[Math.max(0,Math.min(nodes.length-1,index+(['ArrowRight','ArrowDown'].includes(e.key)?1:-1)))];
    next?.focus({preventScroll:true});if(next)keepSelectedVisible(next.dataset.id);
  }
});
window.addEventListener('beforeunload',e=>{if(dirty()){e.preventDefault();e.returnValue='';}});
new ResizeObserver(()=>applyTransform()).observe(canvas);
$$('[data-icon]').forEach(el=>el.innerHTML=icon(el.dataset.icon));
$('#add-button').setAttribute('aria-label','Add step');
refresh();
async function init(){
  if(portable)mode='preview';
  else{
    try{
      const data=await request('/api/project');project=ensurePositions(validateProject(data.document));baseline=JSON.stringify(project);revision=data.revision;filePath=data.file;mode='server';
    }catch(error){mode='error';alertFile(error.status===401 ? error.message : `Cannot open this project: ${error.message}. Check the server and SSH tunnel, then reload.`);}
  }
  selected=null;selectedEdge=null;closeInspector();switchView(project.project.presentation==='layers'?'layers':'graph');refresh();fitGraph();
  frameGraphOpening();
  logoMotion.play('load');
  setInterval(checkExternal,3500);
}
init();

matchMedia('(max-width:700px)').addEventListener('change',()=>{
  $('.canvas-column').inert=ideasOpen&&matchMedia('(max-width:700px)').matches;
});
