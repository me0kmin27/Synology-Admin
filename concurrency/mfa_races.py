"""Explicit PostgreSQL MFA acceptance: no SQLite skip, real lock contention."""
from django.contrib.auth.models import User
from django.db import connection
from django.test import Client as PasswordOnlyClient
from tests.mfa_helpers import TransactionTestCase, fixture_device, override_settings
from concurrency.races import PostgreSQLRaces
from django_otp.oath import TOTP


@override_settings(SECURE_SSL_REDIRECT=False, AUTH_ATTEMPT_LIMIT=1000)
class MFARaces(TransactionTestCase):
    request = PostgreSQLRaces.request
    simultaneous = PostgreSQLRaces.simultaneous

    def setUp(self):
        self.assertEqual(connection.vendor, 'postgresql', 'MFA races require PostgreSQL')
        self.user = User.objects.create_superuser('race-otp', password='Disposable-race-password-827!')
        self.device = fixture_device(self.user)
        self.browsers = [PasswordOnlyClient(), PasswordOnlyClient()]
        for browser in self.browsers:
            browser.force_login(self.user)

    def test_concurrent_replay_has_one_winner_and_committed_failure(self):
        token = f'{TOTP(self.device.bin_key).token():06d}'
        results = self.simultaneous([(browser, '/mfa/verify/', {'token': token}) for browser in self.browsers])
        self.assertEqual(sorted(results), [302, 403])
        self.device.refresh_from_db()
        self.assertEqual(self.device.throttling_failure_count, 1)
        self.assertEqual(sum('mfa_device' in browser.session for browser in self.browsers), 1)
        self.assertEqual(self.browsers[0].post('/mfa/verify/', {'token': token}).status_code, 429)
        print('MFA PostgreSQL: pg_blocking_pids proved overlap; single OTP winner; failure committed')

    def test_concurrent_enrollment_is_one_device(self):
        self.device.delete()
        results = self.simultaneous([(browser, '/mfa/enroll/', {'password': 'Disposable-race-password-827!'}) for browser in self.browsers])
        self.assertEqual(sorted(results), [200, 409])
        from membership.models import AdminOTPDevice
        self.assertEqual(AdminOTPDevice.objects.filter(user=self.user).count(), 1)
