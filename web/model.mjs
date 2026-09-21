/** Pure project model. No DOM, storage, or renderer dependencies. */
export const STATUS = {
  todo: { label: 'To do', color: '#8598a7' },
  in_progress: { label: 'In progress', color: '#f3b705' },
  blocked: { label: 'Blocked', color: '#bd655a' },
  done: { label: 'Done', color: '#0a7abf' },
};
export const MAX_SUBSTEPS = 200;
export const clone = (value) => JSON.parse(JSON.stringify(value));

function assertJsonSafe(value, active = new Set(), depth = 0) {
  if (depth > 50) throw Error('Project nesting is too deep.');
  if (value && typeof value === 'object') {
    if (active.has(value)) throw Error('Recursive values are not supported.');
    active.add(value);
    for (const [key, child] of Object.entries(value)) {
      if (['__proto__', 'constructor', 'prototype'].includes(key)) throw Error('Unsupported object key.');
      assertJsonSafe(child, active, depth + 1);
    }
    active.delete(value);
  } else if (typeof value === 'number' && (!Number.isFinite(value) || Math.abs(value) > Number.MAX_SAFE_INTEGER)) {
    throw Error('Numbers must be finite and within JavaScript’s safe numeric range.');
  } else if (value !== null && !['string', 'boolean', 'number'].includes(typeof value)) {
    throw Error('Only JSON-compatible values are supported.');
  }
}
export function validateProject(input) {
  assertJsonSafe(input);
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw Error('The project must be an object.');
  if (input.schema_version !== 1) throw Error('schema_version must be 1.');
  if (!input.project || typeof input.project.name !== 'string' || !input.project.name.trim()) throw Error('Give the project a name.');
  if (!Array.isArray(input.tasks) || input.tasks.length > 500) throw Error('tasks must be an array with at most 500 tasks.');
  for (const field of ['id', 'description']) if (input.project[field] !== undefined && typeof input.project[field] !== 'string') throw Error(`project.${field} must be text.`);
  const project = clone(input);
  const ids = new Set();
  project.tasks = project.tasks.map((t) => {
    if (!t || typeof t !== 'object' || typeof t.id !== 'string' || !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(t.id)) throw Error('Task IDs must use letters, numbers, underscores, or hyphens (1–64 characters).');
    if (ids.has(t.id)) throw Error(`Duplicate task ID: ${t.id}`);
    ids.add(t.id);
    if (typeof t.title !== 'string' || !t.title.trim()) throw Error(`Give task “${t.id}” a title.`);
    const status = t.status === undefined ? 'todo' : t.status;
    if (typeof status !== 'string' || !Object.hasOwn(STATUS, status)) throw Error(`Invalid status for ${t.id}.`);
    const normalized = { status: 'todo', goal: '', depends_on: [], inputs: [], outputs: [], notes: '', ...t };
    for (const field of ['goal', 'notes', 'agent_instructions']) {
      if (normalized[field] !== undefined && typeof normalized[field] !== 'string') throw Error(`${t.id}.${field} must be text.`);
    }
    for (const field of ['depends_on', 'inputs', 'outputs']) {
      if (!Array.isArray(normalized[field]) || normalized[field].some(x => typeof x !== 'string')) throw Error(`${t.id}.${field} must be a list of strings.`);
    }
    if (new Set(normalized.depends_on).size !== normalized.depends_on.length) throw Error(`Duplicate dependency on ${t.id}.`);
    // Legacy-only input validation. Checklist UI is removed; valid entries are
    // converted to normal child tasks below, without writing the source file.
    if (Object.hasOwn(normalized, 'substeps')) {
      if (!Array.isArray(normalized.substeps) || normalized.substeps.length > MAX_SUBSTEPS) {
        throw Error(`${t.id}.substeps must be a list with at most ${MAX_SUBSTEPS} entries.`);
      }
      const subIds = new Set();
      normalized.substeps = normalized.substeps.map(sub => {
        if (!sub || typeof sub !== 'object' || Array.isArray(sub) ||
            typeof sub.id !== 'string' || !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(sub.id)) {
          throw Error(`Invalid substep ID on ${t.id}.`);
        }
        if (subIds.has(sub.id)) throw Error(`Duplicate substep ID on ${t.id}: ${sub.id}`);
        subIds.add(sub.id);
        if (typeof sub.title !== 'string' || !sub.title.trim()) throw Error(`Give substep ${sub.id} a title.`);
        const normalizedSub = { status: 'todo', notes: '', ...sub };
        if (typeof normalizedSub.status !== 'string' || !Object.hasOwn(STATUS, normalizedSub.status)) throw Error(`Invalid status for substep ${sub.id}.`);
        if (typeof normalizedSub.notes !== 'string') throw Error(`Substep ${sub.id}.notes must be text.`);
        return normalizedSub;
      });
    }
    if (Object.hasOwn(normalized, 'step_number') && (!Number.isSafeInteger(normalized.step_number) || normalized.step_number < 1)) throw Error(`${t.id}.step_number must be a positive whole number.`);
    if (normalized.parent_id !== undefined && normalized.parent_id !== null && typeof normalized.parent_id !== 'string') throw Error(`${t.id}.parent_id must be a task ID or null.`);
    return normalized;
  });
  // Upgrade the old one-level checklist into real child tasks, in memory only.
  // Unknown substep metadata is retained; saving later uses the normal disk backup.
  if (project.tasks.some(t => Object.hasOwn(t, 'substeps'))) {
    const added = [];
    for (const parent of project.tasks) {
      for (const sub of parent.substeps || []) {
        const base = `${parent.id}_${sub.id}`.slice(0, 54);
        let id = base, suffix = 2;
        while (ids.has(id)) id = `${base}_${suffix++}`;
        ids.add(id);
        const child = {id, title: sub.title, status: sub.status, notes: sub.notes,
          goal: '', inputs: [], outputs: [], depends_on: [], parent_id: parent.id};
        const extra = Object.keys(sub).filter(k => !['id','title','status','notes'].includes(k));
        if (extra.length) child.legacy_substep = clone(sub);
        added.push(child);
      }
      delete parent.substeps;
    }
    project.tasks.push(...added);
    if (project.tasks.length > 500) throw Error('Converting existing substeps would exceed the 500-step limit. Your original file is unchanged.');
    return validateProject(project);
  }
  const assigned = project.tasks.filter(t=>!t.parent_id && t.step_number !== undefined).map(t=>t.step_number);
  if(new Set(assigned).size !== assigned.length)throw Error('Main step numbers must be unique.');
  const parents = new Map(project.tasks.map(t => [t.id, t.parent_id]));
  for (const task of project.tasks) {
    if (task.parent_id != null && !ids.has(task.parent_id)) throw Error(`Unknown parent “${task.parent_id}” on ${task.id}.`);
    const seen = new Set([task.id]);
    let parent = task.parent_id;
    while (parent != null) {
      if (seen.has(parent)) throw Error('Parent cycle: a step cannot belong to itself or one of its descendants.');
      seen.add(parent); parent = parents.get(parent);
    }
  }
  for (const task of project.tasks) for (const dependency of task.depends_on) {
    if (!ids.has(dependency)) throw Error(`Unknown dependency “${dependency}” on ${task.id}.`);
    if (dependency === task.id) throw Error('A task cannot depend on itself.');
  }
  const visited = new Set(), active = new Set(), byId = new Map(project.tasks.map(t => [t.id, t]));
  function visit(id) {
    if (active.has(id)) throw Error('This dependency would create a cycle. A step cannot eventually depend on itself.');
    if (visited.has(id)) return;
    active.add(id);
    for (const d of byId.get(id).depends_on) visit(d);
    active.delete(id); visited.add(id);
  }
  project.tasks.forEach(t => visit(t.id));
  if (project.layout !== undefined && (!project.layout || typeof project.layout !== 'object' || Array.isArray(project.layout))) throw Error('layout must be an object.');
  project.layout ??= {};
  project.layout.positions ??= {};
  if (!project.layout.positions || typeof project.layout.positions !== 'object' || Array.isArray(project.layout.positions)) throw Error('layout.positions must be an object.');
  for (const [id, p] of Object.entries(project.layout.positions)) {
    if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y) || Math.abs(p.x) > 10000000 || Math.abs(p.y) > 10000000) throw Error(`Invalid layout position: ${id}`);
  }
  return project;
}
export function addDependency(project, source, target) {
  if (!project.tasks.some(t => t.id === source)) throw Error('Source task not found.');
  if (!project.tasks.some(t => t.id === target)) throw Error('Target task not found.');
  const next = clone(project), task = next.tasks.find(t => t.id === target);
  if (!task.depends_on.includes(source)) task.depends_on.push(source);
  return validateProject(next);
}
/**
 * A dependency drawn next to a child can introduce a sibling into its branch.
 * This is an editing operation, NOT validation or a load-time migration.
 * Existing hierarchy always wins. Parents/ancestors are never moved, and
 * mixed-branch dependencies remain valid without silently merging branches.
 */
export function addBranchDependency(project, source, target) {
  const existed = project.tasks.find(t => t.id === target)?.depends_on.includes(source);
  const next = addDependency(project, source, target); // Validate the DAG first.
  if (existed) return next;
  const byId = new Map(next.tasks.map(t => [t.id, t]));
  const a = byId.get(source), b = byId.get(target);
  const child = a.parent_id && !b.parent_id ? a : b.parent_id && !a.parent_id ? b : null;
  if (!child) return next;
  const candidate = child === a ? b : a;
  const parent = child.parent_id;
  // Do not turn an existing container (including the child's own parent) into a child.
  if (childrenOf(next, candidate.id).length || ancestorIds(next, child.id).includes(candidate.id)) return next;
  // A root leaf with established links to another branch is ambiguous. Keep it
  // independent rather than letting the last-drawn arrow choose its membership.
  const neighbors = next.tasks.filter(t => candidate.depends_on.includes(t.id) || t.depends_on.includes(candidate.id));
  const ancestors = new Set([parent, ...ancestorIds(next, parent)]);
  if (neighbors.some(t => t.parent_id ? t.parent_id !== parent && !ancestors.has(t.id)
      : childrenOf(next,t.id).length)) return next;
  candidate.parent_id = parent;
  delete candidate.step_number;
  return validateProject(next);
}

export function removeTask(project, id) {
  const next = clone(project);
  const parent = next.tasks.find(t => t.id === id)?.parent_id ?? null;
  next.tasks = next.tasks.filter(t => t.id !== id).map(t => {
    t.depends_on = t.depends_on.filter(d => d !== id);
    if (t.parent_id === id) { delete t.step_number; if (parent) t.parent_id = parent; else delete t.parent_id; }
    return t;
  });
  delete next.layout.positions[id];
  return next;
}
export function autoLayout(project) {
  if (project.tasks.some(t => t.parent_id)) return layoutHierarchy(project);
  const next = clone(project), byId = new Map(next.tasks.map(t => [t.id, t])), levels = new Map();
  function level(id) {
    if (levels.has(id)) return levels.get(id);
    const value = Math.max(-1, ...byId.get(id).depends_on.map(level)) + 1;
    levels.set(id, value); return value;
  }
  const columns = new Map();
  next.tasks.forEach(t => { const x = level(t.id); if (!columns.has(x)) columns.set(x, []); columns.get(x).push(t); });
  const maxRows = Math.max(1, ...[...columns.values()].map(c => c.length));
  next.layout ??= {}; next.layout.positions ??= {};
  for (const [column, tasks] of columns) tasks.forEach((t, row) => {
    next.layout.positions[t.id] = { x: column * 316, y: row * 218 + (maxRows - tasks.length) * 109 };
  });
  return next;
}
/** Dependency stages are derived from edges only; parenthood never adds an edge. */
export function dependencyStages(project) {
  const stages = new Map(project.tasks.map(task => [task.id, 0]));
  const remaining = new Map(), dependents = new Map(project.tasks.map(task => [task.id, []]));
  for (const task of project.tasks) {
    remaining.set(task.id, task.depends_on.length);
    for (const source of task.depends_on) {
      if (!dependents.has(source)) throw Error(`Unknown dependency “${source}” on ${task.id}.`);
      dependents.get(source).push(task.id);
    }
  }
  const ready = project.tasks.filter(task => !remaining.get(task.id)).map(task => task.id);
  for (let cursor = 0; cursor < ready.length; cursor++) {
    const source = ready[cursor];
    for (const target of dependents.get(source)) {
      stages.set(target, Math.max(stages.get(target), stages.get(source) + 1));
      remaining.set(target, remaining.get(target) - 1);
      if (!remaining.get(target)) ready.push(target);
    }
  }
  if (ready.length !== project.tasks.length) throw Error('This dependency would create a cycle.');
  return stages;
}

/** A presentation-only layout: saved freeform positions and metadata are untouched. */
export function stageLayout(project) {
  const ranks = dependencyStages(project), columns = new Map();
  for (const {task} of stepOutline(project)) {
    const index = ranks.get(task.id);
    if (!columns.has(index)) columns.set(index, []);
    columns.get(index).push(task);
  }
  const padding = 24, header = 48, rowGap = 34, columnGap = 84;
  const measured = [...columns].sort(([a], [b]) => a - b).map(([index, tasks]) => ({
    index, tasks,
    width: Math.max(...tasks.map(task => taskSize(task).width)) + 2 * padding,
    contentHeight: tasks.reduce((height, task) => height + taskSize(task).height, 0) + (tasks.length - 1) * rowGap,
  }));
  const contentHeight = Math.max(0, ...measured.map(column => column.contentHeight));
  const positions = {}, stages = [];
  let x = 0;
  for (const column of measured) {
    let y = header + padding + (contentHeight - column.contentHeight) / 2;
    for (const task of column.tasks) {
      const size = taskSize(task);
      positions[task.id] = {x: x + (column.width - size.width) / 2, y};
      y += size.height + rowGap;
    }
    stages.push({index: column.index, x, y: 0, width: column.width,
      height: header + 2 * padding + contentHeight, taskIds: column.tasks.map(task => task.id)});
    x += column.width + columnGap;
  }
  return {positions, stages};
}

/** Trace both directions independently so another prerequisite is not highlighted. */
function dependencyPath(project, id) {
  const upstream = new Map(project.tasks.map(task => [task.id, task.depends_on]));
  const ids = new Set(), edges = new Set();
  if (!upstream.has(id)) return {ids, edges};
  const downstream = new Map(project.tasks.map(task => [task.id, []]));
  for (const task of project.tasks) for (const source of task.depends_on) downstream.get(source)?.push(task.id);
  ids.add(id);
  for (const graph of [upstream, downstream]) {
    const visited = new Set([id]), queue = [id];
    for (let cursor = 0; cursor < queue.length; cursor++) {
      const current = queue[cursor];
      for (const next of graph.get(current) || []) {
        edges.add(graph === upstream ? `${next}|${current}` : `${current}|${next}`);
        if (visited.has(next)) continue;
        visited.add(next); ids.add(next); queue.push(next);
      }
    }
  }
  return {ids, edges};
}
export const dependencyPathIds = (project, id) => dependencyPath(project, id).ids;
/** Edge keys omit shortcuts that bypass the selected step, even if both ends are on its path. */
export const dependencyPathEdges = (project, id) => dependencyPath(project, id).edges;
/** Deliberately conservative YAML emitter: quoted scalar values, no tags/aliases. */
export function toYaml(value, indent = 0) {
  const pad = ' '.repeat(indent);
  const scalar = v => v === null ? 'null' : typeof v === 'string' ? JSON.stringify(v) : String(v);
  if (Array.isArray(value)) {
    if (!value.length) return '[]';
    return value.map(v => typeof v === 'object' && v !== null && Object.keys(v).length
      ? `${pad}-\n${toYaml(v, indent + 2)}` : `${pad}- ${typeof v === 'object' && v !== null ? (Array.isArray(v) ? '[]' : '{}') : scalar(v)}`).join('\n');
  }
  if (value !== null && typeof value === 'object') {
    if (!Object.keys(value).length) return '{}';
    return Object.entries(value).map(([k, v]) => {
      const key = /^[a-zA-Z_][\w-]*$/.test(k) ? k : JSON.stringify(k);
      if (v !== null && typeof v === 'object' && Object.keys(v).length) return `${pad}${key}:\n${toYaml(v, indent + 2)}`;
      return `${pad}${key}: ${v !== null && typeof v === 'object' ? (Array.isArray(v) ? '[]' : '{}') : scalar(v)}`;
    }).join('\n');
  }
  return scalar(value);
}

/** Create a real, saveable step before asking the user for a name. */
export function insertBlankStep(project, position, dependency = null, parent = null) {
  const next = clone(project);
  if (next.tasks.length >= 500) throw Error('A workflow can contain at most 500 steps.');
  if (dependency !== null && !next.tasks.some(t => t.id === dependency)) throw Error('Dependency not found.');
  if (parent !== null && !next.tasks.some(t => t.id === parent)) throw Error('Parent step not found.');
  parent ??= dependency ? next.tasks.find(t => t.id === dependency)?.parent_id ?? null : null;
  const ids = new Set(next.tasks.map(t => t.id));
  let n = 1;
  while (ids.has(`step_${n}`)) n++;
  const id = `step_${n}`;
  next.tasks.push({ id, title: 'Untitled step', status: 'todo', goal: '', depends_on: dependency ? [dependency] : [], inputs: [], outputs: [], notes: '', ...(parent ? {parent_id:parent} : {}) });
  next.layout ??= {};
  next.layout.positions ??= {};
  next.layout.positions[id] = { x: Math.round(position.x), y: Math.round(position.y) };
  return { document: validateProject(next), id };
}



/** Children are ordinary task records. Parenthood never creates a dependency. */
export const childrenOf = (project, id) => project.tasks.filter(t => t.parent_id === id);
export function descendantIds(project, id) {
  const children = new Map();
  for (const t of project.tasks) {
    if (!children.has(t.parent_id)) children.set(t.parent_id, []);
    children.get(t.parent_id).push(t.id);
  }
  const result = new Set(), stack = [...(children.get(id) || [])];
  while (stack.length) {
    const child = stack.pop(); if (child === id || result.has(child)) continue;
    result.add(child); stack.push(...(children.get(child) || []));
  }
  return result;
}
export function ancestorIds(project, id) {
  const byId = new Map(project.tasks.map(t => [t.id,t]));
  const result = [], seen = new Set([id]); let parent = byId.get(id)?.parent_id;
  while (parent && byId.has(parent) && !seen.has(parent)) {
    result.push(parent); seen.add(parent); parent = byId.get(parent).parent_id;
  }
  return result;
}
export const taskSize = task => task?.parent_id ? {width:212,height:136} : {width:240,height:148};
export function setParent(project, id, parent = null) {
  const next = clone(project), task = next.tasks.find(t => t.id === id);
  if (!task) throw Error('Step not found.');
  if ((task.parent_id ?? null) !== parent) delete task.step_number;
  if (parent === null) delete task.parent_id; else task.parent_id = parent;
  return validateProject(next);
}
export function moveBranch(project, id, dx, dy) {
  const next = clone(project), ids = new Set([id, ...descendantIds(project,id)]);
  for (const key of ids) {
    const p = next.layout.positions[key]; if (!p) continue;
    p.x = Math.round(p.x + dx); p.y = Math.round(p.y + dy);
  }
  return next;
}
/** Layout trees downwards; root dependencies remain left-to-right when possible.
 * Internal dependencies do not override containment or invent implicit sequence.
 */
function layoutHierarchy(project) {
  const next = clone(project), roots = next.tasks.filter(t => !t.parent_id);
  const kids = new Map(), byId = new Map(next.tasks.map(t=>[t.id,t]));
  for (const t of next.tasks) {
    if (!kids.has(t.parent_id)) kids.set(t.parent_id, []);
    kids.get(t.parent_id).push(t);
  }
  const widths = new Map(), heights = new Map();
  function measure(t) {
    const children = kids.get(t.id) || [], size = taskSize(t);
    children.forEach(measure);
    widths.set(t.id, Math.max(size.width, children.reduce((n,c)=>n+widths.get(c.id),0) + Math.max(0,children.length-1)*48));
    heights.set(t.id, size.height + (children.length ? 86 + Math.max(...children.map(c=>heights.get(c.id))) : 0));
  }
  roots.forEach(measure);
  const rootIds = new Set(roots.map(t=>t.id)), ranks = new Map();
  function rank(t) {
    if (ranks.has(t.id)) return ranks.get(t.id);
    const value = Math.max(-1,...t.depends_on.filter(id=>rootIds.has(id)).map(id=>rank(byId.get(id))))+1;
    ranks.set(t.id,value); return value;
  }
  const columns = new Map();
  for (const root of roots) {const level=rank(root);if(!columns.has(level))columns.set(level,[]);columns.get(level).push(root);}
  const positions = {};
  function place(t,left,top) {
    positions[t.id] = {x:Math.round(left+(widths.get(t.id)-taskSize(t).width)/2),y:Math.round(top)};
    const children=kids.get(t.id)||[];
    const total=children.reduce((n,c)=>n+widths.get(c.id),0)+Math.max(0,children.length-1)*48;
    let x=left+(widths.get(t.id)-total)/2;
    for(const child of children) {place(child,x,top+taskSize(t).height+86);x+=widths.get(child.id)+48;}
  }
  let x=0;
  for(const [,col] of [...columns].sort((a,b)=>a[0]-b[0])) {
    const width=Math.max(...col.map(t=>widths.get(t.id)));let y=0;
    for(const root of col) {place(root,x+(width-widths.get(root.id))/2,y);y+=heights.get(root.id)+100;}
    x+=width+120;
  }
  next.layout ??= {};next.layout.positions=positions;
  return next;
}

/** Hierarchical display numbers are derived without rewriting workflow data. */
export function stepOutline(project) {
  const branches=new Map(), roots=project.tasks.filter(t=>!t.parent_id);
  const used=new Set(roots.filter(t=>t.step_number!==undefined).map(t=>t.step_number));
  const numbers=new Map();let next=1;
  for(const task of roots){
    if(task.step_number!==undefined)numbers.set(task.id,task.step_number);
    else {while(used.has(next))next++;numbers.set(task.id,next);used.add(next++);}
  }
  for(const task of project.tasks){const parent=task.parent_id || null;if(!branches.has(parent))branches.set(parent,[]);branches.get(parent).push(task);}
  const rows=[];
  function append(task,number,depth){rows.push({task,number,depth});(branches.get(task.id)||[]).forEach((child,index)=>append(child,`${number}.${index+1}`,depth+1));}
  roots.sort((a,b)=>numbers.get(a.id)-numbers.get(b.id)).forEach(task=>append(task,String(numbers.get(task.id)),0));
  return rows;
}
/** Assign a main-step number, swapping any occupant in a single undoable edit. */
export function setStepNumber(project,id,number) {
  if(!Number.isSafeInteger(number)||number<1)throw Error('Step number must be a positive whole number.');
  const next=clone(project),task=next.tasks.find(t=>t.id===id);
  if(!task || task.parent_id)throw Error('Only main steps have editable numbers.');
  const roots=stepOutline(next).filter(row=>row.depth===0),old=Number(roots.find(row=>row.task.id===id).number);
  if(old===number)return next;
  for(const row of roots)row.task.step_number=row.task.id===id?number:Number(row.number)===number?old:Number(row.number);
  return validateProject(next);
}
