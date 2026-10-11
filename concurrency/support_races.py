"""Support creation and retirement share a real PostgreSQL policy lock."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
from unittest.mock import patch

from django.db import connection
from tests.mfa_helpers import TransactionTestCase, override_settings
from concurrency.races import PostgreSQLRaces, PASSWORD
from support import views
from support.models import Ticket, TicketAudit


@override_settings(SECURE_SSL_REDIRECT=False, AUTH_ATTEMPT_LIMIT=1000)
class SupportRaces(TransactionTestCase):
    setUp = PostgreSQLRaces.setUp
    member = PostgreSQLRaces.member
    browser = PostgreSQLRaces.browser
    request = PostgreSQLRaces.request

    def test_retirement_waits_for_authorized_ticket_then_blocks_future_creation(self):
        browser, root_browser = self.browser(self.actor.user), self.browser(self.root)
        authorized, release = Event(), Event()
        original = views.actor_membership

        def pause(request, **kwargs):
            member = original(request, **kwargs)
            authorized.set()
            if not release.wait(8):
                raise AssertionError('Support race synchronization timed out')
            return member

        with patch.object(views, 'actor_membership', side_effect=pause), ThreadPoolExecutor(max_workers=2) as pool:
            creation = pool.submit(self.request, browser, '/support/new/', 'support-create', title='Test', body='Test')
            try:
                self.assertTrue(authorized.wait(5))
                retirement = pool.submit(self.request, root_browser, f'/manage/{self.actor.pk}/revoke/', 'support-retire')
                deadline = time.monotonic() + 5
                blocked = False
                while time.monotonic() < deadline and not retirement.done():
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE application_name = %s AND cardinality(pg_blocking_pids(pid)) > 0)", ['support-retire'])
                        blocked = cursor.fetchone()[0]
                    if blocked:
                        break
                    time.sleep(0.02)
                self.assertTrue(blocked, 'Retirement bypassed the support authorization lock')
            finally:
                release.set()
            self.assertEqual(creation.result(timeout=10), 302)
            self.assertEqual(retirement.result(timeout=10), 302)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketAudit.objects.count(), 1)
        self.assertEqual(browser.post('/support/new/', {'title': 'After', 'body': 'After', 'password': PASSWORD}).status_code, 302)
        self.assertEqual(Ticket.objects.count(), 1)
