"""Self-update CLI regressions without network access or installation changes."""
from contextlib import ExitStack, contextmanager
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server
import updater


class UpdateCLITests(unittest.TestCase):
    @contextmanager
    def cli(self, directory, arguments, *, update_effect=None):
        """Guard every startup side effect while exercising the real parser."""
        previous = Path.cwd()
        try:
            os.chdir(directory)
            with ExitStack() as stack:
                stack.enter_context(patch('sys.argv', ['research-flow', *arguments]))
                output = stack.enter_context(patch('sys.stdout', new_callable=io.StringIO))
                errors = stack.enter_context(patch('sys.stderr', new_callable=io.StringIO))
                update = stack.enter_context(patch.object(updater, 'update_installation',
                                                         side_effect=update_effect))
                guards = []
                for name in ('default_project_path', 'default_token_path',
                             'confirm_new_project', 'initialize_project', 'ProjectStore',
                             'access_token', 'bind_server', 'webbrowser.open'):
                    guards.append(stack.enter_context(patch(
                        'server.' + name,
                        side_effect=AssertionError(f'Update must not call {name}'))))
                yield update, output, errors
                for guard in guards:
                    guard.assert_not_called()
        finally:
            os.chdir(previous)

    def test_update_ignores_empty_or_ambiguous_workflow_directory(self):
        for names in ((), ('first.yaml', 'second.yml')):
            with self.subTest(workflows=names), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                for name in names:
                    (directory / name).write_text(f'Original workflow: {name}\n')
                before = {path.name: path.read_bytes() for path in directory.iterdir()}

                def updated(_root):
                    print('Update complete. Restart Research Flow to use the new version.')

                with self.cli(directory, ['--update'], update_effect=updated) as (update, output, errors):
                    server.main()
                    update.assert_called_once_with(server.ROOT)
                    self.assertIn('Restart Research Flow', output.getvalue())
                    self.assertNotIn('listening on', output.getvalue())
                    self.assertEqual(errors.getvalue(), '')
                self.assertEqual({path.name: path.read_bytes() for path in directory.iterdir()}, before)

    def test_update_failure_exits_nonzero_without_starting_server(self):
        for error in (updater.UpdateError('Local changes prevent update.'),
                      OSError('Could not run git.'), ValueError('Invalid installation.')):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as temp:
                with self.cli(temp, ['--update'], update_effect=error) as (update, output, errors):
                    with self.assertRaises(SystemExit) as stopped:
                        server.main()
                    self.assertNotEqual(stopped.exception.code, 0)
                    update.assert_called_once_with(server.ROOT)
                    self.assertIn('Cannot update:', errors.getvalue())
                    self.assertIn(str(error), errors.getvalue())
                    self.assertNotIn('listening on', output.getvalue())
                self.assertEqual(list(Path(temp).iterdir()), [])

    def test_update_rejects_every_startup_option_before_updating(self):
        options = (
            ['--project', 'workflow.yaml'], ['--init'],
            ['--port', str(server.DEFAULT_PORT)], ['--port=0'],
            ['--browser-port', '18765'], ['--token-file', 'private.token'],
            ['--print-url'], ['--open'], ['--no-open'],
        )
        for option in options:
            with self.subTest(option=option), tempfile.TemporaryDirectory() as temp:
                with self.cli(temp, ['--update', *option]) as (update, output, errors):
                    with self.assertRaises(SystemExit) as stopped:
                        server.main()
                    self.assertEqual(stopped.exception.code, 2)
                    update.assert_not_called()
                    self.assertIn('--update', errors.getvalue())
                    self.assertNotIn('listening on', output.getvalue())
                self.assertEqual(list(Path(temp).iterdir()), [])

    def test_subprocess_help_describes_update(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, str(ROOT / 'server.py'), '--help'],
                                    cwd=temp, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--update', result.stdout)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_subprocess_rejects_update_with_init_without_running_updater(self):
        # Run the source entrypoint in a fresh interpreter. The stub ensures even
        # a parser regression cannot reach the network or change this checkout.
        runner = '''
import runpy
import sys
import types
stub = types.ModuleType('updater')
stub.UpdateError = RuntimeError
def forbidden_update(*args, **kwargs):
    raise AssertionError('Updater must not run with incompatible options')
stub.update_installation = forbidden_update
sys.modules['updater'] = stub
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
'''
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(
                [sys.executable, '-c', runner, str(ROOT / 'server.py'), '--update', '--init'],
                cwd=temp, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('--update', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(list(Path(temp).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
