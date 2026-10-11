"""Independent security regressions; disposable users and no external services."""
from unittest.mock import patch

from django.contrib.auth.models import User
from tests.mfa_helpers import Client, RequestFactory, TestCase, override_settings
from django.views.debug import SafeExceptionReporterFilter


@override_settings(SECURE_SSL_REDIRECT=False, DEBUG=False)
class ErrorReportPrivacyTests(TestCase):
    def test_custom_auth_views_redact_post_data_from_error_reports(self):
        from membership import views, groups
        user = User.objects.create_user('review-user')
        for view in [views.signup, views.approve, views.revoke, views.assign, views.link, groups.limits, groups.role, groups.quota]:
            with self.subTest(view=view.__name__):
                request = RequestFactory().post('/', {
                    'password': 'synthetic-sensitive-value',
                    'password1': 'synthetic-sensitive-value',
                    'password2': 'synthetic-sensitive-value',
                    'external_id': 'synthetic-private-identifier',
                })
                request.user = user
                view(request) if view is views.signup else view(request, pk=1)
                values = SafeExceptionReporterFilter().get_post_parameters(request)
                self.assertTrue(all(value == '********************' for value in values.values()))


@override_settings(SECURE_SSL_REDIRECT=False, AUTH_ATTEMPT_LIMIT=2)
class ThrottleIdentityTests(TestCase):
    @patch('membership.throttle.time.time', return_value=1800000000)
    def test_logged_in_clients_cannot_change_login_target_bucket(self, clock):
        for index in range(3):
            browser = Client()
            browser.force_login(User.objects.create_user(f'attacker-{index}'))
            response = browser.post('/login/', {'username': 'target', 'password': 'wrong'}, REMOTE_ADDR=f'192.0.2.{index + 1}')
            self.assertEqual(response.status_code, 429 if index == 2 else 200)

    @patch('membership.throttle.time.time', return_value=1800000000)
    def test_nfkc_equivalent_login_names_share_target_limit(self, clock):
        User.objects.create_user('Alice', password='Review-only-passphrase-829!')
        for index, username in enumerate(['Alice', 'Ａlice']):
            response = Client().post('/login/', {'username': username, 'password': 'wrong'}, REMOTE_ADDR=f'192.0.2.{index + 1}')
            self.assertEqual(response.status_code, 200)
        response = Client().post('/login/', {'username': 'Alice', 'password': 'wrong'}, REMOTE_ADDR='192.0.2.3')
        self.assertEqual(response.status_code, 429)
