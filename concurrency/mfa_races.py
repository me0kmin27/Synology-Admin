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

    def test_queued_verified_request_rechecks_device_and_global_role(self):
        from concurrent.futures import ThreadPoolExecutor
        from tests.mfa_helpers import Client
        from membership.locking import policy_transaction
        from concurrency.reply_races import ReplyRaces
        for mutation in ('device', 'role'):
            with self.subTest(mutation=mutation):
                self.user.refresh_from_db()
                browser = Client()
                browser.force_login(self.user)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    with policy_transaction():
                        future = pool.submit(self.request, browser, '/manage/1/approve/', 'mfa-revoked-waiter')
                        ReplyRaces.assert_blocked(self, 'mfa-revoked-waiter', future)
                        if mutation == 'device':
                            from membership.models import AdminOTPDevice
                            AdminOTPDevice.objects.filter(user=self.user).delete()
                        else:
                            User.objects.filter(pk=self.user.pk).update(is_superuser=False)
                    self.assertEqual(future.result(timeout=10), 403)
                self.assertNotIn('_auth_user_id', browser.session)
        print('MFA PostgreSQL: queued request denied after device deletion/global role change, session flushed')

    def test_concurrent_enrollment_is_one_device(self):
        self.device.delete()
        results = self.simultaneous([(browser, '/mfa/enroll/', {'password': 'Disposable-race-password-827!'}) for browser in self.browsers])
        self.assertEqual(sorted(results), [200, 409])
        from membership.models import AdminOTPDevice
        self.assertEqual(AdminOTPDevice.objects.filter(user=self.user).count(), 1)
