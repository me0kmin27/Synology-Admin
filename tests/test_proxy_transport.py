"""Real TCP -> pinned Gunicorn -> Django (not RequestFactory peer claims)."""
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProxyTransportTests(unittest.TestCase):
    def test_real_gunicorn_trust_and_header_ambiguity(self):
        # 127.0.0.1 is trusted ONLY by the first disposable child, not deployment.
        for trusted, expected in [('127.0.0.1', 200), ('192.168.1.142', 301), ('', 301)]:
            with self.subTest(trusted=trusted), socket.socket() as listener, tempfile.TemporaryFile() as logs:
                listener.bind(('127.0.0.1', 0))
                listener.listen()
                port = listener.getsockname()[1]
                env = {**os.environ, 'DJANGO_SECRET_KEY': secrets.token_urlsafe(64),
                       'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_LOCAL_HTTP': '0',
                       'DJANGO_ALLOWED_HOSTS': 'test.keiminem.com',
                       'DJANGO_CSRF_TRUSTED_ORIGINS': 'https://Test.keiminem.com',
                       'DJANGO_TRUSTED_PROXY_IPS': trusted}
                env.pop('GUNICORN_CMD_ARGS', None)
                process = subprocess.Popen([sys.executable, '-m', 'gunicorn', '--config',
                    'deploy/gunicorn.conf.py', '--workers', '1', '--bind', f'fd://{listener.fileno()}',
                    'config.wsgi:application'], cwd=ROOT, env=env,
                    pass_fds=(listener.fileno(),), stdout=logs, stderr=logs)
                try:
                    deadline = time.monotonic() + 15
                    while True:
                        try:
                            response = self.request(port, 'X-Forwarded-Proto: https\r\n')
                            break
                        except (OSError, TimeoutError):
                            if process.poll() is not None or time.monotonic() > deadline:
                                logs.seek(0)
                                self.fail('Gunicorn failed to become ready: ' + logs.read().decode())
                            time.sleep(0.05)
                    self.assertEqual(self.status(response), expected)
                    if expected == 200:
                        self.assertIn(b'; Secure', response)
                    for headers in ['X-Forwarded-Proto: https,http\r\n',
                                    'X-Forwarded-Proto: https\r\nX-Forwarded-Proto: https\r\n',
                                    'X-Forwarded-Proto: https\r\nX-Forwarded-For: 1.2.3.4,5.6.7.8\r\n']:
                        self.assertEqual(self.status(self.request(port, headers)), 400 if expected == 200 else 301)
                    self.assertEqual(self.status(self.request(port, 'X_Forwarded_Proto: https\r\n')), 301)
                    self.assertEqual(self.status(self.request(port, 'X-Forwarded-Proto: https\r\n', host='evil.invalid')), 400)
                    self.assertEqual(self.status(self.request(port, 'X-Forwarded-Host: test.keiminem.com\r\n', host='evil.invalid')), 400)
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)

    def request(self, port, headers, host='Test.keiminem.com:443'):
        with socket.create_connection(('127.0.0.1', port), timeout=2) as connection:
            connection.sendall((f'GET /login/ HTTP/1.1\r\nHost: {host}\r\n{headers}Connection: close\r\n\r\n').encode())
            chunks = []
            while chunk := connection.recv(65536):
                chunks.append(chunk)
            return b''.join(chunks)

    def status(self, response):
        return int(response.split(b' ', 2)[1])
