"""Update routing and disposable Git regressions; never contact the public repo."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import updater


class InstalledUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'site-packages' / 'research_flow'
        self.root.mkdir(parents=True)
        self.prefix = self.base / 'environment'
        self.prefix.mkdir()

    def test_pip_refreshes_same_version_using_current_interpreter(self):
        workflow = self.base / 'workflow.yaml'
        workflow.write_text('private workflow, untouched\n')
        with patch.object(updater.sys, 'prefix', str(self.prefix)), \
                patch.object(updater.sys, 'executable', '/current/environment/bin/python'), \
                patch.object(updater, 'run') as run, redirect_stdout(io.StringIO()) as output:
            updater.update_installation(self.root)
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ['/current/environment/bin/python', '-m', 'pip', 'install'])
        self.assertIn('--upgrade', command)
        self.assertIn('--force-reinstall', command)
        self.assertIn('--no-cache-dir', command)
        self.assertNotIn('--no-deps', command)
        self.assertEqual(command[-1], updater.SOURCE_URL)
        self.assertIn('Update complete', output.getvalue())
        self.assertEqual(workflow.read_text(), 'private workflow, untouched\n')
        self.assertFalse((self.base / '.research-flow').exists())

    def make_pipx_environment(self, suffix=''):
        prefix = self.base / 'actual-pipx-home' / 'venvs' / f'research-flow{suffix}'
        prefix.mkdir(parents=True)
        metadata = {'main_package': {'package': 'research-flow', 'suffix': suffix,
                                    'package_or_url': 'old-pinned-wheel.whl'}}
        path = prefix / 'pipx_metadata.json'
        path.write_text(json.dumps(metadata))
        return prefix, path

    def test_pipx_uses_own_home_suffix_and_leaves_metadata_to_pipx(self):
        for suffix in ('', '-dev'):
            with self.subTest(suffix=suffix):
                prefix, metadata = self.make_pipx_environment(suffix)
                original = metadata.read_bytes()
                with patch.object(updater.sys, 'prefix', str(prefix)), \
                        patch.object(updater.shutil, 'which', return_value='/tools/pipx'), \
                        patch.dict(os.environ, {'PIPX_HOME': '/wrong/home', 'PIPX_BIN_DIR': '/custom/bin'}), \
                        patch.object(updater, 'run') as run, redirect_stdout(io.StringIO()):
                    updater.update_installation(self.root)
                run.assert_called_once()
                command = run.call_args.args[0]
                self.assertEqual(command[:3], ['/tools/pipx', 'install', '--force'])
                self.assertIn('--pip-args=--no-cache-dir', command)
                self.assertEqual(command[-1], updater.SOURCE_URL)
                self.assertEqual(any(arg.startswith('--suffix=') for arg in command), bool(suffix))
                if suffix:
                    self.assertIn(f'--suffix={suffix}', command)
                env = run.call_args.kwargs['env']
                self.assertEqual(env['PIPX_HOME'], str(prefix.parent.parent))
                self.assertEqual(env['PIPX_BIN_DIR'], '/custom/bin')
                self.assertEqual(metadata.read_bytes(), original)

    def test_missing_pipx_does_not_fall_back_to_pip(self):
        prefix, _ = self.make_pipx_environment()
        with patch.object(updater.sys, 'prefix', str(prefix)), \
                patch.object(updater.shutil, 'which', return_value=None), \
                patch.object(updater, 'run') as run, redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(updater.UpdateError, 'pipx command available'):
                updater.update_installation(self.root)
        run.assert_not_called()
        self.assertNotIn('Update complete', output.getvalue())

    def test_bad_pipx_metadata_does_not_fall_back_to_pip(self):
        prefix, metadata = self.make_pipx_environment()
        for value in ('{broken', '[]', '{"main_package": null}',
                      '{"main_package": {"package": "another-app"}}'):
            with self.subTest(metadata=value):
                metadata.write_text(value)
                with patch.object(updater.sys, 'prefix', str(prefix)), \
                        patch.object(updater.shutil, 'which', return_value='/tools/pipx'), \
                        patch.object(updater, 'run') as run, redirect_stdout(io.StringIO()):
                    with self.assertRaises(updater.UpdateError):
                        updater.update_installation(self.root)
                run.assert_not_called()

    def test_source_archive_does_not_install_a_separate_copy(self):
        (self.root / 'pyproject.toml').write_text('[project]\nname = "research-flow"\n')
        with patch.object(updater, 'run') as run, redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(updater.UpdateError, 'no Git checkout'):
                updater.update_installation(self.root)
        run.assert_not_called()
        self.assertNotIn('Update complete', output.getvalue())

    def test_editable_pipx_does_not_change_checkout_or_installation(self):
        prefix, _ = self.make_pipx_environment()
        (self.root / '.git').mkdir()
        with patch.object(updater.sys, 'prefix', str(prefix)), \
                patch.object(updater, 'run') as run, redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(updater.UpdateError, 'editable pipx'):
                updater.update_installation(self.root)
        run.assert_not_called()
        self.assertNotIn('Update complete', output.getvalue())

    def test_failed_installer_does_not_report_success(self):
        with patch.object(updater.sys, 'prefix', str(self.prefix)), \
                patch.object(updater, 'run', side_effect=updater.UpdateError('download failed')), \
                redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(updater.UpdateError, 'download failed'):
                updater.update_installation(self.root)
        self.assertNotIn('Update complete', output.getvalue())

    def test_subprocess_errors_are_actionable_update_errors(self):
        failure = subprocess.CalledProcessError(1, ['git'], stderr='fatal: network unavailable\n')
        with patch.object(updater.subprocess, 'run', side_effect=failure):
            with self.assertRaisesRegex(updater.UpdateError, 'fatal: network unavailable'):
                updater.run(['git'], capture=True)
            with self.assertRaisesRegex(updater.UpdateError, 'status 1; see output above'):
                updater.run(['git'])
        with patch.object(updater.subprocess, 'run', side_effect=FileNotFoundError('missing')):
            with self.assertRaisesRegex(updater.UpdateError, 'Could not run git'):
                updater.run(['git'])


@unittest.skipUnless(shutil.which('git'), 'Git is required for checkout regressions')
class CheckoutUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.remote = self.base / 'upstream.git'
        self.author = self.base / 'author'
        self.checkout = self.base / 'checkout'
        self.git('init', '--bare', str(self.remote))
        self.git('init', '-b', 'main', str(self.author))
        self.configure(self.author)
        (self.author / 'code.py').write_text('revision = 1\n')
        (self.author / 'pyproject.toml').write_text('[project]\nname = "research-flow"\nversion = "0.8.6"\n')
        (self.author / '.gitignore').write_text('.research-flow/\nworkflow.yaml\n')
        self.commit(self.author, 'Initial version')
        self.git('-C', str(self.author), 'push', str(self.remote), 'main')
        self.git('clone', '--branch', 'main', str(self.remote), str(self.checkout))
        self.configure(self.checkout)
        self.initial_head = self.git('-C', str(self.checkout), 'rev-parse', 'HEAD')
        self.pip_calls = []
        original_run = updater.run

        def intercepted_run(command, *, capture=False, env=None):
            if command[:3] == [sys.executable, '-m', 'pip']:
                self.pip_calls.append(command)
                return subprocess.CompletedProcess(command, 0, stdout='pip available\n')
            return original_run(command, capture=True, env=env)

        self.addCleanup(patch.stopall)
        patch.object(updater, 'REPOSITORY', str(self.remote)).start()
        patch.object(updater, 'run', side_effect=intercepted_run).start()

    def git(self, *args):
        return subprocess.run(['git', *args], check=True, text=True,
                              capture_output=True).stdout.strip()

    def configure(self, root):
        self.git('-C', str(root), 'config', 'user.name', 'Updater Test')
        self.git('-C', str(root), 'config', 'user.email', 'updater@example.invalid')

    def commit(self, root, message):
        self.git('-C', str(root), 'add', '.')
        self.git('-C', str(root), 'commit', '-m', message)

    def push_update(self):
        (self.author / 'code.py').write_text('revision = 2\n')
        self.commit(self.author, 'New code with unchanged package version')
        self.git('-C', str(self.author), 'push', str(self.remote), 'main')

    def assert_no_install(self):
        self.assertFalse(any('install' in command for command in self.pip_calls))

    def test_fast_forward_preserves_ignored_workflow_and_token(self):
        self.push_update()
        workflow = self.checkout / 'workflow.yaml'
        workflow.write_text('private workflow\n')
        token = self.checkout / '.research-flow' / 'workflow.yaml.token'
        token.parent.mkdir()
        token.write_text('private token\n')
        with redirect_stdout(io.StringIO()) as output:
            updater.update_installation(self.checkout)
        self.assertEqual((self.checkout / 'code.py').read_text(), 'revision = 2\n')
        self.assertEqual(workflow.read_text(), 'private workflow\n')
        self.assertEqual(token.read_text(), 'private token\n')
        self.assertEqual(self.pip_calls[-1], updater.pip_command(self.checkout, editable=True))
        self.assertIn('Update complete', output.getvalue())

    def test_dirty_tracked_or_untracked_changes_prevent_update(self):
        for filename in ('code.py', 'untracked.txt'):
            with self.subTest(filename=filename):
                path = self.checkout / filename
                previous = path.read_text() if path.exists() else None
                path.write_text('local work\n')
                try:
                    with self.assertRaisesRegex(updater.UpdateError, 'local changes'):
                        updater.update_checkout(self.checkout)
                    self.assertEqual(path.read_text(), 'local work\n')
                    self.assertEqual(self.pip_calls, [])
                finally:
                    if previous is None:
                        path.unlink()
                    else:
                        path.write_text(previous)

    def test_feature_branch_is_not_switched_or_installed_separately(self):
        self.git('-C', str(self.checkout), 'checkout', '-b', 'my-work')
        with redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(updater.UpdateError, 'main branch'):
                updater.update_installation(self.checkout)
        self.assertEqual(self.git('-C', str(self.checkout), 'branch', '--show-current'), 'my-work')
        self.assertEqual(self.pip_calls, [])
        self.assertNotIn('Update complete', output.getvalue())

    def test_diverged_commits_are_not_reset_or_merged(self):
        self.push_update()
        (self.checkout / 'local.txt').write_text('local committed work\n')
        self.commit(self.checkout, 'Local work')
        local_head = self.git('-C', str(self.checkout), 'rev-parse', 'HEAD')
        with self.assertRaisesRegex(updater.UpdateError, 'local commits'):
            updater.update_checkout(self.checkout)
        self.assertEqual(self.git('-C', str(self.checkout), 'rev-parse', 'HEAD'), local_head)
        self.assertEqual((self.checkout / 'code.py').read_text(), 'revision = 1\n')
        self.assert_no_install()

    def test_newly_tracked_file_cannot_overwrite_ignored_private_data(self):
        workflow = self.checkout / 'workflow.yaml'
        workflow.write_text('private workflow\n')
        (self.author / 'workflow.yaml').write_text('new upstream example\n')
        self.git('-C', str(self.author), 'add', '--force', 'workflow.yaml')
        self.commit(self.author, 'Track a previously ignored filename')
        self.git('-C', str(self.author), 'push', str(self.remote), 'main')
        with redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(updater.UpdateError):
                updater.update_installation(self.checkout)
        self.assertEqual(workflow.read_text(), 'private workflow\n')
        self.assertEqual(self.git('-C', str(self.checkout), 'rev-parse', 'HEAD'), self.initial_head)
        self.assert_no_install()
        self.assertNotIn('Update complete', output.getvalue())


if __name__ == '__main__':
    unittest.main()
