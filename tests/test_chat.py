from django.contrib.auth.models import User
from tests.mfa_helpers import TestCase, override_settings
from membership.models import Membership, Tenant


@override_settings(SECURE_SSL_REDIRECT=False, MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True)
class ChatTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Chat customer')
        self.user = User.objects.create_user('chat-owner')
        self.member = Membership.objects.create(user=self.user, tenant=self.tenant, status='approved')
        self.client.force_login(self.user)

    def test_send_plain_text_and_resume_chronological_bounded_events(self):
        from uuid import uuid4
        conversation = self.client.post('/chat/').url
        events = conversation + 'events/'
        first = self.client.post(events, {'body': '<script>first</script>', 'nonce': str(uuid4()), 'author': '999'})
        self.assertEqual(first.status_code, 201)
        from chat.models import Message
        self.assertEqual(Message.objects.get().author_id, self.user.pk)
        page = self.client.get(events).json()
        self.assertEqual([m['body'] for m in page['messages']], ['<script>first</script>'])
        cursor = page['cursor']
        for i in range(52):
            Message.objects.create(conversation_id=conversation.split('/')[2], author=self.user, body=str(i), nonce=uuid4())
        page = self.client.get(events, {'after': cursor}).json()
        self.assertEqual(len(page['messages']), 50)
        self.assertTrue(page['has_more'])
        self.assertEqual([m['body'] for m in page['messages']], [str(i) for i in range(50)])
        final = self.client.get(events, {'after': page['cursor']}).json()
        self.assertEqual([m['body'] for m in final['messages']], ['50', '51'])
        self.assertFalse(final['has_more'])
        self.assertEqual(self.client.get(events, {'after': final['cursor']}).json()['messages'], [])
        self.assertEqual(self.client.get(events, {'after': cursor}).json(), page)

    def test_validation_and_idempotent_retry(self):
        from uuid import uuid4
        from chat.models import Message
        from django.core.files.uploadedfile import SimpleUploadedFile
        path = self.client.post('/chat/').url + 'events/'
        nonce = str(uuid4())
        for body in ('', '   ', 'x' * 2001):
            self.assertEqual(self.client.post(path, {'body': body, 'nonce': nonce}).status_code, 400)
        self.assertEqual(self.client.post(path, {'body': 'x', 'nonce': 'invalid'}).status_code, 400)
        self.assertEqual(self.client.post(path, {'body': 'x', 'nonce': nonce, 'file': SimpleUploadedFile('a', b'x')}).status_code, 400)
        for cursor in ('-1', 'no', '9' * 100, '1.2', '١'):
            self.assertEqual(self.client.get(path, {'after': cursor}).status_code, 400)
        self.assertFalse(Message.objects.exists())
        data = {'body': 'x' * 2000, 'nonce': nonce}
        first = self.client.post(path, data)
        self.assertEqual(first.status_code, 201)
        retry = self.client.post(path, data)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(first.json(), retry.json())
        self.assertEqual(self.client.post(path, {**data, 'body': 'changed'}).status_code, 409)
        self.assertEqual(Message.objects.count(), 1)

    def test_rate_windows_bound_reads_and_writes_across_conversations(self):
        from uuid import uuid4
        from django.utils import timezone
        from datetime import timedelta
        path = self.client.post('/chat/').url + 'events/'
        for _ in range(19):
            self.assertEqual(self.client.post(path, {'body': 'x', 'nonce': str(uuid4())}).status_code, 201)
        denied = self.client.post(path, {'body': 'x', 'nonce': str(uuid4())})
        self.assertEqual(denied.status_code, 429)
        self.assertIn('Retry-After', denied.headers)
        for _ in range(60):
            self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.get(path).status_code, 429)
        from chat.models import RateWindow
        RateWindow.objects.update(read_started=timezone.now()-timedelta(seconds=61), write_started=timezone.now()-timedelta(seconds=61))
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.post(path, {'body': 'x', 'nonce': str(uuid4())}).status_code, 201)
        self.assertEqual(RateWindow.objects.count(), 1)

    def test_not_found_reads_cannot_rollback_rate_budget(self):
        for _ in range(60):
            self.assertEqual(self.client.get('/chat/99999/events/').status_code, 404)
        self.assertEqual(self.client.get('/chat/99999/events/').status_code, 429)

    def test_start_rejects_attachments(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from chat.models import Conversation
        self.assertEqual(self.client.post('/chat/', {'file': SimpleUploadedFile('a', b'x')}).status_code, 400)
        self.assertFalse(Conversation.objects.exists())

    def test_start_own_conversation_is_idempotent_and_not_a_ticket(self):
        response = self.client.post('/chat/', {'owner': '999', 'tenant': '999'})
        self.assertEqual(response.status_code, 302)
        from chat.models import Conversation
        from support.models import Ticket
        conversation = Conversation.objects.get()
        self.assertEqual((conversation.owner_id, conversation.tenant_id), (self.user.pk, self.tenant.pk))
        self.assertEqual(response.url, f'/chat/{conversation.pk}/')
        self.assertEqual(self.client.post('/chat/').url, response.url)
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertFalse(Ticket.objects.exists())
