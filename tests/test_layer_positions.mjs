import test from 'node:test';
import assert from 'node:assert/strict';
import {validateProject, removeTask, toYaml, autoLayout} from '../web/model.mjs';

const document = () => ({schema_version: 1, project: {name: 'Separate canvases'}, tasks: [
  {id: 'a', title: 'Prepare'},
  {id: 'b', title: 'Normalize', layer: 'operation', overview_id: 'a'},
  {id: 'c', title: 'Scale', layer: 'processing', operation_id: 'b', depends_on: ['a'],
    records: [{id: 'record', recorded_at: '2026-10-16', status: 'recorded', method: 'Preserve history'}]},
], layout: {positions: {a: {x: 0, y: 0}, b: {x: 20, y: 30}, c: {x: 40, y: 50}}, custom: {note: 'Keep this'}}});
const savedPositions = () => ({a: {x: -10000000, y: 10000000}, b: {x: -42.5, y: -25.25, custom: {locked: true}}, c: {x: 0, y: 0}});

test('layer positions accept negative/fractional bounds and preserve graph layout and research data', () => {
  const p = document(); p.layout.layer_positions = savedPositions();
  const before = structuredClone(p), q = validateProject(p);
  assert.deepEqual(p, before);
  assert.deepEqual(q.layout, p.layout);
  assert.deepEqual(q.tasks, validateProject(document()).tasks);
  assert.deepEqual(validateProject(q), q);
  assert.match(toYaml(q), /layer_positions:/);
  assert.match(toYaml(q), /x: -42.5/);
  assert.deepEqual(autoLayout(q).layout.layer_positions, savedPositions());
});

test('old files and deletions do not insert a layer positions field', () => {
  const p = validateProject(document());
  assert.equal(Object.hasOwn(p.layout, 'layer_positions'), false);
  assert.equal(Object.hasOwn(removeTask(p, 'b').layout, 'layer_positions'), false);
  const q = document(); q.layout.layer_positions = {};
  assert.deepEqual(validateProject(q).layout.layer_positions, {});
});

test('layer position validation rejects malformed maps, missing tasks, and invalid coordinates', () => {
  for (const positions of [null, [], 'text', 42, {missing: {x: 0, y: 0}},
    {a: null}, {a: []}, {a: {}}, {a: {x: 0}}, {a: {x: '0', y: 0}}, {a: {x: true, y: 0}},
    {a: {x: 10000000.1, y: 0}}, {a: {x: 0, y: -10000000.1}}, {a: {x: Infinity, y: 0}}, {a: {x: 0, y: NaN}}]) {
    const p = document(); p.layout.layer_positions = positions;
    assert.throws(() => validateProject(p), String(positions));
  }
});

test('deletion prunes only the removed node layer position and preserves remaining histories', () => {
  const raw = document(); raw.layout.layer_positions = savedPositions();
  const p = validateProject(raw), before = structuredClone(p), q = removeTask(p, 'b');
  validateProject(q);
  assert.deepEqual(q.layout.layer_positions, {a: savedPositions().a, c: savedPositions().c});
  assert.deepEqual(q.layout.positions, {a: p.layout.positions.a, c: p.layout.positions.c});
  assert.deepEqual(q.layout.custom, p.layout.custom);
  assert.deepEqual(q.tasks.find(task => task.id === 'c').records, p.tasks[2].records);
  assert.deepEqual(q.tasks.find(task => task.id === 'c').depends_on, ['a']);
  assert.deepEqual(p, before);
});
