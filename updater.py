"""Explicit updates from the official repository, independent of workflow data."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPOSITORY = 'https://github.com/SpicyChicken6/research-flow.git'
SOURCE_URL = 'https://github.com/SpicyChicken6/research-flow/archive/refs/heads/main.zip'


class UpdateError(RuntimeError):
    pass


def run(command, *, capture=False, env=None):
    try:
        return subprocess.run(command, check=True, text=True, capture_output=capture, env=env)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or '').strip() if capture else ''
        raise UpdateError(detail or f'{Path(command[0]).name} exited with status {error.returncode}; see output above.') from error
    except OSError as error:
        raise UpdateError(f'Could not run {command[0]}: {error}') from error


def pip_command(source, *, editable=False):
    return [sys.executable, '-m', 'pip', 'install', '--upgrade', '--force-reinstall',
            '--no-cache-dir', *(['--editable'] if editable else []), str(source)]


def update_checkout(root):
    git = shutil.which('git')
    if not git:
        raise UpdateError('Git is required to update a source checkout.')
    command = [git, '-C', str(root)]
    top = run([*command, 'rev-parse', '--show-toplevel'], capture=True).stdout.strip()
    if Path(top).resolve() != root:
        raise UpdateError('The source directory must be the root of its own Git checkout.')
    branch = run([*command, 'branch', '--show-current'], capture=True).stdout.strip()
    if branch != 'main':
        raise UpdateError('Source updates require the main branch. Switch branches yourself after saving local work.')
    if run([*command, 'status', '--porcelain', '--untracked-files=normal'], capture=True).stdout.strip():
        raise UpdateError('The source checkout has local changes. Commit or move them before updating.')
    # Check installer availability before changing source files.
    run([sys.executable, '-m', 'pip', '--version'], capture=True)
    run([*command, 'fetch', REPOSITORY, 'main'])
    ahead = run([*command, 'rev-list', '--count', 'FETCH_HEAD..HEAD'], capture=True).stdout.strip()
    if ahead != '0':
        raise UpdateError('The main branch has local commits. Reconcile them manually before updating.')
    # Ignored workflows and tokens must not be overwritten by newly tracked files.
    run([*command, 'merge', '--ff-only', '--no-autostash', '--no-overwrite-ignore', 'FETCH_HEAD'])
    run(pip_command(root, editable=True))


def update_pipx(prefix, metadata):
    pipx = shutil.which('pipx')
    if not pipx:
        raise UpdateError('This installation is managed by pipx. Make the pipx command available on PATH and retry.')
    package = metadata.get('main_package', {})
    suffix = package.get('suffix') or ''
    if (package.get('package') != 'research-flow' or not isinstance(suffix, str)
            or prefix.parent.name != 'venvs' or prefix.name != f'research-flow{suffix}'):
        raise UpdateError('Cannot identify this pipx environment. Update it with your pipx installation command.')
    # Derive the home from this running installation, even when the caller's
    # PIPX_HOME points elsewhere. Let pipx update its own installation metadata.
    env = {**os.environ, 'PIPX_HOME': str(prefix.parent.parent)}
    command = [pipx, 'install', '--force', '--pip-args=--no-cache-dir']
    if suffix:
        command += [f'--suffix={suffix}']
    run([*command, SOURCE_URL], env=env)


def update_installation(root):
    root = Path(root).resolve()
    prefix = Path(sys.prefix).resolve()
    print('Updating Research Flow from the official repository (main)...', flush=True)
    if (root / '.git').exists():
        if (prefix / 'pipx_metadata.json').exists():
            raise UpdateError('Update this editable pipx checkout manually, then reinstall it with pipx --editable to preserve its source link.')
        update_checkout(root)
    elif (root / 'pyproject.toml').exists():
        raise UpdateError('This source archive has no Git checkout. Install Research Flow with pipx, or use a Git clone to update in place.')
    elif (prefix / 'pipx_metadata.json').is_file():
        try:
            metadata = json.loads((prefix / 'pipx_metadata.json').read_text())
            if not isinstance(metadata, dict) or not isinstance(metadata.get('main_package'), dict):
                raise ValueError('invalid metadata')
        except (OSError, ValueError) as error:
            raise UpdateError('Cannot read this pipx installation metadata. Repair the installation with pipx.') from error
        update_pipx(prefix, metadata)
    else:
        run(pip_command(SOURCE_URL))
    print('Update complete. Restart Research Flow to use the updated code.', flush=True)
