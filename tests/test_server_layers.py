import copy
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import ProjectStore, ValidationError, make_handler, parse_project, task_layer, validate_project


def project():
    return {'schema_version': 1, 'project': {'name': 'Research'}, 'tasks': [
        {'id': 'question', 'title': 'Define question'},
        {'id': 'evidence', 'title': 'Gather evidence', 'layer': 'overview'},
        {'id': 'search', 'title': 'Search literature', 'parent_id': 'question', 'operation_type': 'literature'},
        {'id': 'download', 'title': 'Download datasets', 'layer': 'operation', 'overview_id': 'evidence'},
    ]}


def record(record_id='run1'):
    return {'id': record_id, 'recorded_at': '2026-10-16T12:00:00Z', 'status': 'recorded',
            'method': 'Search title and abstract', 'parameters': 'Query: example',
            'inputs': ['query.txt'], 'outputs': ['references.json'], 'changes': 'Added references'}


class LayersValidation(unittest.TestCase):
    def test_layer_module_served_as_javascript_without_exposing_workflow(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'workflow.yaml'
            path.write_text(json.dumps(project()))
            server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(ProjectStore(path), auth_token='test-token'))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
                connection.request('GET', '/layers.mjs')
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader('Content-Type'), 'text/javascript; charset=utf-8')
                self.assertIn(b'export', response.read())
                connection.request('GET', '/api/project')
                response = connection.getresponse()
                self.assertEqual(response.status, 401)
                response.read()
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                worker.join()

    def test_legacy_layer_is_derived_without_new_fields(self):
        p = project()
        before = copy.deepcopy(p)
        q = validate_project(p)
        self.assertEqual(task_layer(q['tasks'][0]), 'overview')
        self.assertEqual(task_layer(q['tasks'][2]), 'operation')
        self.assertNotIn('layer', q['tasks'][0])
        self.assertNotIn('records', q['tasks'][2])
        self.assertEqual(p, before)

    def test_roundtrip_preserves_records_and_unknown_metadata(self):
        p = project()
        p['tasks'][2].update(method='Review', parameters='Search terms', rationale='Find prior evidence',
                             records=[record(), {**record('run2'), 'status': 'completed', 'rationale': 'Capture prior evidence', 'custom': {'checksum': 'example'}}],
                             selected_record_id='run2', custom={'owner': 'Researcher'})
        before = copy.deepcopy(p)
        q = validate_project(p)
        self.assertEqual(parse_project(json.dumps(q)), q)
        self.assertEqual(q['tasks'][2]['records'], p['tasks'][2]['records'])
        self.assertEqual(q['tasks'][2]['custom'], {'owner': 'Researcher'})
        q['tasks'][2]['rationale'] = 'Plan changed later'
        self.assertEqual(q['tasks'][2]['records'][1]['rationale'], 'Capture prior evidence')
        self.assertEqual(q['tasks'][2]['status'], 'todo')
        self.assertEqual(q['tasks'][2]['depends_on'], [])
        self.assertEqual(p, before)

    def test_layers_do_not_add_parentage_or_dependencies(self):
        p = validate_project(project())
        self.assertNotIn('parent_id', p['tasks'][3])
        self.assertEqual(p['tasks'][3]['depends_on'], [])
        p['tasks'][1]['depends_on'] = ['download']
        validate_project(p)  # An association does not imply an edge back to the overview.

    def test_invalid_associations(self):
        for target in ['missing', 'search', 'download', '', None, [], 42]:
            with self.subTest(target=target):
                p = project()
                p['tasks'][2]['overview_id'] = target
                with self.assertRaises(ValidationError):
                    validate_project(p)
        p = project()
        p['tasks'][0]['overview_id'] = 'evidence'
        with self.assertRaisesRegex(ValidationError, 'overview association'):
            validate_project(p)

    def test_invalid_layer_and_method_fields(self):
        for field, value in [('layer', 'detail'), ('layer', None), ('layer', []), ('operation_type', []),
                             ('method', {}), ('parameters', 42), ('rationale', True)]:
            with self.subTest(field=field, value=value):
                p = project()
                p['tasks'][2][field] = value
                with self.assertRaises(ValidationError):
                    validate_project(p)

    def test_invalid_records(self):
        cases = [('id', '../run'), ('id', 'x' * 65), ('id', None), ('recorded_at', ''),
                 ('recorded_at', 3), ('method', ' '), ('method', None), ('status', 'done'),
                 ('status', None), ('performed_at', []), ('parameters', {}), ('rationale', {}), ('changes', True),
                 ('code', []), ('software', {}), ('notes', None), ('inputs', 'file'), ('outputs', [2])]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                p = project()
                p['tasks'][2]['records'] = [{**record(), field: value}]
                with self.assertRaises(ValidationError):
                    validate_project(p)
        for field in ['id', 'recorded_at', 'method', 'status']:
            p = project()
            r = record()
            del r[field]
            p['tasks'][2]['records'] = [r]
            with self.assertRaises(ValidationError):
                validate_project(p)

    def test_record_ids_scoped_to_operation_and_list_bounded(self):
        p = project()
        p['tasks'][2]['records'] = [record()]
        p['tasks'][3]['records'] = [record()]
        validate_project(p)
        p['tasks'][2]['records'] = [record(), record()]
        with self.assertRaisesRegex(ValidationError, 'Duplicate record'):
            validate_project(p)
        p['tasks'][2]['records'] = [record(f'run{i}') for i in range(200)]
        validate_project(p)
        p['tasks'][2]['records'].append(record('overflow'))
        with self.assertRaisesRegex(ValidationError, '200'):
            validate_project(p)
        self.assertEqual(len(p['tasks'][2]['records']), 201)

    def test_selected_record_must_exist_on_same_operation(self):
        for selected in ['missing', None, [], 42]:
            p = project()
            p['tasks'][2]['records'] = [record()]
            p['tasks'][3]['selected_record_id'] = selected
            with self.assertRaisesRegex(ValidationError, 'selected record'):
                validate_project(p)

    def test_read_does_not_rewrite_and_save_preserves_complete_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'workflow.yaml'
            p = project()
            p['tasks'][2]['records'] = [record()]
            original = json.dumps(p)
            path.write_text(original)
            store = ProjectStore(path)
            state = store.read()
            self.assertEqual(path.read_text(), original)
            state['document']['tasks'][2]['records'].append({**record('run2'), 'status': 'completed'})
            state['document']['tasks'][2]['selected_record_id'] = 'run2'
            store.save(state['document'], state['revision'])
            reopened = store.read()['document']
            self.assertEqual(reopened['tasks'][2]['records'], state['document']['tasks'][2]['records'])
            self.assertEqual(reopened['tasks'][2]['status'], 'todo')
            backups = [path for path in (Path(temporary) / '.research-flow').rglob('*.yaml') if path.is_file()]
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), original)

    def test_invalid_record_save_leaves_file_and_backups_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'workflow.yaml'
            original = json.dumps(project())
            path.write_text(original)
            store = ProjectStore(path)
            state = store.read()
            state['document']['tasks'][2]['records'] = [{**record(), 'method': ''}]
            with self.assertRaises(ValidationError):
                store.save(state['document'], state['revision'])
            self.assertEqual(path.read_text(), original)
            self.assertEqual(list((Path(temporary) / '.research-flow').rglob('*.yaml')), [])

    @unittest.skipUnless(shutil.which('node'), 'Node is required for cross-language contract verification')
    def test_javascript_and_python_validate_same_layer_documents(self):
        valid = project()
        valid['tasks'][2]['records'] = [{**record(), 'rationale': 'Capture prior evidence', 'extra': {'review': 'pending'}}]
        valid['tasks'][2]['selected_record_id'] = 'run1'
        cases = [project(), valid]
        for field, value in [('layer', None), ('overview_id', 'download'), ('records', {}), ('selected_record_id', 'missing')]:
            case = copy.deepcopy(valid)
            case['tasks'][2][field] = value
            cases.append(case)
        for field, value in [('status', 'done'), ('recorded_at', ''), ('inputs', [False]), ('method', None), ('rationale', [])]:
            case = copy.deepcopy(valid)
            case['tasks'][2]['records'][0][field] = value
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
        for value in actual:
            if value['valid']:
                self.assertEqual(parse_project(value.pop('yaml')), value['document'])
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
