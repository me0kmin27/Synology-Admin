"""Explicit PostgreSQL proof: queued dashboard refreshes revoked authorization."""
from concurrent.futures import ThreadPoolExecutor
import time

from django.db import connection, connections
from tests.mfa_helpers import RequestFactory, TransactionTestCase, override_settings
from concurrency.races import PostgreSQLRaces
from membership.locking import policy_transaction
from membership.models import Membership
from membership.views import service


@override_settings(SECURE_SSL_REDIRECT=False)
class StorageRaces(TransactionTestCase):
    setUp = PostgreSQLRaces.setUp
    member = PostgreSQLRaces.member

    def test_queued_read_rechecks_epoch_after_policy_commit(self):
        request = RequestFactory().get('/service/')
        request.user = self.actor.user  # Deliberately cached before revocation.
        request.session = {'membership_version': self.actor.session_version}

        def read():
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET application_name = 'storage-queued-read'")
                    cursor.execute("SET statement_timeout = '10s'")
                return service(request)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with policy_transaction():
                future = pool.submit(read)
                deadline = time.monotonic() + 5
                blocked = False
                while time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT pg_stat_clear_snapshot()')
                        cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE application_name = 'storage-queued-read' AND cardinality(pg_blocking_pids(pid)) > 0)")
                        blocked = cursor.fetchone()[0]
                    if blocked or future.done():
                        break
                    time.sleep(0.02)
                self.assertTrue(blocked, 'Dashboard bypassed PostgreSQL policy lock')
                Membership.objects.filter(pk=self.actor.pk).update(session_version=self.actor.session_version + 1)
            response = future.result(timeout=10)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b'data-usage', response.content)
        print('STORAGE POSTGRES PASS: pg_blocking_pids confirmed queued read; committed epoch invalidation denied cached actor')
