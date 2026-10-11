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
