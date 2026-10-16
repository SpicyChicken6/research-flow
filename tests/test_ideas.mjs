import test from 'node:test';
import assert from 'node:assert/strict';
import {validateProject, addIdea, updateIdea, removeIdea, removeTask, toYaml} from '../web/model.mjs';

const fresh = () => validateProject({schema_version: 1, project: {name: 'Research'},
  tasks: [{id: 'analysis', title: 'Analyze data'}], custom: {owner: 'Researcher'}});
const idea = (id = 'question1') => ({id, title: 'Does the normalization choice matter?',
  kind: 'question', status: 'open', created_at: '2026-10-16T12:00:00Z',
  notes: 'Compare two alternatives', related_task_id: 'analysis', custom: {evidence: [1, 2]}});

test('legacy documents gain no ideas key and unknown metadata survives', () => {
  const p = fresh(), before = structuredClone(p);
  assert.equal(Object.hasOwn(validateProject(p), 'ideas'), false);
  assert.deepEqual(p, before);
  assert.deepEqual(validateProject(p).custom, {owner: 'Researcher'});
});

test('adding ideas preserves callers, unknown fields, task progress, and serialization', () => {
  const p = fresh(), item = idea(), before = structuredClone(p);
  const q = addIdea(p, item);
  assert.deepEqual(p, before);
  assert.deepEqual(item, idea());
  assert.deepEqual(q.ideas, [idea()]);
  assert.deepEqual(q.tasks, p.tasks);
  assert.deepEqual(validateProject(q), q);
  assert.match(toYaml(q), /revisit_when|Does the normalization choice matter/);
});

test('editing, resolving, and reopening retain identity, creation time, and previous resolution', () => {
  const p = addIdea(fresh(), idea()), before = structuredClone(p);
  const q = updateIdea(p, 'question1', {status: 'resolved', resolution: 'Use the prespecified method',
    updated_at: '2026-10-17', resolved_at: '2026-10-17'});
  const reopened = updateIdea(q, 'question1', {status: 'open', updated_at: '2026-10-18'});
  assert.deepEqual(p, before);
  assert.equal(reopened.ideas[0].id, 'question1');
  assert.equal(reopened.ideas[0].created_at, idea().created_at);
  assert.equal(reopened.ideas[0].resolved_at, '2026-10-17');
  assert.equal(reopened.ideas[0].resolution, 'Use the prespecified method');
  assert.deepEqual(reopened.ideas[0].custom, idea().custom);
  assert.equal(reopened.tasks[0].status, 'todo');
});

test('identity and creation timestamp changes reject atomically; matching values are harmless', () => {
  const p = addIdea(fresh(), idea()), before = structuredClone(p);
  for (const patch of [{id: 'different'}, {created_at: 'tomorrow'}, {id: null}, {created_at: null}]) {
    assert.throws(() => updateIdea(p, 'question1', patch), /cannot be changed/);
  }
  assert.deepEqual(updateIdea(p, 'question1', {id: 'question1', created_at: idea().created_at}), p);
  assert.deepEqual(p, before);
});

test('unlink patch removes optional reference without storing null or dropping content', () => {
  const p = addIdea(fresh(), idea());
  const q = updateIdea(p, 'question1', {related_task_id: null});
  assert.equal(Object.hasOwn(q.ideas[0], 'related_task_id'), false);
  assert.equal(p.ideas[0].related_task_id, 'analysis');
  assert.equal(q.ideas[0].notes, idea().notes);
  assert.deepEqual(q.ideas[0].custom, idea().custom);
});

test('removing tasks unlinks ideas while preserving notes, resolution, and unrelated ideas', () => {
  let p = addIdea(fresh(), {...idea(), resolution: 'Keep this conclusion'});
  p = addIdea(p, {...idea('standalone'), related_task_id: 'analysis'});
  p = updateIdea(p, 'standalone', {related_task_id: null});
  const before = structuredClone(p), q = removeTask(p, 'analysis');
  validateProject(q);
  assert.deepEqual(p, before);
  assert.equal(q.ideas.length, 2);
  assert.equal(q.ideas[0].related_task_id, undefined);
  assert.equal(q.ideas[0].resolution, 'Keep this conclusion');
  assert.equal(q.ideas[0].notes, idea().notes);
  assert.deepEqual(q.ideas[1], p.ideas[1]);
});

test('removing an idea changes only that collection and missing IDs fail', () => {
  const p = addIdea(addIdea(fresh(), idea()), idea('another')), before = structuredClone(p);
  const q = removeIdea(p, 'question1');
  assert.deepEqual(q.ideas, [idea('another')]);
  assert.deepEqual(q.tasks, p.tasks);
  assert.deepEqual(p, before);
  assert.throws(() => updateIdea(p, 'missing', {title: 'New title'}), /not found/);
  assert.throws(() => removeIdea(p, 'missing'), /not found/);
  assert.deepEqual(removeIdea(q, 'another').ideas, []);
});

test('invalid idea data and malformed patches are rejected without mutation', () => {
  const changes = [{id: '../bad'}, {id: 'x'.repeat(65)}, {id: 'x\n'}, {title: ' '}, {created_at: ''},
    {kind: 'task'}, {kind: []}, {status: 'done'}, {status: null}, {notes: {}}, {revisit_when: false},
    {resolution: []}, {updated_at: 4}, {resolved_at: null}, {related_task_id: 'missing'}, {related_task_id: null}];
  const p = fresh();
  for (const change of changes) assert.throws(() => addIdea(p, {...idea(), ...change}), JSON.stringify(change));
  for (const key of ['id', 'title', 'kind', 'status', 'created_at']) {
    const item = idea(); delete item[key];
    assert.throws(() => addIdea(p, item), key);
  }
  for (const value of [null, {}, 'text']) assert.throws(() => validateProject({...p, ideas: value}));
  const q = addIdea(p, idea());
  for (const patch of [null, [], 'text']) assert.throws(() => updateIdea(q, 'question1', patch), /object/);
  assert.throws(() => addIdea(q, idea()), /Duplicate idea/);
  assert.equal(Object.hasOwn(p, 'ideas'), false);
});

test('500-idea cap preserves all existing entries on overflow', () => {
  const p = fresh(); p.ideas = Array.from({length: 500}, (_, i) => idea(`idea${i}`));
  validateProject(p);
  assert.throws(() => addIdea(p, idea('overflow')), /500/);
  assert.equal(p.ideas.length, 500);
});
