import test from 'node:test';
import assert from 'node:assert/strict';
import {validateProject, taskLayer, operationsFor, processingStepsFor, addOperationRecord,
  selectOperationRecord, removeTask, setParent, dependencyStages, toYaml} from '../web/model.mjs';

const fresh = () => validateProject({schema_version: 1, project: {name: 'Processing'}, tasks: [
  {id: 'prepare', title: 'Prepare data'},
  {id: 'normalize', title: 'Normalize', parent_id: 'prepare'},
  {id: 'filter', title: 'Filter', layer: 'operation', overview_id: 'prepare'},
  {id: 'scale', title: 'Scale to CPM', layer: 'processing', operation_id: 'normalize'},
  {id: 'log', title: 'Log transform', layer: 'processing', operation_id: 'normalize', depends_on: ['scale']},
]});
const record = id => ({id, recorded_at: '2026-10-16', status: 'recorded', method: 'Illustrative method', custom: {revision: 'example'}});

test('processing membership is independent of parenthood and creates no dependencies', () => {
  const p = fresh(), before = structuredClone(p);
  assert.deepEqual(processingStepsFor(p, 'normalize').map(t => t.id), ['scale', 'log']);
  assert.deepEqual(operationsFor(p, 'prepare').map(t => t.id), ['normalize', 'filter']);
  assert.equal(p.tasks[3].parent_id, undefined);
  assert.deepEqual(p.tasks[3].depends_on, []);
  assert.equal(dependencyStages(p).get('scale'), 0);
  assert.equal(dependencyStages(p).get('log'), 1);
  assert.equal(p.tasks[1].operation_id, undefined);
  assert.equal(taskLayer(p.tasks[1]), 'operation');
  assert.deepEqual(p, before);
});

test('processing associations override nearest operation hierarchy fallback', () => {
  const p = fresh();
  p.tasks[3].parent_id = 'filter';
  assert.deepEqual(processingStepsFor(p, 'normalize').map(t => t.id), ['scale', 'log']);
  delete p.tasks[3].operation_id;
  p.tasks.push({id: 'nested', title: 'Nested detail', layer: 'processing', parent_id: 'scale'});
  const q = validateProject(p), before = structuredClone(q);
  assert.deepEqual(processingStepsFor(q, 'filter').map(t => t.id), ['scale', 'nested']);
  assert.deepEqual(processingStepsFor(q, 'normalize').map(t => t.id), ['log']);
  assert.deepEqual(q, before);
});

test('old child tasks do not become processing steps or gain membership fields', () => {
  const p = fresh();
  p.tasks.push({id: 'old-child', title: 'Old child', parent_id: 'normalize'});
  const q = validateProject(p), legacy = q.tasks.at(-1);
  assert.equal(taskLayer(legacy), 'operation');
  assert.equal(Object.hasOwn(legacy, 'layer'), false);
  assert.equal(Object.hasOwn(legacy, 'operation_id'), false);
  assert.equal(processingStepsFor(q, 'normalize').some(t => t.id === legacy.id), false);
});

test('processing nodes keep individual records without changing operation progress', () => {
  const p = fresh(), before = structuredClone(p);
  const q = selectOperationRecord(addOperationRecord(p, 'scale', record('first')), 'scale', 'first');
  const r = addOperationRecord(q, 'scale', {...record('second'), status: 'completed'});
  assert.deepEqual(p, before);
  assert.equal(r.tasks[3].selected_record_id, 'first');
  assert.equal(r.tasks[3].records.length, 2);
  assert.deepEqual(r.tasks[3].records[0].custom, {revision: 'example'});
  assert.equal(r.tasks[3].status, 'todo');
  assert.equal(r.tasks[1].status, 'todo');
  assert.equal(r.tasks[1].records, undefined);
  assert.deepEqual(validateProject(r), r);
  assert.match(toYaml(r), /operation_id: "normalize"/);
});

test('invalid operation links and layer changes reject until explicitly unlinked', () => {
  for (const target of ['missing', 'prepare', 'scale', 'log', '', null, 3, []]) {
    const p = fresh(); p.tasks[3].operation_id = target;
    assert.throws(() => validateProject(p), String(target));
  }
  for (const layer of ['overview', 'operation']) {
    const p = fresh(); p.tasks[3].layer = layer;
    assert.throws(() => validateProject(p), /operation association/);
  }
  const p = fresh(); p.tasks[1].layer = 'overview';
  assert.throws(() => validateProject(p), /operation association/);
  for (const t of p.tasks) if (t.operation_id === 'normalize') delete t.operation_id;
  validateProject(p);
  const q = fresh(); q.tasks[3].overview_id = 'prepare';
  assert.throws(() => validateProject(q), /overview association/);
});

test('deleting an operation keeps processing nodes, histories, and their own dependencies', () => {
  const p = addOperationRecord(fresh(), 'scale', record('first')), before = structuredClone(p);
  const q = removeTask(p, 'normalize');
  validateProject(q);
  const scale = q.tasks.find(t => t.id === 'scale'), log = q.tasks.find(t => t.id === 'log');
  assert.equal(scale.operation_id, undefined);
  assert.equal(log.operation_id, undefined);
  assert.equal(taskLayer(scale), 'processing');
  assert.deepEqual(scale.records, [record('first')]);
  assert.deepEqual(log.depends_on, ['scale']);
  assert.deepEqual(p, before);
});

test('hierarchy promotion preserves a referenced legacy operation and its processing links', () => {
  const p = fresh();
  for (const q of [removeTask(p, 'prepare'), setParent(p, 'normalize')]) {
    validateProject(q);
    assert.equal(q.tasks.find(t => t.id === 'normalize').layer, 'operation');
    assert.deepEqual(processingStepsFor(q, 'normalize').map(t => t.id), ['scale', 'log']);
  }
  assert.equal(p.tasks[1].layer, undefined);
});

test('deleting a processing node removes only its dependencies and preserves siblings', () => {
  const p = addOperationRecord(fresh(), 'log', record('log-record'));
  const q = removeTask(p, 'scale');
  validateProject(q);
  const log = q.tasks.find(t => t.id === 'log');
  assert.deepEqual(log.depends_on, []);
  assert.equal(log.operation_id, 'normalize');
  assert.deepEqual(log.records, [record('log-record')]);
});
