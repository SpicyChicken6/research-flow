#!/usr/bin/env python3
"""Single-project Research Flow server for loopback access through an SSH tunnel."""
from __future__ import annotations
import argparse
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import signal
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import yaml

ROOT = Path(__file__).resolve().parent
VERSION = "0.8.7"
DEFAULT_PORT = 8765
MAX_BYTES = 2_000_000
STATUSES = {'todo', 'in_progress', 'blocked', 'done'}
MAX_SUBSTEPS = 200

class ValidationError(ValueError):
    pass

class ConflictError(ValueError):
    pass

class UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader, additionally refusing silently overwritten duplicate YAML keys."""

def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ValidationError('YAML mapping keys must be strings.')
        if key in result:
            raise ValidationError(f'Duplicate YAML key: {key}')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result
UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)

def json_safe(value, active=None, depth=0):
    if active is None:
        active = set()
    if depth > 50:
        raise ValidationError('Project nesting is too deep.')
    if isinstance(value, (list, dict)):
        if id(value) in active:
            raise ValidationError('Recursive YAML aliases are not supported.')
        active.add(id(value))
        if isinstance(value, dict):
            for key in value:
                if not isinstance(key, str) or key in {'__proto__', 'constructor', 'prototype'}:
                    raise ValidationError('Unsupported object key.')
            children = value.values()
        else:
            children = value
        for child in children:
            json_safe(child, active, depth + 1)
        active.remove(id(value))
    elif value is not None and not isinstance(value, (str, bool, int, float)):
        raise ValidationError('Only JSON-compatible YAML values are supported; quote dates as strings.')
    elif isinstance(value, (int, float)) and (abs(value) > 2**53 - 1 or not math.isfinite(value)):
        raise ValidationError('Numbers must be finite and within JavaScript’s safe numeric range.')

def validate_project(value):
    json_safe(value)
    if not isinstance(value, dict) or type(value.get('schema_version')) is not int or value['schema_version'] != 1:
        raise ValidationError('schema_version must be 1.')
    project = value.get('project')
    if not isinstance(project, dict) or not isinstance(project.get('name'), str) or not project['name'].strip():
        raise ValidationError('Give the project a name.')
    for field in ('id', 'description'):
        if field in project and not isinstance(project[field], str):
            raise ValidationError(f'project.{field} must be text.')
    tasks = value.get('tasks')
    if not isinstance(tasks, list) or len(tasks) > 500:
        raise ValidationError('tasks must be a list with at most 500 tasks.')
    # Copy through JSON so validation never mutates the caller and unknown metadata survives.
    value = json.loads(json.dumps(value, ensure_ascii=False))
    tasks, by_id = value['tasks'], {}
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get('id'), str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', task['id']):
            raise ValidationError('Task IDs must use letters, numbers, underscores, or hyphens (1–64 characters).')
        task_id = task['id']
        if task_id in by_id:
            raise ValidationError(f'Duplicate task ID: {task_id}')
        by_id[task_id] = task
        if not isinstance(task.get('title'), str) or not task['title'].strip():
            raise ValidationError(f'Give task {task_id} a title.')
        if 'step_number' in task and (type(task['step_number']) is not int or not 1 <= task['step_number'] <= 9007199254740991):
            raise ValidationError(f'{task_id}.step_number must be a positive whole number.')
        task.setdefault('status', 'todo')
        if not isinstance(task['status'], str) or task['status'] not in STATUSES:
            raise ValidationError(f'Invalid status for {task_id}.')
        for field in ('goal', 'notes'):
            task.setdefault(field, '')
        for field in ('goal', 'notes', 'agent_instructions'):
            if field in task and not isinstance(task[field], str):
                raise ValidationError(f'{task_id}.{field} must be text.')
        for field in ('depends_on', 'inputs', 'outputs'):
            task.setdefault(field, [])
            if not isinstance(task[field], list) or not all(isinstance(v, str) for v in task[field]):
                raise ValidationError(f'{task_id}.{field} must be a list of strings.')
        if len(set(task['depends_on'])) != len(task['depends_on']):
            raise ValidationError(f'Duplicate dependency on {task_id}.')
        # An optional backward-compatible field. Do not add empty lists to old files.
        if 'substeps' in task:
            subs = task['substeps']
            if not isinstance(subs, list) or len(subs) > MAX_SUBSTEPS:
                raise ValidationError(f'{task_id}.substeps must be a list with at most {MAX_SUBSTEPS} entries.')
            sub_ids = set()
            for sub in subs:
                if not isinstance(sub, dict) or not isinstance(sub.get('id'), str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', sub['id']):
                    raise ValidationError(f'Invalid substep ID on {task_id}.')
                if sub['id'] in sub_ids:
                    raise ValidationError(f'Duplicate substep ID on {task_id}: {sub["id"]}')
                sub_ids.add(sub['id'])
                if not isinstance(sub.get('title'), str) or not sub['title'].strip():
                    raise ValidationError(f'Give substep {sub["id"]} a title.')
                sub.setdefault('status', 'todo')
                sub.setdefault('notes', '')
                if not isinstance(sub['status'], str) or sub['status'] not in STATUSES:
                    raise ValidationError(f'Invalid status for substep {sub["id"]}.')
                if not isinstance(sub['notes'], str):
                    raise ValidationError(f'Substep {sub["id"]}.notes must be text.')

    assigned = [task['step_number'] for task in tasks if not task.get('parent_id') and 'step_number' in task]
    if len(set(assigned)) != len(assigned):
        raise ValidationError('Main step numbers must be unique.')

    if any('substeps' in task for task in tasks):
        added = []
        ids = set(by_id)
        for parent in tasks:
            for sub in parent.pop('substeps', []):
                base = f'{parent["id"]}_{sub["id"]}'[:54]
                child_id, suffix = base, 2
                while child_id in ids:
                    child_id = f'{base}_{suffix}'
                    suffix += 1
                ids.add(child_id)
                child = dict(id=child_id, title=sub['title'], status=sub['status'],
                             notes=sub['notes'], goal='', inputs=[], outputs=[],
                             depends_on=[], parent_id=parent['id'])
                if set(sub) - {'id', 'title', 'status', 'notes'}:
                    child['legacy_substep'] = sub
                added.append(child)
        tasks.extend(added)
        if len(tasks) > 500:
            raise ValidationError('Converting existing substeps would exceed the 500-step limit. Your original file is unchanged.')
        return validate_project(value)
    for task in tasks:
        parent = task.get('parent_id')
        if parent is not None and (not isinstance(parent, str) or parent not in by_id):
            raise ValidationError(f'Unknown or invalid parent on {task["id"]}.')
        seen = {task['id']}
        while parent is not None:
            if parent in seen:
                raise ValidationError('Parent cycle: a step cannot belong to itself or a descendant.')
            seen.add(parent)
            entry = by_id.get(parent)
            if entry is None:
                raise ValidationError('Unknown parent.')
            parent = entry.get('parent_id')
            if parent is not None and not isinstance(parent, str):
                raise ValidationError('Invalid parent ID.')

    for task in tasks:
        for dep in task['depends_on']:
            if dep not in by_id:
                raise ValidationError(f'Unknown dependency {dep} on {task["id"]}.')
            if dep == task['id']:
                raise ValidationError('A task cannot depend on itself.')
    visited, active = set(), set()
    def visit(task_id):
        if task_id in active:
            raise ValidationError('Dependency cycle detected.')
        if task_id in visited:
            return
        active.add(task_id)
        for dep in by_id[task_id]['depends_on']:
            visit(dep)
        active.remove(task_id)
        visited.add(task_id)
    for task_id in by_id:
        visit(task_id)
    layout = value.setdefault('layout', {})
    if not isinstance(layout, dict):
        raise ValidationError('layout must be an object.')
    positions = layout.setdefault('positions', {})
    if not isinstance(positions, dict):
        raise ValidationError('layout.positions must be an object.')
    for task_id, position in positions.items():
        if not isinstance(position, dict) or not all(type(position.get(k)) in (int, float) and math.isfinite(position[k]) and abs(position[k]) <= 10000000 for k in ('x', 'y')):
            raise ValidationError(f'Invalid layout position: {task_id}')
    return value

def parse_project(text):
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_BYTES:
        raise ValidationError('Project files must be UTF-8 text under 2 MB.')
    try:
        for token in yaml.scan(text):
            if isinstance(token, yaml.tokens.AliasToken):
                raise ValidationError('YAML aliases are not supported; use explicit values.')
        return validate_project(yaml.load(text, Loader=UniqueKeyLoader))
    except (yaml.YAMLError, RecursionError) as error:
        raise ValidationError(f'Invalid YAML: {error}') from error

def revision(raw):
    return hashlib.sha256(raw).hexdigest()

class ProjectStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.lock = threading.Lock()
    def read(self):
        raw = self.path.read_bytes()
        if len(raw) > MAX_BYTES:
            raise ValidationError('Project files must be under 2 MB.')
        text = raw.decode('utf-8')
        return {'document': parse_project(text), 'revision': revision(raw), 'yaml': text, 'file': str(self.path)}
    def save(self, document, expected_revision):
        document = validate_project(document)
        content = yaml.safe_dump(document, allow_unicode=True, sort_keys=False, width=100).encode('utf-8')
        if len(content) > MAX_BYTES:
            raise ValidationError('Project files must be under 2 MB.')
        with self.lock:
            current = self.path.read_bytes()
            if not isinstance(expected_revision, str) or revision(current) != expected_revision:
                raise ConflictError('The file changed on disk. Download your draft, then reload the file before saving.')
            backups = self.path.parent / '.research-flow' / 'backups' / self.path.name
            backups.mkdir(parents=True, exist_ok=True, mode=0o700)
            backup = backups / f'{time.time_ns()}.yaml'
            with backup.open('xb') as out:
                out.write(current)
            os.chmod(backup, 0o600)
            temp_path = None
            try:
                fd, temp_path = tempfile.mkstemp(prefix=f'.{self.path.name}.', suffix='.tmp', dir=self.path.parent)
                with os.fdopen(fd, 'wb') as out:
                    out.write(content)
                    out.flush()
                    os.fsync(out.fileno())
                os.chmod(temp_path, self.path.stat().st_mode & 0o777)
                # Protect against common editor/agent writes during this save, too.
                if revision(self.path.read_bytes()) != expected_revision:
                    raise ConflictError('The file changed during the save. Reload before trying again.')
                os.replace(temp_path, self.path)
                temp_path = None
            finally:
                if temp_path:
                    Path(temp_path).unlink(missing_ok=True)
            for old in sorted(backups.glob('*.yaml'))[:-20]:
                old.unlink(missing_ok=True)
            return self.read()

STATIC = {'/': ('index.html', 'text/html; charset=utf-8'), '/index.html': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/model.mjs': ('model.mjs', 'text/javascript; charset=utf-8'),
          '/connection.mjs': ('connection.mjs', 'text/javascript; charset=utf-8'),
          '/styles.css': ('styles.css', 'text/css; charset=utf-8'),
          '/assets/research-flow-icon-light.svg': ('assets/research-flow-icon-light.svg', 'image/svg+xml'),
          '/assets/research-flow-icon-dark.svg': ('assets/research-flow-icon-dark.svg', 'image/svg+xml')}

def make_handler(store, *, auth_token=None, browser_port=None):
    """Build a handler. CLI always supplies a token; None is for in-process tests only."""
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, format, *args):
            # Never log request targets (which may accidentally contain secrets).
            pass

        def authenticated(self):
            if auth_token is not None and not secrets.compare_digest(
                self.headers.get('X-Research-Flow-Token', '').encode('utf-8'), auth_token.encode('ascii')
            ):
                self.send_json(401, {'error': 'Open the private access URL printed by the server to connect.'})
                return False
            return True
        def allowed(self):
            ports = {self.server.server_port}
            if browser_port is not None:
                ports.add(browser_port)
            hosts = {f'{name}:{port}' for name in ('localhost', '127.0.0.1') for port in ports}
            if self.headers.get('Host') not in hosts:
                self.send_json(403, {'error': 'Only localhost access is supported.'})
                return False
            origin = self.headers.get('Origin')
            if (origin and origin not in {f'http://{host}' for host in hosts}) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                self.send_json(403, {'error': 'Cross-origin access is not allowed.'})
                return False
            return True
        def send_json(self, status, data):
            self.send_body(status, json.dumps(data, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
        def send_body(self, status, body, content_type):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            if not self.allowed(): return
            path = urlsplit(self.path).path
            try:
                if path.startswith('/api/') and not self.authenticated():
                    return
                if path == '/api/project':
                    self.send_json(200, store.read())
                elif path == '/healthz':
                    self.send_json(200, {'status': 'ok', 'version': VERSION})
                elif path in STATIC:
                    file, content_type = STATIC[path]
                    self.send_body(200, (ROOT / 'web' / file).read_bytes(), content_type)
                else:
                    self.send_json(404, {'error': 'Not found.'})
            except (ValidationError, UnicodeError, OSError) as error:
                self.send_json(400, {'error': str(error)})
        def mutation(self, method):
            if not self.allowed() or not self.authenticated(): return
            if self.headers.get('X-Research-Flow') != '1' or self.headers.get_content_type() != 'application/json':
                self.send_json(403, {'error': 'A same-origin JSON request is required.'}); return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= MAX_BYTES:
                    raise ValidationError('Request must be under 2 MB.')
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValidationError('Request must be an object.')
                path = urlsplit(self.path).path
                if method == 'POST' and path == '/api/validate':
                    result = parse_project(payload.get('yaml'))
                    self.send_json(200, {'document': result})
                elif method == 'PUT' and path == '/api/project':
                    self.send_json(200, store.save(payload.get('document'), payload.get('revision')))
                else:
                    self.send_json(404, {'error': 'Not found.'})
            except ConflictError as error:
                self.send_json(409, {'error': str(error)})
            except (ValidationError, ValueError, UnicodeError, OSError, RecursionError) as error:
                self.send_json(400, {'error': str(error)})
        def do_PUT(self): self.mutation('PUT')
        def do_POST(self): self.mutation('POST')
    return Handler

def default_project_path():
    """Use the only YAML in the launch directory, or a new workflow.yaml."""
    directory = Path.cwd()
    candidates = sorted(path for path in directory.iterdir()
                        if path.suffix.lower() in {'.yaml', '.yml'}
                        and (path.is_file() or path.is_symlink()))
    if len(candidates) > 1:
        names = ', '.join(repr(path.name) for path in candidates)
        raise ValidationError(f'Multiple YAML files in the current directory: {names}. '
                              'Choose one with --project /path/to/file.yaml.')
    return candidates[0] if candidates else directory / 'workflow.yaml'


def read_confirmation(prompt):
    """Read a terminal answer while letting Escape cancel without Enter."""
    import termios
    import tty
    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    answer = []
    try:
        tty.setcbreak(fd)
        print(prompt, end='', flush=True)
        while True:
            key = os.read(fd, 1)
            if not key or key == b'\x04':
                raise EOFError
            if key in (b'\x1b', b'\x03'):
                raise KeyboardInterrupt
            if key in (b'\r', b'\n'):
                print(flush=True)
                return ''.join(answer)
            if key in (b'\x7f', b'\x08'):
                if answer:
                    answer.pop()
                    print('\b \b', end='', flush=True)
            else:
                char = key.decode('utf-8', errors='replace')
                if char.isprintable():
                    answer.append(char)
                    print(char, end='', flush=True)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)


def confirm_new_project(path):
    """Require an explicit choice before creating a workflow in an empty folder."""
    if not sys.stdin.isatty():
        raise ValidationError(f'No workflow file found in {path.parent}. '
                              'Run research-flow --init to create workflow.yaml, '
                              'or use --project /path/to/file.yaml.')
    print(f'No workflow file found in {path.parent}.', flush=True)
    while True:
        try:
            answer = read_confirmation(f'Create a new workflow at {path}? [Y/n] (Esc to cancel) ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print('\nCancelled. No files created.', flush=True)
            return False
        if answer in ('', 'y', 'yes'):
            return True
        if answer in ('n', 'no'):
            print('Cancelled. No files created.', flush=True)
            return False
        print('Please answer yes or no.', flush=True)


def initialize_project(path):
    """Create a private blank project only when it does not already exist."""
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    document = {'schema_version': 1,
                'project': {'id': 'research-project', 'name': 'Untitled project', 'description': ''},
                'tasks': [], 'layout': {'positions': {}}}
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, 'w', encoding='utf-8') as out:
        yaml.safe_dump(document, out, allow_unicode=True, sort_keys=False)
        out.flush()
        os.fsync(out.fileno())
    return True


def default_token_path(project_path):
    path = Path(project_path).resolve()
    return path.parent / '.research-flow' / f'{path.name}.token'


def access_token(path, *, create=True):
    """Create/read a private bearer token without following a final symlink."""
    path = Path(path).expanduser().absolute()
    if create:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'w', encoding='ascii') as out:
                out.write(secrets.token_urlsafe(32) + '\n')
                out.flush()
                os.fsync(out.fileno())
    if path.is_symlink():
        raise ValidationError('Token file must not be a symbolic link.')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, 'r', encoding='ascii') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValidationError('Token file must be a regular file.')
        if os.name == 'posix' and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
            raise ValidationError('Token file must be owned by your user with mode 600. Run chmod 600 on it.')
        token = source.read(4097).strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token):
        raise ValidationError('Invalid token file. Use a 32–128 character URL-safe random token.')
    return token


def valid_port(value):
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError('Port must be a whole number.') from error
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError('Port must be between 0 and 65535.')
    return port


def bind_server(port, handler, *, auto_port=False):
    """Bind directly so choosing an available port cannot race with another process."""
    while True:
        try:
            return ThreadingHTTPServer(('127.0.0.1', port), handler)
        except OSError as error:
            if not auto_port or error.errno != errno.EADDRINUSE or port == 0 or port == 65535:
                raise
            port += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=f'Research Flow {VERSION}')
    parser.add_argument('--update', action='store_true', help='Update this installation from the latest official main branch, then exit.')
    parser.add_argument('--project', type=Path, help='Project file. By default, use the only YAML in the current directory, or ask before creating workflow.yaml if none exists.')
    parser.add_argument('--init', action='store_true', help='Create a blank project without prompting if the selected file is missing; never overwrite it.')
    parser.add_argument('--port', type=valid_port, default=DEFAULT_PORT,
                        help=f'Server port (default: {DEFAULT_PORT}; tries subsequent ports if busy). Other ports must be available; 0 selects an OS-assigned port.')
    parser.add_argument('--browser-port', type=valid_port, help='Local forwarded port when it differs from --port.')
    parser.add_argument('--token-file', type=Path, help='Private access-token file (created when absent).')
    parser.add_argument('--print-url', action='store_true', help='Print the private access URL for an existing token, then exit.')
    parser.add_argument('--open', action='store_true', help='Open a local browser; disabled by default for headless Linux.')
    parser.add_argument('--no-open', action='store_true', help=argparse.SUPPRESS)  # Compatibility with earlier launch commands.
    args = parser.parse_args()
    if args.update:
        if len(sys.argv[1:]) != 1:
            parser.error('--update must be used on its own.')
        if __package__:
            from .updater import UpdateError, update_installation
        else:
            from updater import UpdateError, update_installation
        try:
            update_installation(ROOT)
        except (UpdateError, OSError, ValueError) as error:
            parser.exit(1, f'Cannot update: {error}\n')
        return
    if args.browser_port == 0:
        parser.error('--browser-port must be a specific port, not 0.')
    try:
        path = (args.project.expanduser() if args.project else default_project_path()).absolute()
        token_path = args.token_file or default_token_path(path)
        if args.print_url:
            if args.port == 0:
                raise ValidationError('--print-url needs the running server port.')
            token = access_token(token_path, create=False)
            print(f'http://127.0.0.1:{args.browser_port or args.port}/#token={token}', flush=True)
            return
        if args.project is None and not args.init and not path.exists() and not path.is_symlink():
            if not confirm_new_project(path):
                return
        if args.project is None or args.init:
            initialize_project(path)
        if not path.is_file():
            raise ValidationError('Project file not found. Use --init to create a blank file at this path.')
        store = ProjectStore(path)
        store.read()
        token = access_token(token_path)
        httpd = bind_server(args.port,
                            make_handler(store, auth_token=token, browser_port=args.browser_port),
                            auto_port=args.port == DEFAULT_PORT)
    except (OSError, ValueError, UnicodeError) as error:
        parser.exit(1, f'Cannot start: {error}\n')
    if args.port == DEFAULT_PORT and httpd.server_port != args.port:
        print(f'Warning: default port {args.port} is already in use; using port {httpd.server_port} instead.',
              file=sys.stderr, flush=True)
    local_port = args.browser_port or httpd.server_port
    url = f'http://127.0.0.1:{local_port}/#token={token}'
    print(f'Research Flow {VERSION} — listening on 127.0.0.1:{httpd.server_port}\n'
          f'Project: {store.path}\nPrivate access URL (do not share):\n{url}\n'
          f'On your computer, forward port {local_port} to server port {httpd.server_port}.\n'
          'Press Ctrl+C to stop.', flush=True)
    if args.open and not args.no_open:
        timer = threading.Timer(0.6, lambda: webbrowser.open(url))
        timer.daemon = True
        timer.start()
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=httpd.shutdown, daemon=True).start())
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        print('Stopped.', flush=True)


if __name__ == '__main__':
    main()
