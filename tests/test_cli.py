"""Real headless CLI + TCP forwarding smoke test, without a browser dependency."""
import http.client
import json
import os
from pathlib import Path
import queue
import re
import select
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class Forward(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection(('127.0.0.1', self.server.remote_port), timeout=4) as remote:
            while True:
                ready, _, _ = select.select([self.request, remote], [], [], 6)
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


class CLITests(unittest.TestCase):
    def test_headless_start_forwarded_save_and_shutdown(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / 'data'
            env = {**os.environ, 'XDG_DATA_HOME': str(data)}
            relay = Relay(('127.0.0.1', 0), Forward)
            local_port = relay.server_address[1]
            # Launch from a different CWD; code and data locations must be independent.
            proc = subprocess.Popen(
                [sys.executable, str(ROOT / 'server.py'), '--port', '0',
                 '--browser-port', str(local_port)], cwd=temp, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            messages = queue.Queue()
            def consume():
                for line in proc.stdout:
                    messages.put(line.strip())
            threading.Thread(target=consume, daemon=True).start()
            relay_started = False
            try:
                startup = []
                url = None
                for _ in range(6):
                    line = messages.get(timeout=10)
                    startup.append(line)
                    if '#token=' in line:
                        url = line
                        break
                self.assertIsNotNone(url, 'Server must report its private URL')
                remote = re.search(r'listening on 127\.0\.0\.1:(\d+)', '\n'.join(startup))
                self.assertIsNotNone(remote)
                relay.remote_port = int(remote.group(1))
                self.assertNotEqual(local_port, relay.remote_port)
                thread = threading.Thread(target=relay.serve_forever, daemon=True)
                thread.start()
                relay_started = True
                token = parse_qs(urlsplit(url).fragment)['token'][0]
                self.assertEqual(urlsplit(url).port, local_port)
                def request(method, path, payload=None, authenticated=True):
                    c = http.client.HTTPConnection('127.0.0.1', local_port, timeout=4)
                    headers = {'Origin':f'http://127.0.0.1:{local_port}',
                               'X-Research-Flow':'1', 'Content-Type':'application/json'}
                    if authenticated:
                        headers['X-Research-Flow-Token'] = token
                    c.request(method, path, json.dumps(payload) if payload else None, headers)
                    response = c.getresponse()
                    result = response.status, response.read()
                    c.close()
                    return result
                self.assertEqual(request('GET', '/healthz', authenticated=False)[0], 200)
                self.assertEqual(request('GET', '/api/project', authenticated=False)[0], 401)
                status, body = request('GET', '/api/project')
                self.assertEqual(status, 200)
                doc = json.loads(body)
                self.assertEqual(doc['document']['tasks'], [])
                doc['document']['project']['name'] = 'CLI forwarded smoke test'
                status, _ = request('PUT', '/api/project', doc)
                self.assertEqual(status, 200)
                workflow = data / 'research-flow/project.yaml'
                self.assertIn('CLI forwarded smoke test', workflow.read_text())
                self.assertNotIn(token, workflow.read_text())
                self.assertTrue(list((workflow.parent / '.research-flow/backups/project.yaml').glob('*.yaml')))
                if os.name == 'posix':
                    self.assertEqual(workflow.stat().st_mode & 0o777, 0o600)
                    self.assertEqual((workflow.parent / '.research-flow/project.yaml.token').stat().st_mode & 0o777, 0o600)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
                if relay_started:
                    relay.shutdown()
                relay.server_close()
                proc.stdout.close()
                proc.stderr.close()
            self.assertEqual(proc.returncode, 0, 'SIGTERM should shut down gracefully')


if __name__ == '__main__':
    unittest.main()
