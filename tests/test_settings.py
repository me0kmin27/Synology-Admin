import os
import subprocess
import sys
from tests.mfa_helpers import SimpleTestCase


class SettingsTests(SimpleTestCase):
    def proxy_settings(self, **values):
        env = {**os.environ, 'DJANGO_ALLOWED_HOSTS': 'localhost,Test.keiminem.com',
               'DJANGO_CSRF_TRUSTED_ORIGINS': 'https://Test.keiminem.com',
               'DJANGO_TRUSTED_PROXY_IPS': '192.168.1.142', **values}
        return subprocess.run([sys.executable, '-c',
            'import json; from config import settings as s; print(json.dumps([s.ALLOWED_HOSTS, s.CSRF_TRUSTED_ORIGINS, s.TRUSTED_PROXY_NETWORKS]))'],
            env=env, capture_output=True, text=True)

    def test_runtime_proxy_configuration(self):
        import json
        result = self.proxy_settings()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [['localhost', 'test.keiminem.com'], ['https://test.keiminem.com'], ['192.168.1.142/32']])
        result = self.proxy_settings(DJANGO_TRUSTED_PROXY_IPS='', DJANGO_CSRF_TRUSTED_ORIGINS='')
        self.assertEqual(json.loads(result.stdout)[1:], [[], []])

    def test_config_updates_exact_domain_port_and_cidr_without_build(self):
        import json
        result = self.proxy_settings(DJANGO_ALLOWED_HOSTS='Next.example.com,[::1]',
            DJANGO_CSRF_TRUSTED_ORIGINS='https://Next.example.com:8443,https://[::1]:443',
            DJANGO_TRUSTED_PROXY_IPS='192.168.2.0/24,2001:db8::/64')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [['next.example.com', '[::1]'],
            ['https://next.example.com:8443', 'https://[::1]:443'], ['192.168.2.0/24', '2001:db8::/64']])

    def test_unsafe_proxy_configuration_rejected(self):
        for key, values in {
            'DJANGO_ALLOWED_HOSTS': ['*', '.example.com', 'https://example.com', 'example.com:443', 'a,,b'],
            'DJANGO_CSRF_TRUSTED_ORIGINS': ['https://*.example.com', 'http://test.keiminem.com', 'https://test.keiminem.com/path', 'https://user@test.keiminem.com', 'https://evil.invalid', 'https://@test.keiminem.com', 'https://test.keiminem.com:', 'https://test.keiminem.com?', 'https://test.keiminem.com#'],
            'DJANGO_TRUSTED_PROXY_IPS': ['*', '0.0.0.0/0', '::/0', '192.168.1.142/24', 'proxy.local', '192.168.1.142,'],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.assertNotEqual(self.proxy_settings(**{key: value}).returncode, 0)

    def test_missing_secret_is_rejected(self):
        env = {key: value for key, value in os.environ.items() if key != "DJANGO_SECRET_KEY"}
        result = subprocess.run([sys.executable, "-c", "import config.settings"], env=env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_production_security_defaults(self):
        env = {key: value for key, value in os.environ.items() if key != "DJANGO_LOCAL_HTTP"}
        result = subprocess.run([sys.executable, "-c", "from config import settings as s; assert not s.DEBUG; assert s.SECURE_SSL_REDIRECT; assert s.SESSION_COOKIE_SECURE; assert s.CSRF_COOKIE_SECURE; assert s.SECURE_HSTS_SECONDS > 0"], env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_weak_secret_is_rejected(self):
        result = subprocess.run(
            [sys.executable, "-c", "import config.settings"],
            env={**os.environ, "DJANGO_SECRET_KEY": "short"},
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY must contain at least 50 characters", result.stderr)
