"""Real headless CLI + TCP forwarding smoke test, without a browser dependency."""
import http.client
import json
import os
from pathlib import Path
import queue
import pty
import time
import re
import select
import signal
import termios
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
    @unittest.skipUnless(os.name == 'posix', 'Terminal prompt requires a POSIX PTY')
    def test_real_terminal_confirmation_before_creating_files(self):
        for answer in (b'yes\n', b'\n', b'n\n', b'\x1b', b'\x03'):
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as temp:
                master, slave = pty.openpty()
                original_terminal = termios.tcgetattr(master)
                proc = subprocess.Popen([sys.executable, str(ROOT / 'server.py'), '--port', '0'],
                                        cwd=temp, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                os.close(slave)
                def read_until(marker):
                    output = b''
                    deadline = time.monotonic() + 10
                    while marker not in output:
                        remaining = deadline - time.monotonic()
                        self.assertGreater(remaining, 0, 'Timed out waiting for CLI prompt/startup')
                        ready, _, _ = select.select([proc.stdout], [], [], remaining)
                        self.assertTrue(ready, 'No CLI response')
                        chunk = os.read(proc.stdout.fileno(), 4096)
                        self.assertTrue(chunk, 'CLI exited before expected output')
                        output += chunk
                    return output
                try:
                    output = read_until(b'(Esc to cancel) ')
                    self.assertIn(b'No workflow file found', output)
                    self.assertIn(str(Path(temp) / 'workflow.yaml').encode(), output)
                    self.assertEqual(list(Path(temp).iterdir()), [])
                    if answer == b'\x03': proc.send_signal(signal.SIGINT)
                    else: os.write(master, answer)
                    if answer in (b'yes\n', b'\n'):
                        read_until(b'Press Ctrl+C to stop.')
                        self.assertTrue((Path(temp) / 'workflow.yaml').is_file())
                        self.assertTrue((Path(temp) / '.research-flow/workflow.yaml.token').is_file())
                    else:
                        stdout, stderr = proc.communicate(timeout=10)
                        self.assertEqual(proc.returncode, 0, stderr)
                        self.assertIn(b'Cancelled', stdout)
                        self.assertEqual(list(Path(temp).iterdir()), [])
                finally:
                    if proc.poll() is None: proc.terminate()
                    proc.communicate(timeout=10)
                    self.assertEqual(termios.tcgetattr(master), original_terminal, 'Prompt must restore terminal settings')
                    os.close(master)

    def test_headless_start_forwarded_save_and_shutdown(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / 'data'
            env = {**os.environ, 'XDG_DATA_HOME': str(data)}
            relay = Relay(('127.0.0.1', 0), Forward)
            local_port = relay.server_address[1]
            # Launch outside the checkout; the default workflow belongs to this CWD.
            proc = subprocess.Popen(
                [sys.executable, str(ROOT / 'server.py'), '--init', '--port', '0',
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
                workflow = Path(temp) / 'workflow.yaml'
                self.assertFalse(data.exists(), 'Default launch must not create XDG data')
                self.assertIn('CLI forwarded smoke test', workflow.read_text())
                self.assertNotIn(token, workflow.read_text())
                self.assertTrue(list((workflow.parent / '.research-flow/backups/workflow.yaml').glob('*.yaml')))
                if os.name == 'posix':
                    self.assertEqual(workflow.stat().st_mode & 0o777, 0o600)
                    self.assertEqual((workflow.parent / '.research-flow/workflow.yaml.token').stat().st_mode & 0o777, 0o600)
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
