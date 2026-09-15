#!/usr/bin/env python3
"""Publish this reviewed source bundle to a NEW PRIVATE repository. Never force-push."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*args, capture=False):
    return subprocess.run(args, cwd=ROOT, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--owner', default='SpicyChicken6')
    p.add_argument('--repo', default='research-flow')
    a = p.parse_args()
    for tool in ('git', 'gh'):
        if not shutil.which(tool):
            p.exit(1, f'Install {tool} first. For gh, then run: gh auth login --hostname github.com\n')
    user = json.loads(run('gh', 'api', 'user', capture=True))
    if user['login'].lower() != a.owner.lower():
        p.exit(1, f'Authenticated as {user["login"]}, not {a.owner}. Switch accounts before publishing.\n')
    files = (ROOT / '.release-files').read_text().splitlines()
    if not files or any(not f or Path(f).is_absolute() or '..' in Path(f).parts for f in files):
        p.exit(1, 'Invalid release manifest. Nothing has been uploaded.\n')
    for f in files:
        path = ROOT / f
        if not path.is_file() or path.is_symlink():
            p.exit(1, f'Missing or unsafe release file: {f}\n')
    if not (ROOT / '.git').exists():
        run('git', 'init', '--initial-branch=main', '.')
        # Stage only the reviewed manifest. Never "git add ." in a data workspace.
        run('git', 'add', '--', *files)
        run('git', '-c', f'user.name={user["login"]}', '-c',
            f'user.email={user["id"]}+{user["login"]}@users.noreply.github.com',
            'commit', '-m', 'Release Research Flow 0.8.0 for private Linux deployment')
    top = Path(run('git', 'rev-parse', '--show-toplevel', capture=True).strip()).resolve()
    if top != ROOT.resolve():
        p.exit(1, 'Refusing to publish from inside a different repository.\n')
    if run('git', 'rev-list', '--count', 'HEAD', capture=True).strip() != '1':
        p.exit(1, 'Refusing to push pre-existing history. Publish a fresh source-only release folder.\n')
    tracked = set(run('git', 'ls-files', capture=True).splitlines())
    if tracked != set(files):
        p.exit(1, 'Tracked files differ from the reviewed release manifest. Review the repository before publishing.\n')
    if run('git', 'status', '--porcelain', capture=True).strip():
        p.exit(1, 'There are local changes. Review and commit them before publishing.\n')
    if run('git', 'remote', capture=True).strip():
        p.exit(1, 'A remote is already configured. Refusing to replace it or publish twice.\n')
    name = f'{a.owner}/{a.repo}'
    exists = subprocess.run(['gh', 'repo', 'view', name], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if exists:
        p.exit(1, f'{name} already exists. Nothing was pushed; use a new name or review that remote manually.\n')
    # GitHub CLI will also refuse name collisions and report connectivity/auth errors.
    run('gh', 'repo', 'create', name, '--private', '--source=.', '--remote=origin',
        '--push', '--description', 'Single-project visual workflow editor with nested steps and private Linux deployment.')
    sha = run('git', 'rev-parse', 'HEAD', capture=True).strip()
    remote = run('gh', 'api', f'repos/{name}/commits/{sha}', '--jq', '.sha', capture=True).strip()
    if remote != sha:
        p.exit(1, 'Remote verification failed. Check the repository before retrying.\n')
    print(f'Published and verified https://github.com/{name} at {sha}')


if __name__ == '__main__':
    try:
        main()
    except (subprocess.CalledProcessError, OSError, ValueError) as error:
        sys.exit(f'Publishing stopped: {error}. No force push was attempted.')
