"""Explicit PostgreSQL acceptance: reply/retirement serialization both orders."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
from unittest.mock import patch

from django.db import connection
from tests.mfa_helpers import TransactionTestCase, override_settings
from concurrency.races import PostgreSQLRaces
from membership import views as membership_views
from support import views
from support.models import Ticket, TicketAudit, TicketReply


@override_settings(SECURE_SSL_REDIRECT=False, AUTH_ATTEMPT_LIMIT=1000)
class ReplyRaces(TransactionTestCase):
    setUp = PostgreSQLRaces.setUp
    member = PostgreSQLRaces.member
    browser = PostgreSQLRaces.browser
    request = PostgreSQLRaces.request

    def assert_blocked(self, name, future):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not future.done():
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_stat_clear_snapshot()')
                cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE application_name = %s AND cardinality(pg_blocking_pids(pid)) > 0)", [name])
                if cursor.fetchone()[0]:
                    return
            time.sleep(0.02)
        self.fail(f'{name} did not wait on the policy lock')

    def test_retirement_waits_for_reply_commit(self):
        ticket = Ticket.objects.create(tenant=self.tenant, author=self.actor.user, title='Help', body='Question')
        browser, root_browser = self.browser(self.actor.user), self.browser(self.root)
        authorized, release = Event(), Event()
        original = views.actor_membership

        def pause(request, **kwargs):
            member = original(request, **kwargs)
            authorized.set()
            if not release.wait(8):
                raise AssertionError('Reply race timed out')
            return member

        with patch.object(views, 'actor_membership', side_effect=pause), ThreadPoolExecutor(max_workers=2) as pool:
            creation = pool.submit(self.request, browser, f'/support/{ticket.pk}/replies/', 'reply-create', body='Answer')
            try:
                self.assertTrue(authorized.wait(5))
                retirement = pool.submit(self.request, root_browser, f'/manage/{self.actor.pk}/revoke/', 'reply-retire')
                self.assert_blocked('reply-retire', retirement)
            finally:
                release.set()
            self.assertEqual(creation.result(timeout=10), 302)
            self.assertEqual(retirement.result(timeout=10), 302)
        self.assertEqual(TicketReply.objects.count(), 1)
        self.assertEqual(TicketAudit.objects.filter(action='replied').count(), 1)
        browser.post(f'/support/{ticket.pk}/replies/', {'body': 'After'})
        self.assertEqual(TicketReply.objects.count(), 1)

    def test_queued_reply_refreshes_actor_after_retirement(self):
        ticket = Ticket.objects.create(tenant=self.tenant, author=self.actor.user, title='Help', body='Question')
        browser, root_browser = self.browser(self.actor.user), self.browser(self.root)
        authorized, release = Event(), Event()
        original = membership_views.managed_members

        def pause(user):
            result = original(user)
            authorized.set()
            if not release.wait(8):
                raise AssertionError('Retirement race timed out')
            return result

        with patch.object(membership_views, 'managed_members', side_effect=pause), ThreadPoolExecutor(max_workers=2) as pool:
            retirement = pool.submit(self.request, root_browser, f'/manage/{self.actor.pk}/revoke/', 'retire-first')
            try:
                self.assertTrue(authorized.wait(5))
                creation = pool.submit(self.request, browser, f'/support/{ticket.pk}/replies/', 'queued-reply', body='Answer')
                self.assert_blocked('queued-reply', creation)
            finally:
                release.set()
            self.assertEqual(retirement.result(timeout=10), 302)
            self.assertEqual(creation.result(timeout=10), 403)
        self.assertFalse(TicketReply.objects.exists())
        self.assertFalse(TicketAudit.objects.exists())
