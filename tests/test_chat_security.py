from uuid import uuid4
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from tests.mfa_helpers import Client, RequestFactory, TestCase, override_settings
from membership.models import Membership, Tenant
from tests import test_chat
from chat.models import Conversation, Message
from chat import views


@override_settings(SECURE_SSL_REDIRECT=False, MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True)
class ChatSecurityTests(TestCase):
    setUp = test_chat.ChatTests.setUp

    def conversation(self):
        return self.client.post('/chat/').url

    def test_csrf_privacy_methods_and_account_link(self):
        path = self.conversation()
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        denied = browser.post(path + 'events/', {'body': 'no token', 'nonce': str(uuid4())})
        self.assertEqual(denied.status_code, 403)
        self.assertIn('no-store', denied.headers.get('Cache-Control', ''))
        browser.get(path)
        allowed = browser.post(path + 'events/', {'body': 'yes', 'nonce': str(uuid4()), 'csrfmiddlewaretoken': browser.cookies['csrftoken'].value})
        self.assertEqual(allowed.status_code, 201)
        for url in ('/chat/', path, path + 'events/', '/chat/99999/'):
            self.assertIn('no-store', self.client.get(url).headers.get('Cache-Control', ''))
            self.assertEqual(self.client.delete(url).status_code, 405)
        self.assertContains(self.client.get('/account/'), 'href="/chat/"')
        self.client.logout()
        self.assertEqual(self.client.get(path+'events/').status_code, 302)

    def test_customer_owner_group_admin_global_scope_matrix(self):
        path = self.conversation()
        Message.objects.create(conversation=Conversation.objects.get(), author=self.user, body='private-content', nonce=uuid4())
        peer = User.objects.create_user('chat-peer')
        Membership.objects.create(user=peer, tenant=self.tenant, status='approved')
        admin = User.objects.create_user('chat-admin')
        Membership.objects.create(user=admin, tenant=self.tenant, status='approved', role='admin')
        foreign = User.objects.create_user('chat-foreign')
        Membership.objects.create(user=foreign, tenant=Tenant.objects.create(name='Other customer'), status='approved', role='admin')
        root = User.objects.create_superuser('chat-root')
        staff = User.objects.create_user('chat-staff', is_staff=True)
        for user, expected in ((self.user, 200), (peer, 404), (admin, 200), (foreign, 404), (root, 200), (staff, 403)):
            self.client.force_login(user)
            for url in (path, path+'events/'):
                response = self.client.get(url, {'tenant': self.tenant.pk, 'owner': self.user.pk})
                self.assertEqual(response.status_code, expected)
                if expected != 200:
                    self.assertNotIn(b'private-content', response.content)
            index = self.client.get('/chat/')
            if expected == 200:
                self.assertContains(index, path)
            elif expected == 404:
                self.assertNotContains(index, path)
            response = self.client.post(path+'events/', {'body': 'reply', 'nonce': str(uuid4())})
            self.assertEqual(response.status_code, 201 if expected == 200 else expected)

    def test_pending_suspended_and_retired_cannot_read_or_write(self):
        path = self.conversation()
        for status in ('pending', 'suspended'):
            self.member.status = status
            self.member.save()
            self.client.force_login(self.user)
            for url in ('/chat/', path, path+'events/'):
                self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(path+'events/', {'body': 'x', 'nonce': str(uuid4())}).status_code, 403)
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertEqual(self.client.get(path+'events/').status_code, 302)
        self.assertEqual(self.client.post(path+'events/', {'body': 'x', 'nonce': str(uuid4())}).status_code, 302)
        self.assertFalse(Message.objects.exists())

    def test_inflight_actor_is_reloaded_for_reads_and_writes(self):
        path = self.conversation()
        pk = Conversation.objects.get().pk
        for field, value in (('session_version', 1), ('status', 'suspended')):
            Membership.objects.filter(pk=self.member.pk).update(**{field: value})
            for method in ('get', 'post'):
                request = getattr(RequestFactory(), method)(path+'events/', {'body': 'x', 'nonce': str(uuid4())})
                request.user = self.user
                request.session = {'membership_version': 0}
                with self.assertRaises(PermissionDenied):
                    views.events(request, pk)
            Membership.objects.filter(pk=self.member.pk).update(session_version=0, status='approved')
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        request = RequestFactory().get(path+'events/')
        request.user, request.session = self.user, {'membership_version': 0}
        with self.assertRaises(PermissionDenied):
            views.events(request, pk)
        self.assertFalse(Message.objects.exists())

    def test_sqlite_fails_closed_without_development_opt_in(self):
        from django.db import connection
        path = self.conversation()
        if connection.vendor == 'sqlite':
            with override_settings(MEMBERSHIP_ALLOW_UNSAFE_SQLITE=False):
                for url in ('/chat/', path, path+'events/'):
                    self.assertEqual(self.client.get(url).status_code, 503)
                self.assertEqual(self.client.post(path+'events/', {'body': 'x', 'nonce': str(uuid4())}).status_code, 503)
