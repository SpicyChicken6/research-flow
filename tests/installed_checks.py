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
import re
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


def run(executable):
    executable = str(Path(executable).resolve())
    with tempfile.TemporaryDirectory(prefix='research-flow-installed-') as temp:
        work = Path(temp)
        env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
        env['XDG_DATA_HOME'] = str(work / 'default data')
        version = subprocess.check_output([executable, '--version'], cwd=work, env=env, text=True)
        assert version.strip() == 'Research Flow 0.8.7', version
        for scenario in ('explicit', 'empty', 'existing'):
            cwd = work / scenario
            cwd.mkdir()
            project = cwd / 'workflow.yaml'
            args = []
            if scenario == 'explicit':
                project = cwd / 'my study' / 'workflow.yaml'
                args = ['--project', str(project), '--init']
                # An explicit path must bypass an otherwise ambiguous directory.
                (cwd / 'a.yaml').write_text('unrelated configuration')
                (cwd / 'b.yml').write_text('other configuration')
            elif scenario == 'existing':
                project = cwd / 'my-study.yml'
                project.write_text('# Keep this comment until Save\nschema_version: 1\nproject:\n  name: Existing study\ntasks: []\ncustom: preserved\n')
            if scenario == 'empty':
                refusal = subprocess.run([executable], cwd=cwd, env=env, input='',
                                         capture_output=True, text=True, timeout=10)
                assert refusal.returncode != 0 and '--init' in refusal.stderr
                assert not list(cwd.iterdir()), 'Noninteractive launch must not create files'
                args = ['--init']
            original = project.read_bytes() if project.exists() else None
            proc = subprocess.Popen([executable, *args, '--port', '0'], cwd=cwd, env=env,
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
                preview = project.with_suffix('.html')
                assert not preview.exists(), 'Opening a workflow must not generate a preview'
                if original is not None:
                    assert project.read_bytes() == original, 'Opening an existing workflow must not rewrite it'
                    assert snapshot['document']['custom'] == 'preserved'
                snapshot['document']['project']['name'] = 'Installed app saved this'
                status, data = request('PUT', '/api/project', snapshot)
                assert status == 200
                result = json.loads(data)
                assert result['preview_file'] == str(preview.resolve())
                assert result['preview_warning'] is None
                assert 'Installed app saved this' in project.read_text()
                assert token not in project.read_text()
                html = preview.read_text()
                assert '<!doctype html>' in html.lower()
                embedded = re.search(r'<script id="initial-project" type="application/json">(.*?)</script>', html, re.S)
                assert embedded and json.loads(embedded[1]) == snapshot['document']
                assert 'window.RESEARCH_FLOW_VIEWER' in html
                assert not re.search(r'<script\b[^>]*\bsrc=', html)
                assert 'href="styles.css"' not in html
                assert 'href="assets/' not in html
                assert token not in html
                assert not project.with_suffix('.svg').exists(), 'Save must not create an automatic SVG'
                saved = project.read_bytes()
                status, data = request('POST', '/api/export/svg',
                                       {'document': snapshot['document'], 'layout_mode': 'freeform'})
                assert status == 200
                svg = json.loads(data)['svg']
                assert ET.fromstring(svg).tag == '{http://www.w3.org/2000/svg}svg'
                assert 'Installed app saved this' in svg and token not in svg
                assert project.read_bytes() == saved and preview.read_text() == html
                assert list((project.parent / '.research-flow/backups' / project.name).glob('*.yaml'))
                assert request('PUT', '/api/project', snapshot)[0] == 409
                assert preview.read_text() == html, 'A conflict must preserve the saved preview'
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
                                                cwd=cwd, env=env, text=True)
            assert recovered.strip() == url
            assert project.read_bytes() == saved
            if scenario == 'existing':
                assert not (cwd / 'workflow.yaml').exists(), 'Discovery must not create a second workflow'
            print('PASS installed app:', scenario, flush=True)
        assert not Path(env['XDG_DATA_HOME']).exists(), 'Default launch must use the current folder'
    print('ALL INSTALLED APP CHECKS PASSED', flush=True)


if __name__ == '__main__':
    run(sys.argv[1])
