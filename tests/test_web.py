from django.test import TestCase, override_settings


@override_settings(SECURE_SSL_REDIRECT=False)
class WebTests(TestCase):
    def test_untrusted_host_is_rejected(self):
        self.assertEqual(self.client.get("/", HTTP_HOST="untrusted.invalid").status_code, 400)

    def test_security_headers(self):
        response = self.client.get("/")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_http_redirects_to_https(self):
        self.assertEqual(self.client.get("/").status_code, 301)

    def test_no_public_admin_or_nas_routes(self):
        for path in ("/admin/", "/api/nas/"):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_landing_is_truthful(self):
        response = self.client.get("/")
        self.assertContains(response, "Synology-Admin")
        self.assertContains(response, "NAS 연결 안 됨")
        self.assertContains(response, "NAS 용량·지원 기능은 아직 제공하지 않습니다")

    def test_database_failure_is_sanitized(self):
        from unittest.mock import patch
        from django.db import OperationalError
        self.client.raise_request_exception = False
        with patch("config.views.connection.cursor", side_effect=OperationalError("private-detail")):
            response = self.client.get("/health/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable", "database": "unavailable", "nas": "not_configured"})
        self.assertNotContains(response, "private-detail", status_code=503)

    def test_health_is_not_cacheable(self):
        response = self.client.get("/health/")
        self.assertIn("no-store", response.get("Cache-Control", ""))

    def test_health_checks_real_database(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok", "nas": "not_configured"})
