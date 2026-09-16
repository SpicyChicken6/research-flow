"""Linux release security, startup and build regression tests; disposable files only."""
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import (ROOT, ProjectStore, ValidationError, access_token,
                    default_project_path, default_token_path, initialize_project,
                    make_handler, parse_project, main)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_blank_initialization(self):
        path = self.root / 'work/project.yaml'
        self.assertTrue(initialize_project(path))
        doc = parse_project(path.read_text())
        self.assertEqual(doc['tasks'], [])
        self.assertEqual(doc['project']['name'], 'Untitled project')
        if os.name == 'posix':
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_init_preserves_existing_even_invalid(self):
        path = self.root / 'project.yaml'
        path.write_bytes(b'original bytes\nnot valid yaml')
        self.assertFalse(initialize_project(path))
        self.assertEqual(path.read_bytes(), b'original bytes\nnot valid yaml')

    def test_empty_directory_defaults_to_workflow_without_creating_it(self):
        with patch('server.Path.cwd', return_value=self.root):
            self.assertEqual(default_project_path(), self.root / 'workflow.yaml')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cli_empty_noninteractive_directory_requires_init(self):
        result = subprocess.run([sys.executable, str(ROOT / 'server.py')], cwd=self.root,
                                input='yes\n', capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No workflow file found', result.stderr)
        self.assertIn('--init', result.stderr)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_empty_folder_prompt_decline_or_interrupt_creates_nothing(self):
        for answer in ('n', 'NO', EOFError(), KeyboardInterrupt()):
            with self.subTest(answer=repr(answer)), patch('server.Path.cwd', return_value=self.root), \
                 patch('sys.argv', ['research-flow']), patch('server.sys.stdin.isatty', return_value=True), \
                 patch('server.read_confirmation', side_effect=[answer]) as prompt, patch('sys.stdout', new_callable=io.StringIO) as output:
                main()
                prompt.assert_called_once()
                self.assertIn('[Y/n]', prompt.call_args.args[0])
                self.assertIn(str(self.root / 'workflow.yaml'), prompt.call_args.args[0])
                self.assertIn('Cancelled', output.getvalue())
                self.assertEqual(list(self.root.iterdir()), [])

    def test_empty_folder_prompt_accepts_yes_after_invalid_answer(self):
        with patch('server.Path.cwd', return_value=self.root), patch('sys.argv', ['research-flow']), \
             patch('server.sys.stdin.isatty', return_value=True), patch('server.read_confirmation', side_effect=['maybe', ' YES ']) as prompt, \
             patch('sys.stdout', new_callable=io.StringIO) as output, patch('server.ThreadingHTTPServer') as httpd, patch('server.signal.signal'):
            httpd.return_value.server_port = 8765
            main()
            self.assertEqual(prompt.call_count, 2)
            self.assertIn('Please answer yes or no', output.getvalue())
            httpd.return_value.serve_forever.assert_called_once()
        self.assertEqual(parse_project((self.root / 'workflow.yaml').read_text())['tasks'], [])
        self.assertTrue(default_token_path(self.root / 'workflow.yaml').is_file())

    def test_print_url_empty_directory_never_prompts_or_creates(self):
        with patch('server.Path.cwd', return_value=self.root), patch('sys.argv', ['research-flow', '--print-url']), \
             patch('server.read_confirmation') as prompt, patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaises(SystemExit): main()
            prompt.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_only_yaml_is_selected_regardless_of_name_or_extension(self):
        for name in ('my-study.yaml', 'plan.yml', 'STUDY.YAML'):
            with self.subTest(name=name):
                path = self.root / name
                path.write_text('original bytes')
                with patch('server.Path.cwd', return_value=self.root):
                    self.assertEqual(default_project_path(), path)
                self.assertEqual(path.read_text(), 'original bytes')
                path.unlink()

    def test_discovery_is_not_recursive_and_ignores_other_files(self):
        (self.root / 'nested').mkdir()
        (self.root / 'nested/project.yaml').write_text('nested')
        (self.root / 'config.json').write_text('{}')
        (self.root / 'folder.yaml').mkdir()
        with patch('server.Path.cwd', return_value=self.root):
            self.assertEqual(default_project_path(), self.root / 'workflow.yaml')

    def test_multiple_yaml_files_require_an_explicit_choice(self):
        for name in ('workflow.yaml', 'other.yml'):
            (self.root / name).write_text(name)
        with patch('server.Path.cwd', return_value=self.root):
            with self.assertRaisesRegex(ValidationError, 'Multiple YAML.*--project'):
                default_project_path()
        self.assertEqual((self.root / 'workflow.yaml').read_text(), 'workflow.yaml')

    def test_xdg_does_not_override_current_directory(self):
        with patch.dict(os.environ, {'XDG_DATA_HOME': 'irrelevant'}), patch('server.Path.cwd', return_value=self.root):
            self.assertEqual(default_project_path(), self.root / 'workflow.yaml')

    def test_cli_ambiguous_directory_does_not_create_or_modify_files(self):
        for name in ('a.yaml', 'b.yml'):
            initialize_project(self.root / name)
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        result = subprocess.run([sys.executable, str(ROOT / 'server.py')], cwd=self.root,
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--project', result.stderr)
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir()}, before)

    def test_cli_invalid_discovered_yaml_is_not_replaced_or_ignored(self):
        path = self.root / 'study.yml'
        path.write_text('not a research workflow')
        result = subprocess.run([sys.executable, str(ROOT / 'server.py')], cwd=self.root,
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('schema_version', result.stderr)
        self.assertEqual(path.read_text(), 'not a research workflow')
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_token_is_stable_private_and_random(self):
        path = default_token_path(self.root / 'project.yaml')
        token = access_token(path)
        self.assertEqual(access_token(path, create=False), token)
        self.assertGreaterEqual(len(token), 32)
        self.assertNotEqual(access_token(self.root / 'other.token'), token)
        if os.name == 'posix': self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_no_create_for_print_url(self):
        path = self.root / 'missing.token'
        with self.assertRaises(OSError): access_token(path, create=False)
        self.assertFalse(path.exists())

    def test_refuse_token_symlink(self):
        target = self.root / 'actual.token'
        access_token(target)
        link = self.root / 'link.token'
        link.symlink_to(target)
        with self.assertRaises(ValidationError): access_token(link)

    @unittest.skipUnless(os.name == 'posix', 'POSIX permissions')
    def test_refuse_world_readable_token(self):
        path = self.root / 'open.token'
        access_token(path)
        path.chmod(0o644)
        with self.assertRaises(ValidationError): access_token(path)

    def test_refuse_malformed_token(self):
        path = self.root / 'bad.token'
        path.write_text('bad token')
        path.chmod(0o600)
        with self.assertRaises(ValidationError): access_token(path)

    def test_cli_explicit_missing_file_does_not_create(self):
        path = self.root / 'missing.yaml'
        result = subprocess.run([sys.executable, str(ROOT / 'server.py'), '--project', str(path)],
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--init', result.stderr)
        self.assertFalse(path.exists())

    def test_cli_print_url_uses_alternate_port(self):
        path = self.root / 'p.yaml'
        token = access_token(default_token_path(path))
        result = subprocess.run([sys.executable, str(ROOT / 'server.py'), '--project', str(path),
                                 '--browser-port', '18765', '--print-url'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), f'http://127.0.0.1:18765/#token={token}')
        self.assertFalse(path.exists())

    def test_preview_build_does_not_modify_sources(self):
        spec = importlib.util.spec_from_file_location('builder', ROOT / 'scripts/build_preview.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        before = (ROOT / 'web/index.html').read_bytes()
        out = mod.build(output=self.root / 'portable.html')
        content = out.read_text()
        self.assertEqual((ROOT / 'web/index.html').read_bytes(), before)
        self.assertIn('window.RESEARCH_FLOW_PREVIEW = true;', content)
        self.assertNotIn('href="assets/', content)
        self.assertNotIn('src="app.js"', content)
        self.assertNotIn('href="styles.css"', content)
        self.assertIn('data:image/svg+xml;base64,', content)
        self.assertNotIn('refinements/', content)


class PrivateHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name) / 'project.yaml'
        initialize_project(cls.path)
        cls.token = 'test-token-' + 'x' * 40
        cls.store = ProjectStore(cls.path)
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0),
                                       make_handler(cls.store, auth_token=cls.token, browser_port=18765))
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.thread.join()
        cls.httpd.server_close()
        cls.temp.cleanup()

    def request(self, path='/api/project', *, method='GET', token=None, headers=None, data=None):
        h = {'Content-Type': 'application/json', 'X-Research-Flow': '1'}
        if token is not None: h['X-Research-Flow-Token'] = token
        h.update(headers or {})
        c = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=4)
        c.request(method, path, body=json.dumps(data) if data is not None else None, headers=h)
        r = c.getresponse()
        result = (r.status, dict(r.getheaders()), r.read())
        c.close()
        return result

    def test_read_requires_token(self): self.assertEqual(self.request()[0], 401)
    def test_bad_token_denied(self): self.assertEqual(self.request(token='wrong')[0], 401)
    def test_nonascii_token_denied(self): self.assertEqual(self.request(token='\xe9'*40)[0], 401)
    def test_authenticated_read(self): self.assertEqual(self.request(token=self.token)[0], 200)
    def test_health_no_secrets(self):
        status, _, body = self.request('/healthz')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['status'], 'ok')
        self.assertNotIn(self.token.encode(), body)
        self.assertNotIn(str(self.path).encode(), body)
    def test_public_shell_no_project_or_token(self):
        status, headers, body = self.request('/')
        self.assertEqual(status, 200)
        self.assertNotIn(self.token.encode(), body)
        self.assertNotIn(str(self.path).encode(), body)
        self.assertEqual(headers['X-Frame-Options'], 'DENY')
        self.assertEqual(headers['Cache-Control'], 'no-store')
    def test_favicons_served(self):
        for variant in ('light', 'dark'):
            status, headers, _ = self.request(f'/assets/research-flow-icon-{variant}.svg')
            self.assertEqual(status, 200)
            self.assertEqual(headers['Content-Type'], 'image/svg+xml')
    def test_write_requires_token_and_does_not_mutate(self):
        before = self.path.read_bytes()
        self.assertEqual(self.request(method='PUT', data={'document':{},'revision':'x'})[0], 401)
        self.assertEqual(self.path.read_bytes(), before)
    def test_validation_requires_token(self):
        self.assertEqual(self.request('/api/validate', method='POST', data={'yaml':'x'})[0], 401)
    def test_token_does_not_bypass_origin_checks(self):
        self.assertEqual(self.request(token=self.token, headers={'Origin':'https://evil.example'})[0], 403)
    def test_token_does_not_bypass_host_checks(self):
        self.assertEqual(self.request(token=self.token, headers={'Host':'evil.example'})[0], 403)
    def test_alternate_tunnel_port_accepted(self):
        self.assertEqual(self.request(token=self.token, headers={'Host':'127.0.0.1:18765',
                         'Origin':'http://127.0.0.1:18765'})[0], 200)
    def test_unconfigured_tunnel_port_denied(self):
        self.assertEqual(self.request(token=self.token, headers={'Host':'127.0.0.1:19999'})[0], 403)
    def test_files_not_served_by_generic_handler(self):
        for path in ('/server.py','/project.yaml','/.research-flow/project.yaml.token','/../server.py'):
            self.assertEqual(self.request(path, token=self.token)[0], 404)
    def test_authenticated_save_conflict_and_backup(self):
        start = self.store.read()
        doc = start['document']
        doc['project']['name'] = 'Private fixture'
        status, _, body = self.request(method='PUT', token=self.token,
                                      data={'document':doc,'revision':start['revision']})
        self.assertEqual(status, 200)
        self.assertEqual(parse_project(self.path.read_text())['project']['name'], 'Private fixture')
        self.assertNotIn(self.token.encode(), body)
        self.assertTrue(list((self.path.parent/'.research-flow/backups/project.yaml').glob('*.yaml')))
        self.assertEqual(self.request(method='PUT', token=self.token,
                         data={'document':doc,'revision':start['revision']})[0], 409)


if __name__ == '__main__': unittest.main()
