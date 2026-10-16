import test from 'node:test';
import assert from 'node:assert/strict';
import {validateProject, taskLayer, overviewSteps, operationsFor, addOperationRecord,
  selectOperationRecord, removeTask, setParent, dependencyStages, toYaml} from '../web/model.mjs';

const document = () => ({schema_version: 1, project: {name: 'Research'}, tasks: [
  {id: 'question', title: 'Define the question'},
  {id: 'evidence', title: 'Gather evidence', layer: 'overview'},
  {id: 'search', title: 'Search literature', parent_id: 'question', operation_type: 'literature'},
  {id: 'screen', title: 'Screen papers', parent_id: 'search'},
  {id: 'download', title: 'Download data', layer: 'operation', overview_id: 'evidence', operation_type: 'download'},
  {id: 'normalize', title: 'Normalize counts', layer: 'operation', overview_id: 'evidence', parent_id: 'question'},
]});
const fresh = () => validateProject(document());
const record = (id = 'run1') => ({id, recorded_at: '2026-10-16T12:00:00Z',
  status: 'recorded', method: 'Search title and abstract', parameters: 'Query: example',
  inputs: ['query.txt'], outputs: ['references.json'], changes: 'Added references'});

test('legacy layers are derived without adding fields or changing status, edges, or positions', () => {
  const p = fresh(), before = structuredClone(p);
  assert.deepEqual(overviewSteps(p).map(task => task.id), ['question', 'evidence']);
  assert.equal(taskLayer(p.tasks[2]), 'operation');
  assert.deepEqual(operationsFor(p, 'question').map(task => task.id), ['search', 'screen']);
  assert.deepEqual(operationsFor(p, 'evidence').map(task => task.id), ['download', 'normalize']);
  assert.deepEqual(p, before);
  assert.equal(Object.hasOwn(p.tasks[0], 'layer'), false);
  assert.equal(Object.hasOwn(p.tasks[2], 'records'), false);
  assert.deepEqual([...dependencyStages(p).values()], [0, 0, 0, 0, 0, 0]);
});

test('nearest overview governs inherited membership without treating associations as parentage', () => {
  const p = fresh();
  p.tasks[2].layer = 'overview';
  assert.deepEqual(operationsFor(p, 'search').map(task => task.id), ['screen']);
  assert.equal(p.tasks[4].parent_id, undefined);
  assert.deepEqual(p.tasks[4].depends_on, []);
  validateProject(p);
});

test('records append without modifying earlier runs, selecting results, or completing tasks', () => {
  const p = fresh(), r = record(), before = structuredClone(p);
  const q = addOperationRecord(p, 'search', r);
  const next = addOperationRecord(q, 'search', {...record('run2'), status: 'completed', method: 'Expanded search'});
  assert.deepEqual(p, before);
  assert.deepEqual(r, record());
  assert.deepEqual(next.tasks[2].records[0], r);
  assert.equal(q.tasks[2].records.length, 1);
  assert.equal(next.tasks[2].status, 'todo');
  assert.equal(next.tasks[2].selected_record_id, undefined);
  const selected = selectOperationRecord(next, 'search', 'run2');
  assert.equal(selected.tasks[2].selected_record_id, 'run2');
  assert.equal(selected.tasks[2].status, 'todo');
  assert.equal(next.tasks[2].selected_record_id, undefined);
});

test('record helpers reject missing tasks, overview tasks, duplicate records, and invalid selection atomically', () => {
  const p = addOperationRecord(fresh(), 'search', record()), before = structuredClone(p);
  for (const id of ['missing', 'question']) {
    assert.throws(() => addOperationRecord(p, id, record()));
    assert.throws(() => selectOperationRecord(p, id, 'run1'));
  }
  assert.throws(() => addOperationRecord(p, 'search', record()), /Duplicate record/);
  assert.throws(() => selectOperationRecord(p, 'search', 'missing'), /selected record/);
  assert.deepEqual(p, before);
});

test('new fields and unknown metadata survive normalization and YAML export', () => {
  const p = fresh();
  p.tasks[2].method = 'Review'; p.tasks[2].parameters = 'Search terms'; p.tasks[2].rationale = 'Find prior evidence';
  p.tasks[2].metadata = {owner: 'Researcher'};
  const q = addOperationRecord(p, 'search', {...record(), rationale: 'Capture prior evidence', custom: {checksum: 'example'}});
  assert.deepEqual(validateProject(q), q);
  assert.deepEqual(q.tasks[2].metadata, {owner: 'Researcher'});
  assert.deepEqual(q.tasks[2].records[0].custom, {checksum: 'example'});
  q.tasks[2].rationale = 'Plan changed later';
  assert.equal(q.tasks[2].records[0].rationale, 'Capture prior evidence');
  assert.match(toYaml(q), /records:/);
  assert.match(toYaml(q), /checksum: "example"/);
});

test('invalid layer fields and overview references fail validation', () => {
  for (const changes of [{layer: 'details'}, {layer: null}, {overview_id: 'missing'}, {overview_id: 'search'},
    {overview_id: 'screen'}, {overview_id: null}, {operation_type: []}, {method: {}}, {parameters: 42}, {rationale: true}]) {
    const p = fresh(); Object.assign(p.tasks[2], changes);
    assert.throws(() => validateProject(p), JSON.stringify(changes));
  }
  const p = fresh(); p.tasks[0].overview_id = 'evidence';
  assert.throws(() => validateProject(p), /overview association/);
});

test('record validation requires explicit method, time, status, safe IDs, and typed metadata', () => {
  for (const changes of [{id: '../run'}, {id: 'x'.repeat(65)}, {id: null}, {recorded_at: ''}, {recorded_at: 3},
    {method: ' '}, {method: null}, {status: 'done'}, {status: null}, {performed_at: []}, {parameters: {}},
    {rationale: {}}, {changes: true}, {code: []}, {software: {}}, {notes: null}, {inputs: 'file'}, {outputs: [2]}]) {
    assert.throws(() => addOperationRecord(fresh(), 'search', {...record(), ...changes}), JSON.stringify(changes));
  }
  for (const field of ['id', 'recorded_at', 'method', 'status']) {
    const r = record(); delete r[field];
    assert.throws(() => addOperationRecord(fresh(), 'search', r), field);
  }
  const p = fresh(); p.tasks[2].records = {};
  assert.throws(() => validateProject(p), /records/);
});

test('record IDs are scoped to one operation and bounded without truncation', () => {
  let p = addOperationRecord(fresh(), 'search', record());
  p = addOperationRecord(p, 'screen', record());
  p.tasks[2].records = Array.from({length: 200}, (_, i) => record(`run${i}`));
  validateProject(p);
  assert.throws(() => addOperationRecord(p, 'search', record('overflow')), /200/);
  assert.equal(p.tasks[2].records.length, 200);
});

test('deleting overview cleans explicit references without removing operation history', () => {
  const p = addOperationRecord(fresh(), 'download', record()), before = structuredClone(p);
  const q = removeTask(p, 'evidence');
  validateProject(q);
  assert.equal(q.tasks.find(task => task.id === 'download').overview_id, undefined);
  assert.deepEqual(q.tasks.find(task => task.id === 'download').records, [record()]);
  assert.equal(q.tasks.find(task => task.id === 'download').layer, 'operation');
  assert.deepEqual(p, before);
});

test('deleting nested overview reattaches associations to its enclosing overview', () => {
  const p = fresh(); p.tasks[1].parent_id = 'question';
  const q = removeTask(p, 'evidence');
  validateProject(q);
  assert.equal(q.tasks.find(task => task.id === 'download').overview_id, 'question');
  assert.equal(q.tasks.find(task => task.id === 'download').parent_id, undefined);
});

test('reparenting cannot silently invalidate explicit associations', () => {
  const p = fresh(); p.tasks[2].overview_id = 'evidence';
  assert.throws(() => setParent(p, 'search'), /overview association/);
  assert.equal(p.tasks[2].parent_id, 'question');
  p.tasks[2].layer = 'operation';
  const q = setParent(p, 'search');
  assert.equal(q.tasks[2].overview_id, 'evidence');
});

test('existing records survive inferred role changes when legacy children are promoted', () => {
  const p = addOperationRecord(fresh(), 'search', record());
  const q = removeTask(p, 'question');
  validateProject(q);
  assert.deepEqual(q.tasks.find(task => task.id === 'search').records, [record()]);
  assert.equal(taskLayer(q.tasks.find(task => task.id === 'search')), 'operation');
  const r = addOperationRecord(q, 'search', record('run2'));
  assert.equal(r.tasks.find(task => task.id === 'search').records.length, 2);
});

test('promoting an associated legacy operation preserves its independent overview association', () => {
  const p = fresh(); p.tasks[2].overview_id = 'evidence';
  const q = removeTask(p, 'question');
  validateProject(q);
  const operation = q.tasks.find(task => task.id === 'search');
  assert.equal(operation.layer, 'operation');
  assert.equal(operation.overview_id, 'evidence');
  assert.equal(operation.parent_id, undefined);
});

test('manual promotion preserves access to legacy operation history and permits explicit role changes', () => {
  const p = addOperationRecord(fresh(), 'search', record());
  const q = setParent(p, 'search');
  assert.equal(p.tasks[2].parent_id, 'question');
  assert.equal(p.tasks[2].layer, undefined);
  assert.equal(q.tasks[2].parent_id, undefined);
  assert.equal(q.tasks[2].layer, 'operation');
  const r = addOperationRecord(q, 'search', record('run2'));
  assert.equal(r.tasks[2].records.length, 2);
  r.tasks[2].layer = 'overview';
  assert.equal(taskLayer(validateProject(r).tasks[2]), 'overview');
  assert.equal(r.tasks[2].records.length, 2);
});

test('maximum-size project grouping remains complete and immutable', () => {
  const p = validateProject({schema_version: 1, project: {name: 'Wide'}, tasks: [
    ...Array.from({length: 250}, (_, i) => ({id: `s${i}`, title: `Stage ${i}`})),
    ...Array.from({length: 250}, (_, i) => ({id: `o${i}`, title: `Operation ${i}`, parent_id: `s${i}`})),
  ]});
  const before = structuredClone(p);
  for (const stage of overviewSteps(p)) {
    assert.deepEqual(operationsFor(p, stage.id).map(task => task.id), [`o${stage.id.slice(1)}`]);
  }
  assert.deepEqual(p, before);
});
