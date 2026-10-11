"""Explicit PostgreSQL concurrency acceptance; never skipped on SQLite."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
from uuid import uuid4

from django.db import connection, connections
from tests.mfa_helpers import TransactionTestCase, override_settings
from concurrency import races, reply_races
from membership import views as membership_views
from chat import views
from chat.models import Conversation, Message, RateWindow


@override_settings(SECURE_SSL_REDIRECT=False, AUTH_ATTEMPT_LIMIT=1000)
class ChatRaces(TransactionTestCase):
    setUp = races.PostgreSQLRaces.setUp
    member = races.PostgreSQLRaces.member
    browser = races.PostgreSQLRaces.browser
    assert_blocked = reply_races.ReplyRaces.assert_blocked

    def request(self, browser, path, name, method='post', **data):
        try:
            with connection.cursor() as cursor:
                cursor.execute('SET application_name = %s', [name])
                cursor.execute("SET statement_timeout = '10s'")
            return getattr(browser, method)(path, {'password': races.PASSWORD, **data}).status_code
        finally:
            connections.close_all()

    def retirement_race(self, method, retire_first):
        conversation = Conversation.objects.create(tenant=self.tenant, owner=self.actor.user)
        path = f'/chat/{conversation.pk}/events/'
        browser, root = self.browser(self.actor.user), self.browser(self.root)
        authorized, release = Event(), Event()
        module = membership_views if retire_first else views
        name = 'managed_members' if retire_first else 'visible_conversations'
        original = getattr(module, name)

        def pause(*args, **kwargs):
            result = original(*args, **kwargs)
            authorized.set()
            if not release.wait(8):
                raise AssertionError('Chat race synchronization timed out')
            return result

        def chat():
            return self.request(browser, path, 'chat-race', method=method, body='race message', nonce=str(uuid4()))

        def retire():
            return self.request(root, f'/manage/{self.actor.pk}/revoke/', 'chat-retire')

        with patch.object(module, name, side_effect=pause), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(retire if retire_first else chat)
            try:
                self.assertTrue(authorized.wait(5))
                second = pool.submit(chat if retire_first else retire)
                self.assert_blocked('chat-race' if retire_first else 'chat-retire', second)
            finally:
                release.set()
            if retire_first:
                self.assertEqual(first.result(timeout=10), 302)
                self.assertEqual(second.result(timeout=10), 403)
            else:
                self.assertEqual(first.result(timeout=10), 201 if method == 'post' else 200)
                self.assertEqual(second.result(timeout=10), 302)
        self.assertEqual(Message.objects.count(), int(method == 'post' and not retire_first))
        self.assertEqual(browser.get(path).status_code, 302)
        self.assertEqual(browser.post(path, {'body': 'after', 'nonce': str(uuid4())}).status_code, 302)

    def test_retirement_waits_for_send(self):
        self.retirement_race('post', False)

    def test_send_waiting_behind_retirement_rechecks_actor(self):
        self.retirement_race('post', True)

    def test_retirement_waits_for_read_serialization(self):
        self.retirement_race('get', False)

    def test_read_waiting_behind_retirement_rechecks_actor(self):
        self.retirement_race('get', True)

    def test_cursor_cannot_skip_an_uncommitted_lower_id(self):
        conversation = Conversation.objects.create(tenant=self.tenant, owner=self.actor.user)
        path = f'/chat/{conversation.pk}/events/'
        clients = [self.browser(self.actor.user) for _ in range(3)]
        inserted, release = Event(), Event()
        original = Message.objects.get_or_create

        def pause(*args, **kwargs):
            result = original(*args, **kwargs)
            if kwargs['defaults']['body'] == 'first':
                inserted.set()
                if not release.wait(8):
                    raise AssertionError('Uncommitted insert timeout')
            return result

        def fetch():
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET application_name = 'chat-cursor'")
                    cursor.execute("SET statement_timeout = '10s'")
                return clients[2].get(path).json()
            finally:
                connections.close_all()

        with patch('chat.views.Message.objects.get_or_create', side_effect=pause), ThreadPoolExecutor(max_workers=3) as pool:
            first = pool.submit(self.request, clients[0], path, 'chat-first', body='first', nonce=str(uuid4()))
            try:
                self.assertTrue(inserted.wait(5))
                second = pool.submit(self.request, clients[1], path, 'chat-second', body='second', nonce=str(uuid4()))
                reader = pool.submit(fetch)
                self.assert_blocked('chat-second', second)
                self.assert_blocked('chat-cursor', reader)
            finally:
                release.set()
            self.assertEqual(first.result(timeout=10), 201)
            self.assertEqual(second.result(timeout=10), 201)
            page = reader.result(timeout=10)
        resumed = clients[2].get(path, {'after': page['cursor']}).json()
        messages = page['messages'] + resumed['messages']
        self.assertEqual([m['body'] for m in messages], ['first', 'second'])
        self.assertEqual(len({m['id'] for m in messages}), 2)

    def test_concurrent_idempotency_and_rate_limit(self):
        conversation = Conversation.objects.create(tenant=self.tenant, owner=self.actor.user)
        path = f'/chat/{conversation.pk}/events/'
        browsers = [self.browser(self.actor.user), self.browser(self.actor.user)]
        nonce = str(uuid4())
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.request, browser, path, f'chat-duplicate-{i}', body='same', nonce=nonce) for i, browser in enumerate(browsers)]
            self.assertEqual(sorted(f.result(timeout=10) for f in futures), [200, 201])
        self.assertEqual(Message.objects.count(), 1)
        RateWindow.objects.filter(user=self.actor.user).update(write_count=19)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.request, browser, path, f'chat-rate-{i}', body='new', nonce=str(uuid4())) for i, browser in enumerate(browsers)]
            self.assertEqual(sorted(f.result(timeout=10) for f in futures), [201, 429])
        self.assertEqual(Message.objects.count(), 2)
