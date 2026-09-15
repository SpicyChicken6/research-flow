import test from 'node:test';
import assert from 'node:assert/strict';
import { validateProject, addDependency, removeTask, autoLayout, toYaml } from '../web/model.mjs';
const fresh = () => validateProject({ schema_version: 1, project: { name: 'Demo' }, tasks: [
  { id: 'a', title: 'A', status: 'done' }, { id: 'b', title: 'B', depends_on: ['a'] }, { id: 'c', title: 'C' }
] });
test('normalizes optional fields without mutating input', () => { const x = { schema_version: 1, project: {name: 'X'}, tasks: [] }; const y = validateProject(x); assert.equal(x.layout, undefined); assert.deepEqual(y.layout.positions, {}); });
test('round-trips unknown extension metadata', () => { const x = fresh(); x.tasks[0].owner = 'Analyst'; x.custom = { extra: ['x'] }; assert.deepEqual(validateProject(x).custom, x.custom); assert.equal(validateProject(x).tasks[0].owner, 'Analyst'); });
test('detects a direct cycle', () => assert.throws(() => addDependency(fresh(), 'b', 'a'), /cycle/));
test('detects an indirect cycle', () => assert.throws(() => addDependency(addDependency(fresh(), 'b', 'c'), 'c', 'a'), /cycle/));
test('self dependency rejected', () => assert.throws(() => addDependency(fresh(), 'a', 'a'), /itself/));
test('unknown dependency rejected', () => { const x = fresh(); x.tasks[0].depends_on.push('unknown'); assert.throws(() => validateProject(x), /Unknown/); });
test('duplicate ids rejected', () => { const x = fresh(); x.tasks[2].id = 'a'; assert.throws(() => validateProject(x), /Duplicate/); });
test('duplicate dependencies rejected', () => { const x = fresh(); x.tasks[1].depends_on.push('a'); assert.throws(() => validateProject(x), /Duplicate/); });
test('adding the same edge is idempotent', () => assert.deepEqual(addDependency(fresh(), 'a', 'b'), fresh()));
test('remove task removes incident edges but retains descendants', () => { const x = removeTask(fresh(), 'a'); assert.equal(x.tasks.length, 2); assert.deepEqual(x.tasks[0].depends_on, []); });
test('auto layout puts dependencies before descendants', () => { const x = autoLayout(fresh()); assert.ok(x.layout.positions.a.x < x.layout.positions.b.x); assert.equal(x.layout.positions.a.x, x.layout.positions.c.x); });
test('empty project layout remains valid', () => { const x = fresh(); x.tasks = []; assert.deepEqual(autoLayout(x).tasks, []); });
test('invalid status and empty string rejected', () => { for (const v of ['finished', '']) { const x = fresh(); x.tasks[0].status = v; assert.throws(() => validateProject(x), /status/); } });
test('empty required title is rejected', () => { const x = fresh(); x.tasks[0].title = ''; assert.throws(() => validateProject(x), /title/); });
test('YAML emitter safely quotes special strings', () => { assert.match(toYaml({x: 'a: b\n#comment'}), /"a: b\\n#comment"/); assert.match(toYaml({ empty: [] }), /empty: \[\]/); });
test('nonfinite and dangerous extension keys rejected', () => { const x = fresh(); x.extra = Infinity; assert.throws(() => validateProject(x), /finite/); const y = JSON.parse('{"__proto__": {}}'); assert.throws(() => validateProject(y), /Unsupported/); });
test('invalid layout rejected', () => { const x = fresh(); x.layout.positions.a = {x: 0, y: 'bad'}; assert.throws(() => validateProject(x), /layout/); });
test('task IDs must be strings without implicit coercion', () => {
  for (const id of [123, true, ['a']]) {
    const x = fresh(); x.tasks[2].id = id;
    assert.throws(() => validateProject(x), /Task IDs/);
  }
});
test('task statuses must be strings without implicit coercion', () => {
  for (const status of [['todo'], ['done'], null, 123]) {
    const x = fresh(); x.tasks[0].status = status;
    assert.throws(() => validateProject(x), /Invalid status/);
  }
});
