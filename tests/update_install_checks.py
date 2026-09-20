#!/usr/bin/env python3
"""Offline self-update checks against disposable pip and pipx installations.

Usage: python tests/update_install_checks.py /path/research_flow-VERSION.whl /path/to/pipx
Place compatible PyYAML and pip wheels beside the Research Flow wheel first.
Only standard-library dependencies are required by the harness itself.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

MARKER = '# Disposable self-update regression marker\n'


def command(args, cwd, env):
    result = subprocess.run([str(arg) for arg in args], cwd=cwd, env=env,
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise AssertionError(f'Command failed: {args}\n{result.stdout}\n{result.stderr}')
    return result.stdout


def snapshot(directory):
    return {str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob('*') if path.is_file()}


def verify_update(python, wheel, cwd, env, prefix, *, metadata=None):
    details = json.loads(command([python, '-c', '''
import json
from pathlib import Path
import sys
from research_flow import server
print(json.dumps({'server': str(Path(server.__file__).resolve()),
                  'prefix': str(Path(sys.prefix).resolve()), 'version': server.VERSION}))
'''], cwd, env))
    assert Path(details['prefix']) == prefix.resolve(), details
    installed_server = Path(details['server'])
    assert installed_server.is_relative_to(prefix.resolve()), installed_server
    installed_server.write_text(installed_server.read_text() + MARKER)
    before = snapshot(cwd)
    output = command([python, '-c', '''
import sys
from research_flow import server, updater
updater.SOURCE_URL = sys.argv[1]
sys.argv = ['research-flow', '--update']
server.main()
''', wheel], cwd, env)
    assert 'Update complete. Restart Research Flow' in output, output
    assert 'listening on' not in output, output
    # A new interpreter verifies the on-disk package, not the modules still
    # loaded by the update process after its own installation was replaced.
    refreshed = json.loads(command([python, '-c', '''
import json
from pathlib import Path
from research_flow import server, updater
print(json.dumps({'source': Path(server.__file__).read_text(),
                  'version': server.VERSION, 'updater': str(Path(updater.__file__).resolve())}))
'''], cwd, env))
    assert MARKER not in refreshed['source'], 'Same-version update left stale source installed'
    assert refreshed['version'] == details['version'], 'Fixture should exercise same-version reinstall'
    assert Path(refreshed['updater']).is_relative_to(prefix.resolve()), refreshed['updater']
    assert snapshot(cwd) == before, 'Update changed workflow data or token files'
    if metadata:
        updated = json.loads(metadata.read_text())['main_package']
        assert updated['package_or_url'] == str(wheel), updated
    print(output.strip(), flush=True)


def run(wheel, pipx):
    wheel = Path(wheel).resolve(strict=True)
    pipx = Path(pipx).absolute()
    assert pipx.is_file(), pipx
    with zipfile.ZipFile(wheel) as archive:
        assert 'research_flow/updater.py' in archive.namelist()
    print('PASS wheel includes research_flow/updater.py', flush=True)
    with tempfile.TemporaryDirectory(prefix='research-flow-update-install-') as temp:
        work = Path(temp).resolve()
        cwd = work / 'workflows'
        cwd.mkdir()
        (cwd / 'workflow.yaml').write_text('# Keep this workflow\nschema_version: 1\nproject:\n  name: Existing\ntasks: []\n')
        (cwd / 'other.yml').write_text('unrelated: preserved\n')
        token_dir = cwd / '.research-flow'
        token_dir.mkdir()
        (token_dir / 'workflow.yaml.token').write_text('disposable-test-credential\n')
        (token_dir / 'backups').mkdir()
        (token_dir / 'backups' / 'saved.yaml').write_text('old workflow preserved\n')
        before = snapshot(cwd)
        initial_dir = work / 'initial'
        initial_dir.mkdir()
        initial_wheel = initial_dir / wheel.name
        shutil.copyfile(wheel, initial_wheel)
        env = {key: value for key, value in os.environ.items()
               if key not in {'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'}
               and not key.startswith(('PIP_', 'PIPX_'))}
        env.update({
            'PIP_NO_INDEX': '1', 'PIP_FIND_LINKS': str(wheel.parent),
            'PIP_DISABLE_PIP_VERSION_CHECK': '1', 'PIP_NO_CACHE_DIR': '1',
            'PIP_CONFIG_FILE': os.devnull,
            'PIPX_HOME': str(work / 'pipx'), 'PIPX_BIN_DIR': str(work / 'bin'),
            'PIPX_MAN_DIR': str(work / 'man'), 'PIPX_LOG_DIR': str(work / 'logs'),
            'PIPX_DEFAULT_BACKEND': 'pip', 'PIPX_DEFAULT_PYTHON': sys.executable,
            'PIPX_FETCH_PYTHON': 'never',
            'PATH': str(pipx.parent) + os.pathsep + env.get('PATH', ''),
        })

        prefix = work / 'ordinary-venv'
        command([sys.executable, '-m', 'venv', prefix], cwd, env)
        python = prefix / 'bin/python'
        command([python, '-m', 'pip', 'install', initial_wheel], cwd, env)
        verify_update(python, wheel, cwd, env, prefix)
        print('PASS ordinary venv: same-version source replaced; workflow, token, and backup preserved', flush=True)

        for suffix in ('', '-test'):
            args = [pipx, 'install', '--python', sys.executable]
            if suffix:
                args += [f'--suffix={suffix}']
            command([*args, initial_wheel], cwd, env)
            prefix = Path(env['PIPX_HOME']) / 'venvs' / f'research-flow{suffix}'
            metadata = prefix / 'pipx_metadata.json'
            original = json.loads(metadata.read_text())['main_package']
            assert original['package_or_url'] == str(initial_wheel), original
            assert (original.get('suffix') or '') == suffix, original
            caller_env = dict(env)
            caller_env['PIPX_HOME'] = str(work / 'unrelated-pipx-home')
            verify_update(prefix / 'bin/python', wheel, cwd, caller_env, prefix, metadata=metadata)
            assert not Path(caller_env['PIPX_HOME']).exists(), 'Update used the caller home instead of the active installation'
            launcher = Path(env['PIPX_BIN_DIR']) / f'research-flow{suffix}'
            assert launcher.is_file(), launcher
            assert '--update' in command([launcher, '--help'], cwd, env)
            print(f'PASS pipx{suffix or " (no suffix)"}: same-version source replaced; metadata and active home correct; workflows preserved', flush=True)
        assert snapshot(cwd) == before
    print('ALL INSTALLED UPDATE CHECKS PASSED', flush=True)


if __name__ == '__main__':
    run(sys.argv[1], sys.argv[2])
