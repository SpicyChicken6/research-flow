import test from 'node:test';
import assert from 'node:assert/strict';
import {validateProject, dependencyStages, stageLayout, dependencyPathIds, dependencyPathEdges, taskSize} from '../web/model.mjs';

const project = tasks => validateProject({schema_version: 1, project: {name: 'Stages'}, tasks});
const task = (id, depends_on = [], extra = {}) => ({id, title: id, depends_on, ...extra});
const freeze = value => {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
};

test('parallel evidence steps precede synthesis and follow-up', () => {
  const p = project([task('design', ['analysis', 'literature']), task('analysis'), task('literature'), task('review', ['design'])]);
  const ranks = dependencyStages(p), layout = stageLayout(p);
  assert.deepEqual([...ranks], [['design', 1], ['analysis', 0], ['literature', 0], ['review', 2]]);
  assert.deepEqual(layout.stages.map(stage => stage.taskIds), [['analysis', 'literature'], ['design'], ['review']]);
  assert.equal(layout.positions.analysis.x, layout.positions.literature.x);
  assert.ok(layout.positions.analysis.y + taskSize(p.tasks[1]).height < layout.positions.literature.y);
  assert.ok(layout.positions.design.y > layout.positions.analysis.y);
  assert.ok(layout.positions.design.y < layout.positions.literature.y);
});

test('longest prerequisite path controls stage regardless of array order or status', () => {
  const p = project([task('final', ['early', 'late']), task('late', ['middle']), task('middle', ['early']), task('early', [], {status: 'done'}), task('independent', [], {status: 'blocked'})]);
  assert.equal(dependencyStages(p).get('final'), 3);
  const before = dependencyStages(p);
  p.tasks.forEach(t => {t.status = 'done';});
  assert.deepEqual(dependencyStages(p), before);
});

test('hierarchy adds no ordering constraints and child dependencies still run left to right', () => {
  const p = project([task('parent', ['child']), task('other'), task('child', ['other'], {parent_id: 'parent'}), task('sibling', [], {parent_id: 'parent'})]);
  assert.deepEqual([...dependencyStages(p)], [['parent', 2], ['other', 0], ['child', 1], ['sibling', 0]]);
  const {positions} = stageLayout(p);
  for (const t of p.tasks) for (const source of t.depends_on) {
    assert.ok(positions[source].x + taskSize(p.tasks.find(t => t.id === source)).width < positions[t.id].x);
  }
});

test('same-stage family order follows the outline without changing the task array', () => {
  const p = project([task('parent'), task('other'), task('child', [], {parent_id: 'parent'}), task('nested', [], {parent_id: 'child'})]);
  const before = JSON.stringify(p);
  assert.deepEqual(stageLayout(p).stages[0].taskIds, ['parent', 'child', 'nested', 'other']);
  assert.equal(JSON.stringify(p), before);
});

test('stage geometry encloses compact child cards and has no overlapping frames or cards', () => {
  const p = project([task('parent'), task('child', ['parent'], {parent_id: 'parent'}), task('peer'), task('child_peer', ['parent'], {parent_id: 'parent'}), task('final', ['child', 'child_peer'])]);
  const {positions, stages} = stageLayout(p);
  for (const stage of stages) {
    for (const id of stage.taskIds) {
      const position = positions[id], size = taskSize(p.tasks.find(t => t.id === id));
      assert.ok(position.x >= stage.x + 24);
      assert.ok(position.x + size.width <= stage.x + stage.width - 24);
      assert.ok(position.y >= stage.y + 72);
      assert.ok(position.y + size.height <= stage.y + stage.height - 24);
    }
  }
  for (let i = 1; i < stages.length; i++) assert.ok(stages[i - 1].x + stages[i - 1].width < stages[i].x);
  for (let i = 0; i < p.tasks.length; i++) for (let j = 0; j < i; j++) {
    const a = positions[p.tasks[i].id], b = positions[p.tasks[j].id], as = taskSize(p.tasks[i]), bs = taskSize(p.tasks[j]);
    assert.ok(a.x + as.width <= b.x || b.x + bs.width <= a.x || a.y + as.height <= b.y || b.y + bs.height <= a.y);
  }
});

test('stage helpers accept frozen projects and preserve saved positions and extension metadata', () => {
  const p = project([task('a', [], {custom: {labels: ['retain']}}), task('b', ['a'])]);
  p.layout.positions = {a: {x: -37, y: 58}, b: {x: 300, y: 19}};
  p.layout.custom = {theme: 'keep'};
  const before = JSON.stringify(p);
  freeze(p);
  const first = stageLayout(p);
  assert.deepEqual(stageLayout(p), first);
  assert.deepEqual([...dependencyPathIds(p, 'a')], ['a', 'b']);
  first.positions.a.x = 999;
  first.stages[0].taskIds.push('not_a_task');
  assert.equal(JSON.stringify(p), before);
  assert.notEqual(stageLayout(p).positions.a.x, 999);
});

test('selection highlights transitive paths without co-prerequisites or sibling dependents', () => {
  const p = project([task('upstream'), task('selected', ['upstream']), task('sibling', ['upstream']), task('co_input'), task('merge', ['selected', 'co_input']), task('downstream', ['merge']), task('unrelated')]);
  assert.deepEqual([...dependencyPathIds(p, 'selected')].sort(), ['downstream', 'merge', 'selected', 'upstream']);
  assert.deepEqual([...dependencyPathIds(p, 'merge')].sort(), ['co_input', 'downstream', 'merge', 'selected', 'upstream']);
  assert.deepEqual([...dependencyPathIds(p, 'unrelated')], ['unrelated']);
  assert.equal(dependencyPathIds(p, 'missing').size, 0);
});

test('path edges omit shortcuts bypassing the selection and include converging path edges', () => {
  const p = project([task('root'), task('left', ['root']), task('right', ['root']), task('selected', ['left', 'right']), task('join', ['selected', 'root']), task('last', ['join'])]);
  assert.deepEqual([...dependencyPathEdges(p, 'selected')].sort(), ['join|last', 'left|selected', 'right|selected', 'root|left', 'root|right', 'selected|join']);
  assert.equal(dependencyPathEdges(p, 'missing').size, 0);
});

test('empty projects have no stages or paths', () => {
  const p = project([]);
  assert.deepEqual(stageLayout(p), {positions: {}, stages: []});
  assert.equal(dependencyStages(p).size, 0);
  assert.equal(dependencyPathIds(p, 'missing').size, 0);
});

test('500-step chains and wide stages remain complete', () => {
  const chain = project(Array.from({length: 500}, (_, i) => task(`t${i}`, i ? [`t${i - 1}`] : [])));
  const layout = stageLayout(chain);
  assert.equal(layout.stages.length, 500);
  assert.equal(Object.keys(layout.positions).length, 500);
  assert.equal(dependencyStages(chain).get('t499'), 499);
  assert.equal(dependencyPathIds(chain, 't250').size, 500);
  const wide = stageLayout(project(chain.tasks.map(t => ({...t, depends_on: []}))));
  assert.equal(wide.stages.length, 1);
  assert.equal(wide.stages[0].taskIds.length, 500);
  assert.ok(wide.positions.t499.y > wide.positions.t0.y);
});

test('invalid dependency graphs fail rather than returning misleading stages', () => {
  assert.throws(() => dependencyStages({tasks: [task('a', ['b']), task('b', ['a'])]}), /cycle/);
  assert.throws(() => dependencyStages({tasks: [task('a', ['missing'])]}), /Unknown dependency/);
});
