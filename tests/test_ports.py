"""Port-conflict regressions using disposable workflows and real loopback sockets."""
from contextlib import ExitStack, contextmanager
import errno
import http.client
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


@contextmanager
def occupied_pair():
    """Reserve two consecutive ports after confirming a third is available."""
    for _ in range(100):
        with ExitStack() as sockets:
            first = sockets.enter_context(socket.socket())
            first.bind(('127.0.0.1', 0))
            port = first.getsockname()[1]
            if port > 65533:
                continue
            second = sockets.enter_context(socket.socket())
            probe = sockets.enter_context(socket.socket())
            try:
                second.bind(('127.0.0.1', port + 1))
                probe.bind(('127.0.0.1', port + 2))
            except OSError as error:
                if error.errno == errno.EADDRINUSE:
                    continue
                raise
            first.listen()
            second.listen()
            probe.close()
            yield port
            return
    raise RuntimeError('Could not reserve consecutive loopback ports for the test.')


class PortTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'workflow.yaml'
        server.initialize_project(self.path)

    def run_main(self, options, check_server):
        """Exercise the real listener while replacing UI launch and signal hooks."""
        original_serve = ThreadingHTTPServer.serve_forever

        def serve(httpd):
            thread = threading.Thread(target=original_serve, args=(httpd,),
                                      kwargs={'poll_interval': 0.01}, daemon=True)
            thread.start()
            try:
                check_server(httpd, opened)
            finally:
                httpd.shutdown()
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())

        def immediate_timer(_delay, callback):
            timer = Mock()
            timer.start.side_effect = callback
            return timer

        argv = ['research-flow', '--project', str(self.path), '--open', *options]
        with patch('sys.argv', argv), \
             patch('sys.stdout', new_callable=io.StringIO) as output, \
             patch('sys.stderr', new_callable=io.StringIO) as errors, \
             patch('server.signal.signal'), \
             patch('server.webbrowser.open') as opened, \
             patch('server.threading.Timer', side_effect=immediate_timer), \
             patch.object(ThreadingHTTPServer, 'serve_forever', serve):
            server.main()
        return output.getvalue(), errors.getvalue()

    def request(self, port, path, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
        try:
            connection.request('GET', path, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_busy_default_skips_occupied_ports_and_opens_working_view(self):
        for explicit_default, forwarded in ((False, None), (True, None), (False, 18765)):
            with self.subTest(explicit_default=explicit_default, forwarded=forwarded), \
                 occupied_pair() as default, patch('server.DEFAULT_PORT', default):
                options = ['--port', str(default)] if explicit_default else []
                if forwarded:
                    options += ['--browser-port', str(forwarded)]

                def check(httpd, opened):
                    self.assertEqual(httpd.server_address, ('127.0.0.1', default + 2))
                    opened.assert_called_once()
                    url = urlsplit(opened.call_args.args[0])
                    browser_port = forwarded or default + 2
                    self.assertEqual(url.port, browser_port)
                    self.assertEqual(url.hostname, '127.0.0.1')
                    token = parse_qs(url.fragment)['token'][0]
                    self.assertEqual(token, server.access_token(server.default_token_path(self.path), create=False))
                    headers = {'Host': f'127.0.0.1:{browser_port}',
                               'Origin': f'http://127.0.0.1:{browser_port}'}
                    status, body = self.request(httpd.server_port, '/', headers)
                    self.assertEqual(status, 200)
                    self.assertIn(b'<html', body)
                    self.assertNotIn(token.encode(), body)
                    self.assertEqual(self.request(httpd.server_port, '/api/project', headers)[0], 401)
                    headers['X-Research-Flow-Token'] = token
                    status, body = self.request(httpd.server_port, '/api/project', headers)
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(body)['document']['tasks'], [])
                    headers['Host'] = f'127.0.0.1:{default}'
                    self.assertEqual(self.request(httpd.server_port, '/api/project', headers)[0], 403)

                output, errors = self.run_main(options, check)
                self.assertEqual(errors, f'Warning: default port {default} is already in use; '
                                        f'using port {default + 2} instead.\n')
                self.assertIn(f'listening on 127.0.0.1:{default + 2}', output)
                self.assertIn(f'forward port {forwarded or default + 2} to server port {default + 2}', output)

    def test_busy_custom_port_fails_without_opening_browser(self):
        with occupied_pair() as port, patch('server.DEFAULT_PORT', port + 2), \
             patch('sys.argv', ['research-flow', '--project', str(self.path), '--port', str(port), '--open']), \
             patch('sys.stderr', new_callable=io.StringIO) as errors, \
             patch('server.webbrowser.open') as opened:
            with self.assertRaises(SystemExit) as stopped:
                server.main()
            self.assertEqual(stopped.exception.code, 1)
            self.assertIn('Cannot start:', errors.getvalue())
            self.assertNotIn('Warning:', errors.getvalue())
            opened.assert_not_called()

    def test_port_zero_opens_os_assigned_port_without_warning(self):
        def check(httpd, opened):
            self.assertGreater(httpd.server_port, 0)
            opened.assert_called_once()
            self.assertEqual(urlsplit(opened.call_args.args[0]).port, httpd.server_port)
            self.assertEqual(self.request(httpd.server_port, '/')[0], 200)

        _, errors = self.run_main(['--port', '0'], check)
        self.assertEqual(errors, '')

    def test_free_default_does_not_warn(self):
        with occupied_pair() as port, patch('server.DEFAULT_PORT', port + 2):
            def check(httpd, opened):
                self.assertEqual(httpd.server_port, port + 2)
                self.assertEqual(urlsplit(opened.call_args.args[0]).port, port + 2)

            _, errors = self.run_main([], check)
            self.assertEqual(errors, '')

    def test_other_bind_errors_are_not_retried(self):
        denied = PermissionError(errno.EACCES, 'Permission denied')
        with patch('server.ThreadingHTTPServer', side_effect=denied) as listener:
            with self.assertRaises(PermissionError) as raised:
                server.bind_server(8765, object(), auto_port=True)
            self.assertIs(raised.exception, denied)
            listener.assert_called_once()

    def test_port_zero_does_not_retry_as_port_one(self):
        busy = OSError(errno.EADDRINUSE, 'Address already in use')
        with patch('server.ThreadingHTTPServer', side_effect=busy) as listener:
            with self.assertRaises(OSError):
                server.bind_server(0, object(), auto_port=True)
            listener.assert_called_once()

    def test_fallback_stops_at_maximum_port(self):
        busy = OSError(errno.EADDRINUSE, 'Address already in use')
        with patch('server.ThreadingHTTPServer', side_effect=busy) as listener:
            with self.assertRaises(OSError):
                server.bind_server(65534, object(), auto_port=True)
            self.assertEqual([call.args[0] for call in listener.call_args_list],
                             [('127.0.0.1', 65534), ('127.0.0.1', 65535)])


if __name__ == '__main__':
    unittest.main()
