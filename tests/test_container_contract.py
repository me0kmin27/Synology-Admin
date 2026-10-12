"""Offline guardrails for the internal-only container definition."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ContainerContractTests(unittest.TestCase):
    def test_loopback_default_explicit_lan_opt_in_and_bounded_services(self):
        path = ROOT / 'compose.internal.json'
        self.assertTrue(path.exists(), 'Internal compose definition must exist')
        config = json.loads(path.read_text())
        web, db = config['services']['web'], config['services']['db']
        self.assertEqual(web['ports'], ['${INTERNAL_BIND_HOST:-127.0.0.1}:18080:8000'])
        self.assertEqual(web['environment']['DJANGO_ALLOWED_HOSTS'],
                         'localhost,127.0.0.1,${INTERNAL_BIND_HOST:-127.0.0.1}')
        self.assertNotIn('ports', db)
        self.assertTrue(config['networks']['default']['internal'])
        self.assertEqual(db.get('networks', ['default']), ['default'])
        self.assertIn('frontend', web.get('networks', []))
        self.assertFalse(config['networks'].get('frontend', {}).get('internal', False))
        self.assertTrue(web['read_only'])
        self.assertEqual(web['cap_drop'], ['ALL'])
        self.assertEqual(web['environment']['DJANGO_LOCAL_HTTP'], '1')
        for service in (web, db):
            self.assertIn('mem_limit', service)
            self.assertIn('cpus', service)
            self.assertIn('pids_limit', service)
            self.assertIn('healthcheck', service)
        self.assertEqual(db['volumes'], ['postgres_data:/var/lib/postgresql/data'])
        self.assertEqual(web['environment']['DJANGO_DB_ENGINE'], 'postgresql')
        self.assertNotIn('DJANGO_ALLOW_UNSAFE_SQLITE', web['environment'])

    def test_proxy_overlay_requires_explicit_hosts_and_trust(self):
        path = ROOT / 'compose.proxy.json'
        self.assertTrue(path.exists(), 'Proxy overlay required')
        environment = json.loads(path.read_text())['services']['web']['environment']
        self.assertEqual(environment['DJANGO_ALLOWED_HOSTS'], '${DJANGO_ALLOWED_HOSTS:?Set exact allowed hosts}')
        self.assertEqual(environment['DJANGO_CSRF_TRUSTED_ORIGINS'], '${DJANGO_CSRF_TRUSTED_ORIGINS:-}')
        self.assertEqual(environment['DJANGO_TRUSTED_PROXY_IPS'], '${DJANGO_TRUSTED_PROXY_IPS:-}')
        self.assertEqual(environment['DJANGO_LOCAL_HTTP'], '${DJANGO_LOCAL_HTTP:-0}')

    def test_secret_creation_is_private_and_never_overwrites(self):
        import subprocess
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            command = [sys.executable, str(ROOT / 'deploy/init-secrets.py')]
            first = subprocess.run(command, cwd=directory, capture_output=True)
            self.assertEqual(first.returncode, 0)
            self.assertTrue(path.exists(), 'Secret initializer must create .env')
            original = path.read_bytes()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            values = dict(line.split('=', 1) for line in original.decode().splitlines())
            self.assertGreaterEqual(len(values['DJANGO_SECRET_KEY']), 64)
            self.assertGreaterEqual(len(values['POSTGRES_PASSWORD']), 48)
            second = subprocess.run(command, cwd=directory, capture_output=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(path.read_bytes(), original)
            for value in values.values():
                self.assertNotIn(value.encode(), first.stdout + first.stderr + second.stdout + second.stderr)

    def test_mfa_key_is_independent_private_and_not_overwritten(self):
        import base64
        import subprocess
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            script = ROOT / 'deploy/init-mfa-key.py'
            self.assertTrue(script.exists(), 'Independent MFA key initializer required')
            command = [sys.executable, str(script)]
            first = subprocess.run(command, cwd=directory, capture_output=True)
            self.assertEqual(first.returncode, 0)
            path = Path(directory) / '.mfa.env'
            original = path.read_bytes()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            value = original.decode().strip().split('=', 1)[1]
            self.assertEqual(len(base64.urlsafe_b64decode(value)), 32)
            second = subprocess.run(command, cwd=directory, capture_output=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(path.read_bytes(), original)
            self.assertNotIn(value.encode(), first.stdout + first.stderr + second.stdout + second.stderr)
        config = json.loads((ROOT / 'compose.internal.json').read_text())
        self.assertIn('MFA_ENCRYPTION_KEYS', config['services']['web']['environment'])

    def test_image_runs_unprivileged_and_distrusts_proxy_headers(self):
        path = ROOT / 'Dockerfile'
        self.assertTrue(path.exists(), 'Container image definition must exist')
        image = path.read_text()
        self.assertIn('USER 10001:10001', image)
        self.assertIn('python:3.14-slim', image)
        config = ROOT / 'deploy/gunicorn.conf.py'
        self.assertTrue(config.exists())
        namespace = {}
        exec(compile(config.read_text(), str(config), 'exec'), namespace)
        self.assertEqual(namespace['forwarded_allow_ips'], '')
        self.assertEqual(namespace['secure_scheme_headers'], {})
        self.assertEqual(namespace.get('forwarder_headers'), '')
        self.assertEqual(namespace.get('proxy_protocol'), 'off')
        self.assertEqual(namespace['bind'], '0.0.0.0:8000')
        self.assertTrue(namespace.get('control_socket_disable', False))
