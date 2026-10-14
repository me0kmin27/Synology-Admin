"""Real PostgreSQL CAS race: both readers see unconsumed state before either update."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from django.db import close_old_connections, connection
from django.db.models.query import QuerySet
from django.test import Client, TransactionTestCase, override_settings
from membership.models import OIDCLoginAttempt
from tests.test_oidc import CONFIG, METADATA, response


@override_settings(**CONFIG)
class OIDCRaces(TransactionTestCase):
    def test_simultaneous_callback_redeems_only_once(self):
        self.assertEqual(connection.vendor, 'postgresql', 'Real PostgreSQL required; no skips')
        browser = Client()
        with patch('requests.sessions.Session.send', return_value=response(METADATA)):
            result = browser.post('/auth/oidc/login/', secure=True)
        self.assertEqual(result.status_code, 302)
        state = parse_qs(urlsplit(result.url).query)['state'][0]
        barrier = Barrier(2)
        original = QuerySet.first
        def synchronized_first(queryset):
            value = original(queryset)
            if queryset.model is OIDCLoginAttempt:
                self.assertIsNotNone(value)
                barrier.wait(timeout=10)
            return value
        def send(session, prepared, **kwargs):
            if prepared.url.endswith('/token/'):
                return response({'error': 'invalid_grant'})
            return response(METADATA)
        def callback():
            close_old_connections()
            try:
                client = Client()
                client.cookies = browser.cookies.copy()
                return client.get('/auth/oidc/callback/', {'state': state, 'code': 'code'}, secure=True).status_code
            finally:
                close_old_connections()
        with patch.object(QuerySet, 'first', synchronized_first), patch('requests.sessions.Session.send', autospec=True, side_effect=send) as transport:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: callback(), range(2)))
        self.assertEqual(results, [400, 400])
        self.assertEqual(sum(call.args[1].url.endswith('/token/') for call in transport.call_args_list), 1)
        attempt = OIDCLoginAttempt.objects.get()
        self.assertTrue(attempt.consumed)
        self.assertEqual((attempt.verifier, attempt.nonce), ('', ''))
