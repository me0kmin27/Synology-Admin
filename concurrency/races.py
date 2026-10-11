"""Real PostgreSQL transactions; explicit CI label, never skipped on SQLite."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connection, connections
from django.test import Client, TransactionTestCase, override_settings

from membership.models import AuditEvent, Membership, Tenant
from membership import views

PASSWORD = 'Race-test-passphrase-739!'


@override_settings(SECURE_SSL_REDIRECT=False, AUTH_ATTEMPT_LIMIT=1000)
class PostgreSQLRaces(TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor, 'postgresql', 'Race acceptance requires PostgreSQL, not SQLite/skip')
        self.tenant = Tenant.objects.create(name='Race customer', max_accounts=100)
        self.root = User.objects.create_superuser('root', password=PASSWORD)
        self.actor = self.member('actor', role='admin', status='approved')
        self.member('backup', role='admin', status='approved')

    def member(self, name, **fields):
        return Membership.objects.create(user=User.objects.create_user(name, password=PASSWORD), tenant=self.tenant, **fields)

    def browser(self, user):
        browser = Client()
        browser.force_login(user)
        return browser

    def request(self, browser, path, name, **data):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET application_name = %s", [name])
                cursor.execute("SET statement_timeout = '10s'")
            return browser.post(path, {'password': PASSWORD, **data}).status_code
        finally:
            connections.close_all()

    def simultaneous(self, requests):
        from django.db import transaction
        from membership.locking import POLICY_LOCK_ID
        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_advisory_xact_lock(%s)', [POLICY_LOCK_ID])
                futures = [pool.submit(self.request, browser, path, f'queued-race-{i}', **data)
                           for i, (browser, path, data) in enumerate(requests)]
                deadline = time.monotonic() + 5
                blocked = 0
                while time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT pg_stat_clear_snapshot()')
                        cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name LIKE 'queued-race-%%' AND cardinality(pg_blocking_pids(pid)) > 0")
                        blocked = cursor.fetchone()[0]
                    if blocked == len(requests):
                        break
                    time.sleep(0.02)
                self.assertEqual(blocked, len(requests), 'Workers did not contend on the real PostgreSQL policy lock')
            return [future.result(timeout=10) for future in futures]

    def test_last_account_slot_has_one_winner(self):
        self.tenant.max_accounts = 3  # two active managers plus one remaining slot
        self.tenant.save()
        subjects = [self.member('first'), self.member('second')]
        requests = [(self.browser(self.actor.user), f'/manage/{subject.pk}/approve/', {}) for subject in subjects]
        self.assertEqual(sorted(self.simultaneous(requests)), [302, 409])
        self.assertEqual(Membership.objects.filter(tenant=self.tenant, status='approved', user__is_active=True).count(), 3)
        self.assertEqual(AuditEvent.objects.filter(action='approve').count(), 1)

    def test_mutual_retirement_retains_one_active_manager(self):
        backup = Membership.objects.get(user__username='backup')
        requests = [(self.browser(self.actor.user), f'/manage/{backup.pk}/revoke/', {}),
                    (self.browser(backup.user), f'/manage/{self.actor.pk}/revoke/', {})]
        self.assertEqual(sorted(self.simultaneous(requests)), [302, 403])
        self.assertEqual(Membership.objects.filter(tenant=self.tenant, role='admin', status='approved', user__is_active=True).count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action='revoke').count(), 1)

    def test_concurrent_manager_demotions_retain_one_manager(self):
        backup = Membership.objects.get(user__username='backup')
        requests = [(self.browser(self.root), f'/manage/{subject.pk}/role/', {'role': 'member'})
                    for subject in (self.actor, backup)]
        self.assertEqual(sorted(self.simultaneous(requests)), [302, 409])
        self.assertEqual(Membership.objects.filter(tenant=self.tenant, role='admin', status='approved').count(), 1)

    def test_concurrent_quota_allocation_does_not_oversubscribe(self):
        self.tenant.storage_limit_bytes = 100
        self.tenant.save()
        subjects = [self.member('first', status='approved'), self.member('second', status='approved')]
        requests = [(self.browser(self.actor.user), f'/manage/{subject.pk}/quota/', {'quota_bytes': '60'}) for subject in subjects]
        self.assertEqual(sorted(self.simultaneous(requests)), [302, 409])
        from membership.groups import allocated_bytes
        self.assertEqual(allocated_bytes(self.tenant), 60)

    def test_reduction_and_approval_preserve_account_cap(self):
        self.tenant.max_accounts = 3
        self.tenant.save()
        subject = self.member('applicant')
        requests = [(self.browser(self.actor.user), f'/manage/{subject.pk}/approve/', {}),
                    (self.browser(self.root), f'/manage/groups/{self.tenant.pk}/limits/', {'max_accounts': '2', 'storage_limit_bytes': '0'})]
        self.assertEqual(sorted(self.simultaneous(requests)), [302, 409])
        self.tenant.refresh_from_db()
        self.assertLessEqual(Membership.objects.filter(tenant=self.tenant, status='approved', user__is_active=True).count(), self.tenant.max_accounts)

    def test_concurrent_login_cannot_recreate_authenticated_retired_session(self):
        from django.contrib.auth.backends import ModelBackend
        subject = self.member('logging-in', status='approved')
        browser, root_browser = Client(), self.browser(self.root)
        authenticated, release = Event(), Event()
        original = ModelBackend.authenticate

        def pause_after_password(backend, request, **credentials):
            user = original(backend, request, **credentials)
            if user and user.pk == subject.user_id:
                authenticated.set()
                if not release.wait(8):
                    raise AssertionError('Login race timed out')
            return user

        with patch.object(ModelBackend, 'authenticate', pause_after_password), ThreadPoolExecutor(max_workers=1) as pool:
            login = pool.submit(self.request, browser, '/login/', 'race-login', username='logging-in')
            try:
                self.assertTrue(authenticated.wait(5))
                self.assertEqual(root_browser.post(f'/manage/{subject.pk}/revoke/', {'password': PASSWORD}).status_code, 302)
            finally:
                release.set()
            self.assertEqual(login.result(timeout=10), 302)
        self.assertNotIn('_auth_user_id', browser.session)
        self.assertEqual(browser.get('/service/').status_code, 302)

    def test_actor_revocation_waits_for_inflight_authorized_write(self):
        subject = self.member('applicant')
        actor_browser, root_browser = self.browser(self.actor.user), self.browser(self.root)
        authorized, release = Event(), Event()
        original = views.managed_members

        def pause_after_authorization(user):
            result = original(user)
            if user.pk == self.actor.user_id:
                authorized.set()
                if not release.wait(8):
                    raise AssertionError('Race synchronization timed out')
            return result

        with patch.object(views, 'managed_members', side_effect=pause_after_authorization), ThreadPoolExecutor(max_workers=2) as pool:
            approval = pool.submit(self.request, actor_browser, f'/manage/{subject.pk}/approve/', 'race-approver')
            revocation = None
            try:
                self.assertTrue(authorized.wait(5))
                revocation = pool.submit(self.request, root_browser, f'/manage/{self.actor.pk}/revoke/', 'race-revoker')
                deadline = time.monotonic() + 5
                blocked = False
                while time.monotonic() < deadline and not revocation.done():
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE application_name = %s AND cardinality(pg_blocking_pids(pid)) > 0)", ['race-revoker'])
                        blocked = cursor.fetchone()[0]
                    if blocked:
                        break
                    time.sleep(0.02)
                self.assertTrue(blocked, 'Revocation committed while an already-authorized actor write remained in flight')
            finally:
                release.set()
            self.assertEqual(approval.result(timeout=10), 302)
            self.assertIsNotNone(revocation)
            self.assertEqual(revocation.result(timeout=10), 302)
        self.actor.refresh_from_db()
        self.assertEqual(self.actor.status, 'suspended')
        another = self.member('after-revocation')
        self.assertEqual(actor_browser.post(f'/manage/{another.pk}/approve/', {'password': PASSWORD}).status_code, 302)
        self.assertFalse(AuditEvent.objects.filter(subject=another).exists())
