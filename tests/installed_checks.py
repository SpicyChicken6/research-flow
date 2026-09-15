#!/usr/bin/env python3
"""Exercise an installed entry point from outside the source checkout.

Usage: python tests/installed_checks.py /absolute/path/to/research-flow
Only standard-library dependencies are needed by this harness.
"""
import http.client
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlsplit


def run(executable):
    executable = str(Path(executable).resolve())
    with tempfile.TemporaryDirectory(prefix='research-flow-installed-') as temp:
        work = Path(temp)
        env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
        env['XDG_DATA_HOME'] = str(work / 'default data')
        version = subprocess.check_output([executable, '--version'], cwd=work, env=env, text=True)
        assert version.strip() == 'Research Flow 0.8.1', version
        # Test both an explicit path (including spaces) and the default data path.
        for explicit in (True, False):
            project = work / 'my study' / 'workflow.yaml' if explicit else Path(env['XDG_DATA_HOME']) / 'research-flow/project.yaml'
            args = ['--project', str(project), '--init'] if explicit else []
            proc = subprocess.Popen([executable, *args, '--port', '0'], cwd=work, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            lines = queue.Queue()
            def consume():
                for line in proc.stdout:
                    lines.put(line.strip())
            reader = threading.Thread(target=consume, daemon=True)
            reader.start()
            try:
                url = None
                for _ in range(6):
                    line = lines.get(timeout=15)
                    if '#token=' in line:
                        url = line
                        break
                assert url, 'Installed server did not print its access URL'
                parts = urlsplit(url)
                token = parts.fragment.removeprefix('token=')
                headers = {'X-Research-Flow-Token': token, 'X-Research-Flow': '1',
                           'Content-Type': 'application/json'}
                def request(method, path, body=None, authenticated=True):
                    conn = http.client.HTTPConnection('127.0.0.1', parts.port, timeout=5)
                    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                                 headers=headers if authenticated else {})
                    response = conn.getresponse()
                    status, data = response.status, response.read()
                    conn.close()
                    return status, data
                for asset in ('/', '/app.js', '/model.mjs', '/connection.mjs', '/styles.css',
                              '/assets/research-flow-icon-light.svg', '/assets/research-flow-icon-dark.svg'):
                    status, data = request('GET', asset)
                    assert status == 200 and data, asset
                assert request('GET', '/api/project', authenticated=False)[0] == 401
                assert request('GET', '/server.py')[0] == 404
                status, data = request('GET', '/api/project')
                assert status == 200
                snapshot = json.loads(data)
                assert Path(snapshot['file']) == project.resolve()
                assert snapshot['document']['tasks'] == []
                snapshot['document']['project']['name'] = 'Installed app saved this'
                status, _ = request('PUT', '/api/project', snapshot)
                assert status == 200
                assert 'Installed app saved this' in project.read_text()
                assert token not in project.read_text()
                assert list((project.parent / '.research-flow/backups' / project.name).glob('*.yaml'))
                assert request('PUT', '/api/project', snapshot)[0] == 409
                saved = project.read_bytes()
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
                reader.join(timeout=2)
                proc.stdout.close()
                proc.stderr.close()
            assert proc.returncode == 0, 'Server did not shut down cleanly'
            # Recover the same persistent credential without modifying the YAML.
            recovered = subprocess.check_output([executable, *args, '--port', str(parts.port), '--print-url'],
                                                cwd=work, env=env, text=True)
            assert recovered.strip() == url
            assert project.read_bytes() == saved
            print('PASS installed app:', 'explicit project path' if explicit else 'default data path', flush=True)
        assert not (work / 'project.yaml').exists(), 'Unexpected workflow in the working directory'
    print('ALL INSTALLED APP CHECKS PASSED', flush=True)


if __name__ == '__main__':
    run(sys.argv[1])
