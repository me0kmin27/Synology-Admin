"""Explicit PG policy races; pg_blocking_pids evidence, never backend skips."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
from django.contrib.auth.models import User
from django.db import connection, connections
from django.test import Client, RequestFactory
from django_otp.oath import TOTP
from tests.mfa_helpers import TransactionTestCase, fixture_device, override_settings
from concurrency.races import PostgreSQLRaces
from concurrency.reply_races import ReplyRaces
from membership.models import AdminMFAPolicy, MFAPolicyAudit, Membership, Tenant, AuditEvent
from membership import views
from membership.locking import policy_transaction


@override_settings(SECURE_SSL_REDIRECT=False, AUTH_ATTEMPT_LIMIT=1000)
class OptionalPolicyRaces(TransactionTestCase):
    password = 'Disposable-policy-race-password-823!'
    assert_blocked = ReplyRaces.assert_blocked
    simultaneous = PostgreSQLRaces.simultaneous
    request = PostgreSQLRaces.request

    def setUp(self):
        self.assertEqual(connection.vendor, 'postgresql', 'Policy races require real PostgreSQL, not a skip')
        AdminMFAPolicy.objects.filter(pk=1).update(required=False)
        self.clock = patch('django_otp.oath.time', return_value=2000000010)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.owner = User.objects.create_superuser('policy-owner', password=self.password)
        self.owner_browser = Client()
        self.owner_browser.force_login(self.owner)
        self.device = fixture_device(self.owner)
        # Confirm the preceding step, leaving the current step fresh for toggle.
        with patch('django_otp.oath.time', return_value=1999999980):
            token = f'{TOTP(self.device.bin_key).token():06d}'
            self.assertEqual(self.owner_browser.post('/mfa/verify/', {'token': token}).status_code, 302)
        self.actor = User.objects.create_superuser('unenrolled-admin', password=self.password)
        self.actor_browser = Client()
        self.actor_browser.force_login(self.actor)
        tenant = Tenant.objects.create(name='policy-race', max_accounts=10)
        self.subject = Membership.objects.create(user=User.objects.create_user('pending'), tenant=tenant)

    def toggle_data(self):
        return {'password': self.password, 'required': 'on', 'token': f'{TOTP(self.device.bin_key).token():06d}'}

    def call(self, name, operation):
        try:
            with connection.cursor() as cursor:
                cursor.execute('SET application_name = %s', [name])
                cursor.execute("SET statement_timeout = '10s'")
            return operation().status_code
        finally:
            connections.close_all()

    def stale_mutation(self):
        request = RequestFactory().post(f'/manage/{self.subject.pk}/approve/', {'password': self.password})
        request.user = self.actor
        request.session = self.actor_browser.session
        dict(request.session)
        return request

    def test_toggle_commit_precedes_queued_session_and_inner_mutation(self):
        cached = self.stale_mutation()
        entered, release = Event(), Event()
        original = MFAPolicyAudit.objects.create

        def pause_audit(**kwargs):
            result = original(**kwargs)
            entered.set()
            if not release.wait(8):
                raise AssertionError('Policy audit pause timed out')
            return result

        data = self.toggle_data()
        with patch.object(MFAPolicyAudit.objects, 'create', side_effect=pause_audit), ThreadPoolExecutor(max_workers=3) as pool:
            toggle = pool.submit(self.call, 'policy-toggle-first', lambda: self.owner_browser.post('/manage/mfa-policy/', data))
            try:
                self.assertTrue(entered.wait(5))
                read = pool.submit(self.call, 'policy-read-waiter', lambda: self.actor_browser.get('/manage/'))
                mutation = pool.submit(self.call, 'policy-inner-waiter', lambda: views.approve(cached, self.subject.pk))
                self.assert_blocked('policy-read-waiter', read)
                self.assert_blocked('policy-inner-waiter', mutation)
            finally:
                release.set()
            self.assertEqual(toggle.result(timeout=10), 302)
            self.assertEqual(read.result(timeout=10), 302)
            self.assertEqual(mutation.result(timeout=10), 403)
        self.subject.refresh_from_db()
        self.assertEqual(self.subject.status, 'pending')
        self.assertFalse(AuditEvent.objects.exists())
        self.assertEqual(MFAPolicyAudit.objects.count(), 1)
        self.assertEqual(AdminMFAPolicy.objects.get(pk=1).version, 2)
        print('POLICY PG: toggle-first blocked session AND cached inner mutation via pg_blocking_pids; stale denied')

    def assert_toggle_waits_for_operation(self, mutation):
        entered, release = Event(), Event()
        original = views.managed_members

        def pause(user):
            result = original(user)
            if user.pk == self.actor.pk:
                entered.set()
                if not release.wait(8):
                    raise AssertionError('Authorized operation pause timed out')
            return result

        cached = self.stale_mutation()
        data = self.toggle_data()
        operation = (lambda: views.approve(cached, self.subject.pk)) if mutation else (lambda: self.actor_browser.get('/manage/'))
        with patch.object(views, 'managed_members', side_effect=pause), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.call, 'policy-operation-first', operation)
            try:
                self.assertTrue(entered.wait(5))
                toggle = pool.submit(self.call, 'policy-toggle-waiter', lambda: self.owner_browser.post('/manage/mfa-policy/', data))
                self.assert_blocked('policy-toggle-waiter', toggle)
            finally:
                release.set()
            self.assertEqual(first.result(timeout=10), 302 if mutation else 200)
            self.assertEqual(toggle.result(timeout=10), 302)
        self.assertEqual(AuditEvent.objects.count(), 1 if mutation else 0)
        self.assertEqual(MFAPolicyAudit.objects.count(), 1)
        self.assertEqual(self.actor_browser.get('/manage/').url, '/mfa/enroll/')
        print(f'POLICY PG: toggle waited for {"mutation commit" if mutation else "session read"}; pg_blocking_pids overlap')

    def test_toggle_waits_for_authorized_read(self):
        self.assert_toggle_waits_for_operation(False)

    def test_toggle_waits_for_inner_mutation_commit(self):
        self.assert_toggle_waits_for_operation(True)

    def test_concurrent_toggles_have_one_version_and_audit_winner(self):
        other_user = User.objects.create_superuser('second-policy-owner', password=self.password)
        other = Client()
        other.force_login(other_user)
        other_device = fixture_device(other_user)
        with patch('django_otp.oath.time', return_value=1999999980):
            self.assertEqual(other.post('/mfa/verify/', {'token': f'{TOTP(other_device.bin_key).token():06d}'}).status_code, 302)
        other_data = {**self.toggle_data(), 'token': f'{TOTP(other_device.bin_key).token():06d}'}
        results = self.simultaneous([
            (self.owner_browser, '/manage/mfa-policy/', self.toggle_data()),
            (other, '/manage/mfa-policy/', other_data),
        ])
        self.assertEqual(sorted(results), [302, 403])
        self.assertEqual(AdminMFAPolicy.objects.get(pk=1).version, 2)
        self.assertEqual(MFAPolicyAudit.objects.count(), 1)
        print('POLICY PG: concurrent toggles overlapped via pg_blocking_pids; one version/audit winner')
