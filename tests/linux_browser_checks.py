#!/usr/bin/env python3
"""Actual Chromium + CLI-server round trip through a local TCP port-forward.

This exercises the HTTP path rather than mocking fetch. The TCP relay simulates the
forwarding topology, not SSH encryption/authentication or the user's remote host.
"""
import http.client
import json
import os
from pathlib import Path
import re
import queue
import select
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import parse_project

OUT = ROOT / 'test-results'
OUT.mkdir(exist_ok=True)
CHECKS = []


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    CHECKS.append(label)
    print('PASS', label, flush=True)


class Forward(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection(('127.0.0.1', self.server.remote_port), timeout=5) as remote:
            while True:
                ready, _, _ = select.select([self.request, remote], [], [], 10)
                if not ready:
                    return
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    (remote if source is self.request else self.request).sendall(data)


class Relay(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def run():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'workflow.yaml'
        path.write_bytes((ROOT / 'examples/research-project.yaml').read_bytes())
        relay = Relay(('127.0.0.1', 0), Forward)
        local_port = relay.server_address[1]
        proc = subprocess.Popen([sys.executable, str(ROOT / 'server.py'), '--project', str(path),
                                 '--port', '0', '--browser-port', str(local_port)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # Startup output contains a private token. Consume it without printing/logging it.
        startup = []
        private_url = None
        relay_started = False
        messages = queue.Queue()
        def read_startup():
            for line in proc.stdout:
                messages.put(line.strip())
        threading.Thread(target=read_startup, daemon=True).start()
        try:
            for _ in range(6):
                try:
                    line = messages.get(timeout=10)
                except queue.Empty:
                    raise AssertionError('CLI startup timed out.') from None
                startup.append(line)
                if '#token=' in line:
                    private_url = line
                    break
            if not private_url:
                raise AssertionError('CLI server failed to start.')
            match = re.search(r'listening on 127\.0\.0\.1:(\d+)', '\n'.join(startup))
            check(bool(match), 'CLI starts headlessly on loopback')
            relay.remote_port = int(match.group(1))
            thread = threading.Thread(target=relay.serve_forever, daemon=True)
            thread.start()
            relay_started = True
            check(local_port != relay.remote_port, 'browser and server use different ports')
            token_path = path.parent / '.research-flow' / 'workflow.yaml.token'
            token = token_path.read_text().strip()
            check(token in private_url, 'CLI prints the private access URL for this instance')
            before = path.read_bytes()
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),
                                             headless=True, args=['--no-sandbox'])
                page = browser.new_page(viewport={'width':1600, 'height':1000}, reduced_motion='reduce')
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(private_url, wait_until='networkidle', timeout=15000)
                expect(page.locator('#save-state')).to_have_text('Saved')
                expect(page.locator('.task-node')).to_have_count(8)
                check(True, 'real HTTP navigation loads the project through the forwarded port')
                check(not urlsplit(page.url).fragment, 'private token is removed from the visible URL')
                check(page.evaluate("sessionStorage.getItem('research-flow-token')") == token, 'token stays in tab-scoped session storage')
                check(token not in page.content(), 'token is absent from rendered DOM')
                check(path.read_bytes() == before, 'opening a project does not rewrite its data')
                check(page.locator('#minimap-wrap').is_visible(), 'global minimap remains visible')
                check(page.locator('.header-divider').evaluate("e=>getComputedStyle(e).width==='2px'&&getComputedStyle(e).borderRadius==='0px'"),
                      'latest thin rectangular title accent is retained')
                page.screenshot(path=str(OUT / 'linux-overview.png'))
                page.locator('#add-button').click()
                expect(page.locator('.task-node')).to_have_count(9)
                check(not page.locator('#inspector').is_visible(), 'blank insertion still keeps the editor unobtrusive')
                node = page.locator('.task-node').last
                node.focus()
                page.keyboard.press('Enter')
                page.locator('[data-field=title]').fill('Forwarded-session edit')
                page.locator('#save-button').click()
                expect(page.locator('#save-state')).to_have_text('Saved')
                check(parse_project(path.read_text())['tasks'][-1]['title'] == 'Forwarded-session edit', 'authenticated UI save writes the actual YAML')
                check(bool(list((path.parent/'.research-flow/backups/workflow.yaml').glob('*.yaml'))), 'server save keeps a previous-version backup')
                check(token not in path.read_text(), 'private token is never written into the workflow')
                page.reload(wait_until='networkidle')
                expect(page.locator('.task-node')).to_have_count(9)
                expect(page.locator('#save-state')).to_have_text('Saved')
                check(True, 'reload reuses the tab credential without a token fragment')
                other = browser.new_page()
                other.goto(private_url.split('#')[0], wait_until='networkidle')
                expect(other.locator('#file-alert')).to_be_visible()
                check('private access URL' in other.locator('#file-alert').inner_text(), 'a fresh unauthenticated tab gets a clear connection message')
                check(other.locator('.task-node').count() == 0, 'unauthenticated tab cannot see the project or stale demo data')
                other.close()
                check(not errors, 'no uncaught JavaScript errors over the actual HTTP path')
                browser.close()
            # Auth is required even when the caller is another loopback client.
            client = http.client.HTTPConnection('127.0.0.1', local_port, timeout=5)
            client.request('GET', '/api/project')
            response = client.getresponse()
            check(response.status == 401, 'other loopback clients cannot read without the token')
            response.read()
            client.close()
            check(token_path.stat().st_mode & 0o777 == 0o600, 'stored access credential is owner-only')
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
            # Relay's serve loop only started after valid CLI startup.
            if relay_started:
                relay.shutdown()
            relay.server_close()
        check(proc.returncode == 0, 'SIGTERM stops the CLI server gracefully')
    (OUT/'linux-browser-checks.json').write_text(json.dumps(CHECKS, indent=2))
    print(f'ALL {len(CHECKS)} LINUX BROWSER CHECKS PASSED', flush=True)


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        # Even disposable test credentials should not be echoed by Playwright errors.
        message = re.sub(r'#token=[A-Za-z0-9_-]+', '#token=[REDACTED]', str(error))
        print(f'Linux browser verification failed: {message}', file=sys.stderr)
        sys.exit(1)
