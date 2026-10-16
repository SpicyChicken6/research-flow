import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import ProjectStore, ValidationError, parse_project, validate_project


def project():
    return {'schema_version': 1, 'project': {'name': 'Research'},
            'tasks': [{'id': 'analysis', 'title': 'Analyze data'}], 'custom': {'owner': 'Researcher'}}


def idea(idea_id='question1'):
    return {'id': idea_id, 'title': 'Does the normalization choice matter?', 'kind': 'question',
            'status': 'open', 'created_at': '2026-10-16T12:00:00Z', 'notes': 'Compare two alternatives',
            'related_task_id': 'analysis', 'custom': {'evidence': [1, 2]}}


class IdeasValidation(unittest.TestCase):
    def test_old_documents_have_no_new_field_or_metadata_changes(self):
        p = project()
        before = copy.deepcopy(p)
        q = validate_project(p)
        self.assertNotIn('ideas', q)
        self.assertEqual(q['custom'], p['custom'])
        self.assertEqual(p, before)

    def test_roundtrip_preserves_all_content_without_changing_task_progress(self):
        p = project()
        p['ideas'] = [{**idea(), 'status': 'resolved', 'resolution': 'Use the prespecified method',
                       'revisit_when': 'When validation results arrive', 'updated_at': '2026-10-17', 'resolved_at': '2026-10-17'}]
        before = copy.deepcopy(p)
        q = validate_project(p)
        self.assertEqual(parse_project(json.dumps(q)), q)
        self.assertEqual(q['ideas'], p['ideas'])
        self.assertEqual(q['tasks'][0]['status'], 'todo')
        self.assertEqual(p, before)

    def test_bad_fields_missing_fields_and_task_references(self):
        changes = [('id', '../bad'), ('id', 'x' * 65), ('id', 'x\n'), ('title', ' '), ('created_at', ''),
                   ('kind', 'task'), ('kind', []), ('status', 'done'), ('status', None), ('notes', {}),
                   ('revisit_when', False), ('resolution', []), ('updated_at', 4), ('resolved_at', None),
                   ('related_task_id', 'missing'), ('related_task_id', None)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                p = project()
                p['ideas'] = [{**idea(), key: value}]
                with self.assertRaises(ValidationError):
                    validate_project(p)
        for key in ['id', 'title', 'kind', 'status', 'created_at']:
            p = project()
            item = idea()
            del item[key]
            p['ideas'] = [item]
            with self.assertRaises(ValidationError):
                validate_project(p)

    def test_collection_type_duplicate_and_size(self):
        for value in [None, {}, 'text', [idea(), idea()]]:
            p = project()
            p['ideas'] = value
            with self.assertRaises(ValidationError):
                validate_project(p)
        p = project()
        p['ideas'] = [idea(f'idea{i}') for i in range(500)]
        validate_project(p)
        p['ideas'].append(idea('overflow'))
        with self.assertRaisesRegex(ValidationError, '500'):
            validate_project(p)
        self.assertEqual(len(p['ideas']), 501)

    def test_read_does_not_rewrite_and_save_retains_ideas_and_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'workflow.yaml'
            p = project()
            p['ideas'] = [idea()]
            original = json.dumps(p)
            path.write_text(original)
            store = ProjectStore(path)
            state = store.read()
            self.assertEqual(path.read_text(), original)
            state['document']['ideas'][0].update(status='deferred', revisit_when='After validation')
            store.save(state['document'], state['revision'])
            self.assertEqual(store.read()['document']['ideas'], state['document']['ideas'])
            backups = list((Path(directory) / '.research-flow/backups/workflow.yaml').glob('*.yaml'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), original)

    @unittest.skipUnless(shutil.which('node'), 'Node required for cross-language contract verification')
    def test_javascript_python_validation_and_yaml_roundtrip_match(self):
        valid = project()
        valid['ideas'] = [idea()]
        cases = [project(), valid, {**project(), 'ideas': []}]
        for key, value in [('id', 'bad/id'), ('id', 'x\n'), ('kind', []), ('status', 'done'),
                           ('related_task_id', 'missing'), ('related_task_id', None), ('resolved_at', [])]:
            case = copy.deepcopy(valid)
            case['ideas'][0][key] = value
            cases.append(case)
        expected = []
        for case in cases:
            try:
                expected.append({'valid': True, 'document': validate_project(case)})
            except ValidationError:
                expected.append({'valid': False})
        script = """
import {validateProject, toYaml} from './web/model.mjs';
let input = ''; for await (const chunk of process.stdin) input += chunk;
console.log(JSON.stringify(JSON.parse(input).map(value => {
  try { const document = validateProject(value); return {valid: true, document, yaml: toYaml(document)}; }
  catch { return {valid: false}; }
})));
"""
        result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT,
                                input=json.dumps(cases), capture_output=True, text=True, check=True)
        actual = json.loads(result.stdout)
        for entry in actual:
            if entry['valid']:
                self.assertEqual(parse_project(entry.pop('yaml')), entry['document'])
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
