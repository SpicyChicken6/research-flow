import copy
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import ROOT, ProjectStore, ValidationError, ConflictError, parse_project, validate_project, make_handler

class ModelTests(unittest.TestCase):
    def setUp(self): self.example = parse_project((ROOT / 'examples/research-project.yaml').read_text())
    def test_defaults(self):
        x = validate_project({'schema_version': 1, 'project': {'name': 'X'}, 'tasks': [{'id': 'x', 'title': 'X'}]})
        self.assertEqual(x['tasks'][0]['depends_on'], [])
    def test_duplicate_yaml_key(self):
        with self.assertRaises(ValidationError): parse_project('schema_version: 1\nschema_version: 1\n')
    def test_cycle(self):
        self.example['tasks'][0]['depends_on'] = ['synthesis']
        with self.assertRaisesRegex(ValidationError, 'cycle'): validate_project(self.example)
    def test_missing_dependency(self):
        self.example['tasks'][0]['depends_on'] = ['missing']
        with self.assertRaisesRegex(ValidationError, 'Unknown'): validate_project(self.example)
    def test_duplicate_ids(self):
        self.example['tasks'][1]['id'] = self.example['tasks'][0]['id']
        with self.assertRaisesRegex(ValidationError, 'Duplicate'): validate_project(self.example)
    def test_unknown_metadata_preserved(self):
        self.example['tasks'][0]['evidence'] = {'papers': [123], 'owner': 'Analyst'}
        self.assertEqual(validate_project(self.example), self.example)
    def test_unsafe_tags_rejected(self):
        with self.assertRaises(ValidationError): parse_project('!!python/object/apply:os.system [echo nope]')
    def test_alias_rejected(self):
        with self.assertRaises(ValidationError): parse_project('x: &x [*x]')
    def test_large_file(self):
        with self.assertRaises(ValidationError): parse_project('a' * 2_000_001)
    def test_nonfinite_number(self):
        self.example['extension'] = float('inf')
        with self.assertRaises(ValidationError): validate_project(self.example)
    def test_extremely_large_integer_is_validation_error(self):
        for value in (10**400, -(10**400)):
            with self.subTest(value=value):
                self.example['extension'] = value
                with self.assertRaisesRegex(ValidationError, 'safe numeric range'):
                    validate_project(self.example)
                with self.assertRaisesRegex(ValidationError, 'safe numeric range'):
                    parse_project('schema_version: 1\nproject:\n  name: Example\ntasks: []\nextra: ' + str(value))
    def test_false_version(self):
        self.example['schema_version'] = True
        with self.assertRaises(ValidationError): validate_project(self.example)
    def test_empty_title(self):
        self.example['tasks'][0]['title'] = ' '
        with self.assertRaises(ValidationError): validate_project(self.example)
    def test_invalid_status(self):
        self.example['tasks'][0]['status'] = 'finished'
        with self.assertRaises(ValidationError): validate_project(self.example)
    def test_bad_layout(self):
        self.example['layout']['positions']['question'] = {'x': 'wrong', 'y': 0}
        with self.assertRaises(ValidationError): validate_project(self.example)
    def test_bad_project_description(self):
        self.example['project']['description'] = 123
        with self.assertRaises(ValidationError): validate_project(self.example)

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.path = Path(self.temp.name) / 'project.yaml'
        self.path.write_text((ROOT / 'examples/research-project.yaml').read_text()); self.store = ProjectStore(self.path)
    def tearDown(self): self.temp.cleanup()
    def test_save_is_persistent_and_backed_up(self):
        original = self.path.read_bytes(); snapshot = self.store.read()
        snapshot['document']['project']['name'] = 'Saved title'
        updated = self.store.save(snapshot['document'], snapshot['revision'])
        self.assertEqual(self.store.read()['document']['project']['name'], 'Saved title')
        self.assertNotEqual(updated['revision'], snapshot['revision'])
        backups = list(self.path.parent.glob('.research-flow/backups/project.yaml/*.yaml'))
        self.assertEqual(backups[0].read_bytes(), original)
    def test_external_edit_conflict_preserves_external_content(self):
        snap = self.store.read(); external = self.path.read_text().replace('From question to discovery', 'External edit')
        self.path.write_text(external)
        with self.assertRaises(ConflictError): self.store.save(snap['document'], snap['revision'])
        self.assertEqual(self.path.read_text(), external)
    def test_stale_second_client_rejected(self):
        a = self.store.read(); b = self.store.read(); a['document']['project']['name'] = 'First client'
        self.store.save(a['document'], a['revision'])
        with self.assertRaises(ConflictError): self.store.save(b['document'], b['revision'])
    def test_missing_revision_rejected(self):
        with self.assertRaises(ConflictError): self.store.save(self.store.read()['document'], None)
    def test_invalid_document_does_not_write(self):
        before = self.path.read_bytes(); snap = self.store.read(); snap['document']['tasks'][0]['depends_on'] = ['synthesis']
        with self.assertRaises(ValidationError): self.store.save(snap['document'], snap['revision'])
        self.assertEqual(self.path.read_bytes(), before)
    def test_backup_rotation(self):
        for i in range(23):
            x = self.store.read(); x['document']['project']['name'] = str(i); self.store.save(x['document'], x['revision'])
        self.assertEqual(len(list(self.path.parent.glob('.research-flow/backups/project.yaml/*.yaml'))), 20)

class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.path = Path(cls.temp.name) / 'project.yaml'
        cls.path.write_text((ROOT / 'examples/research-project.yaml').read_text())
        cls.store = ProjectStore(cls.path)
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(cls.store))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close(); cls.temp.cleanup()
    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers or {})
        response = conn.getresponse(); status = response.status; data = response.read(); conn.close(); return status, data
    def test_real_http_load(self):
        code, body = self.request('GET', '/api/project'); self.assertEqual(code, 200); self.assertIn('document', json.loads(body))
    def test_real_http_save(self):
        _, body = self.request('GET', '/api/project'); snap = json.loads(body); snap['document']['project']['name'] = 'Via HTTP'
        code, _ = self.request('PUT', '/api/project', snap, {'Content-Type': 'application/json', 'X-Research-Flow': '1'})
        self.assertEqual(code, 200); self.assertEqual(self.store.read()['document']['project']['name'], 'Via HTTP')
    def test_cross_origin_rejected(self): self.assertEqual(self.request('GET', '/api/project', headers={'Origin': 'https://example.com'})[0], 403)
    def test_untrusted_host_rejected(self): self.assertEqual(self.request('GET', '/api/project', headers={'Host': 'evil.example'})[0], 403)
    def test_missing_custom_header_rejected(self): self.assertEqual(self.request('PUT', '/api/project', {}, {'Content-Type': 'application/json'})[0], 403)
    def test_path_traversal_rejected(self): self.assertEqual(self.request('GET', '/../server.py')[0], 404)
    def test_project_file_not_exposed_as_static(self): self.assertEqual(self.request('GET', '/project.yaml')[0], 404)
    def test_yaml_validation_endpoint(self):
        code, body = self.request('POST', '/api/validate', {'yaml': self.path.read_text()}, {'Content-Type': 'application/json', 'X-Research-Flow': '1'})
        self.assertEqual(code, 200); self.assertIn('document', json.loads(body))
if __name__ == '__main__': unittest.main(verbosity=2)
