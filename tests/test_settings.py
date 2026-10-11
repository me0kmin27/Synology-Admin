import os
import subprocess
import sys
from tests.mfa_helpers import SimpleTestCase


class SettingsTests(SimpleTestCase):
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
