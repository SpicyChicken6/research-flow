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
    return {'schema_version': 1, 'project': {'name': 'Processing'}, 'tasks': [
        {'id': 'prepare', 'title': 'Prepare data'},
        {'id': 'normalize', 'title': 'Normalize', 'parent_id': 'prepare'},
        {'id': 'scale', 'title': 'Scale to CPM', 'layer': 'processing', 'operation_id': 'normalize'},
        {'id': 'log', 'title': 'Log transform', 'layer': 'processing', 'operation_id': 'normalize', 'depends_on': ['scale']},
    ]}


class ProcessingValidation(unittest.TestCase):
    def test_records_and_membership_roundtrip_without_adding_parentage(self):
        p = project()
        p['tasks'][2].update(method='Scale', parameters='scale: 1000000', custom={'owner': 'Researcher'},
            records=[{'id': 'first', 'recorded_at': '2026-10-16', 'status': 'recorded', 'method': 'Illustrative method', 'custom': {'revision': 'example'}}],
            selected_record_id='first')
        before = copy.deepcopy(p)
        q = validate_project(p)
        self.assertEqual(parse_project(json.dumps(q)), q)
        self.assertEqual(q['tasks'][2]['records'], p['tasks'][2]['records'])
        self.assertEqual(q['tasks'][2]['custom'], p['tasks'][2]['custom'])
        self.assertNotIn('parent_id', q['tasks'][2])
        self.assertEqual(q['tasks'][2]['depends_on'], [])
        self.assertEqual(q['tasks'][1]['status'], 'todo')
        self.assertEqual(p, before)

    def test_invalid_operation_associations(self):
        for target in ['missing', 'prepare', 'scale', 'log', '', None, 3, []]:
            with self.subTest(target=target):
                p = project()
                p['tasks'][2]['operation_id'] = target
                with self.assertRaises(ValidationError):
                    validate_project(p)
        for layer in ['overview', 'operation']:
            p = project()
            p['tasks'][2]['layer'] = layer
            with self.assertRaisesRegex(ValidationError, 'operation association'):
                validate_project(p)

    def test_reclassifying_referenced_operation_requires_unlinking(self):
        p = project()
        p['tasks'][1]['layer'] = 'overview'
        with self.assertRaisesRegex(ValidationError, 'operation association'):
            validate_project(p)
        del p['tasks'][2]['operation_id']
        del p['tasks'][3]['operation_id']
        validate_project(p)

    def test_legacy_hierarchy_does_not_gain_processing_layer_or_membership(self):
        p = project()
        p['tasks'] = p['tasks'][:2]
        q = validate_project(p)
        self.assertNotIn('layer', q['tasks'][1])
        self.assertNotIn('operation_id', q['tasks'][1])

    def test_example_processing_nodes_are_planned_and_preserve_old_records(self):
        p = parse_project((ROOT / 'examples/three-layers.yaml').read_text())
        tasks = {t['id']: t for t in p['tasks']}
        for task_id, operation in [('filter-rule', 'filtering'), ('scale-cpm', 'normalization'), ('log-transform', 'normalization')]:
            task = tasks[task_id]
            self.assertEqual(task['layer'], 'processing')
            self.assertEqual(task['operation_id'], operation)
            self.assertEqual(task['status'], 'todo')
            self.assertNotIn('records', task)
            self.assertTrue(task['inputs'])
            self.assertTrue(task['outputs'])
            self.assertTrue(task['method'])
            self.assertTrue(task['parameters'])
        self.assertEqual(tasks['log-transform']['depends_on'], ['scale-cpm'])
        self.assertEqual(tasks['scale-cpm']['depends_on'], [])
        self.assertEqual([r['id'] for r in tasks['normalization']['records']], ['normalization-v1', 'normalization-v2'])

    def test_disk_read_and_save_preserve_processing_details(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'workflow.yaml'
            original = json.dumps(project())
            path.write_text(original)
            store = ProjectStore(path)
            state = store.read()
            self.assertEqual(path.read_text(), original)
            state['document']['tasks'][2]['parameters'] = 'scale: 1000000'
            store.save(state['document'], state['revision'])
            self.assertEqual(store.read()['document']['tasks'], state['document']['tasks'])

    @unittest.skipUnless(shutil.which('node'), 'Node required for cross-language contract verification')
    def test_javascript_python_contract_and_yaml_roundtrip_match(self):
        cases = [project()]
        for field, value in [('operation_id', 'missing'), ('operation_id', 'prepare'), ('operation_id', []),
                             ('operation_id', None), ('layer', 'operation'), ('overview_id', 'prepare')]:
            case = copy.deepcopy(project())
            case['tasks'][2][field] = value
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
