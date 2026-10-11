from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from membership.models import Membership, Tenant
from support.models import Ticket, TicketAudit


@override_settings(SECURE_SSL_REDIRECT=False, MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True)
class ReplyTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Replies A')
        self.user = User.objects.create_user('reply-owner')
        self.member = Membership.objects.create(user=self.user, tenant=self.tenant, status='approved')
        self.ticket = Ticket.objects.create(tenant=self.tenant, author=self.user, title='Help', body='Question')
        self.path = f'/support/{self.ticket.pk}/replies/'
        self.client.force_login(self.user)

    def test_scope_matrix_does_not_expand_ticket_visibility(self):
        from support.models import TicketReply
        peer = User.objects.create_user('peer')
        Membership.objects.create(user=peer, tenant=self.tenant, status='approved')
        manager = User.objects.create_user('manager')
        Membership.objects.create(user=manager, tenant=self.tenant, status='approved', role='admin')
        foreign = User.objects.create_user('foreign-manager')
        other = Tenant.objects.create(name='Replies B')
        Membership.objects.create(user=foreign, tenant=other, status='approved', role='admin')
        root = User.objects.create_superuser('root')
        staff = User.objects.create_user('staff', is_staff=True)
        TicketReply.objects.create(ticket=self.ticket, author=self.user, body='private-answer')
        for actor, expected in ((self.user, 302), (peer, 404), (manager, 302), (foreign, 404), (root, 302), (staff, 403)):
            self.client.force_login(actor)
            before = TicketReply.objects.count()
            response = self.client.post(self.path + '?tenant=' + str(self.tenant.pk), {'body': 'Answer', 'internal': 'true'})
            self.assertEqual(response.status_code, expected)
            self.assertEqual(TicketReply.objects.count(), before + (expected == 302))
            detail = self.client.get(f'/support/{self.ticket.pk}/')
            self.assertEqual(detail.status_code, 200 if expected == 302 else expected)
            if expected == 302:
                self.assertContains(detail, 'private-answer')
            else:
                self.assertNotIn(b'private-answer', detail.content)

    def test_denied_status_and_retired_sessions(self):
        from support.models import TicketReply
        for status in ('pending', 'suspended'):
            self.member.status = status
            self.member.save()
            self.client.force_login(self.user)
            self.assertEqual(self.client.post(self.path, {'body': 'Answer'}).status_code, 403)
            self.assertEqual(self.client.get(f'/support/{self.ticket.pk}/').status_code, 403)
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.client.post(self.path, {'body': 'Answer'}).status_code, 302)
        self.assertFalse(TicketReply.objects.exists())

    def test_inflight_fresh_actor_epoch_and_scope(self):
        from django.test import RequestFactory
        from django.core.exceptions import PermissionDenied
        from django.http import Http404
        from support.views import reply
        from support.models import TicketReply
        def request():
            result = RequestFactory().post(self.path, {'body': 'Answer'})
            result.user = self.user
            result.session = {'membership_version': 0}
            return result
        self.member.session_version = 1
        self.member.save()
        with self.assertRaises(PermissionDenied):
            reply(request(), self.ticket.pk)
        self.member.session_version = 0
        self.member.tenant = Tenant.objects.create(name='Moved')
        self.member.save()
        with self.assertRaises(Http404):
            reply(request(), self.ticket.pk)
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            reply(request(), self.ticket.pk)
        self.assertFalse(TicketReply.objects.exists())

    def test_audit_failure_rolls_back_and_history_is_protected(self):
        from unittest.mock import patch
        from django.db.models.deletion import ProtectedError
        from support.models import TicketReply
        with patch('support.views.TicketAudit.objects.create', side_effect=RuntimeError('audit unavailable')):
            with self.assertRaisesMessage(RuntimeError, 'audit unavailable'):
                self.client.post(self.path, {'body': 'secret answer'})
        self.assertFalse(TicketReply.objects.exists())
        self.client.post(self.path, {'body': 'secret answer'})
        self.assertNotIn('secret answer', str(TicketAudit.objects.values().get()))
        with self.assertRaises(ProtectedError):
            self.ticket.delete()
        with self.assertRaises(ProtectedError):
            self.user.delete()

    def test_csrf_methods_no_store_and_no_edit_delete(self):
        from django.test import Client
        from support.models import TicketReply
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        missing = browser.post(self.path, {'body': 'Answer'})
        self.assertEqual(missing.status_code, 403)
        self.assertIn('no-store', missing.headers['Cache-Control'])
        browser.get(f'/support/{self.ticket.pk}/')
        response = browser.post(self.path, {'body': 'Answer', 'csrfmiddlewaretoken': browser.cookies['csrftoken'].value})
        self.assertEqual(response.status_code, 302)
        self.assertIn('no-store', response.headers['Cache-Control'])
        for method in ('get', 'put', 'patch', 'delete'):
            response = getattr(self.client, method)(self.path)
            self.assertEqual(response.status_code, 405)
            self.assertIn('no-store', response.headers['Cache-Control'])
        for suffix in ('1/', '1/edit/', '1/delete/'):
            self.assertEqual(self.client.post(self.path + suffix).status_code, 404)
        self.assertEqual(TicketReply.objects.count(), 1)
        self.client.logout()
        self.assertEqual(self.client.post(self.path, {'body': 'Answer'}).status_code, 302)
        self.assertEqual(TicketReply.objects.count(), 1)

    def test_sqlite_without_opt_in_fails_closed(self):
        from django.db import connection
        if connection.vendor == 'sqlite':
            with override_settings(MEMBERSHIP_ALLOW_UNSAFE_SQLITE=False):
                self.assertEqual(self.client.post(self.path, {'body': 'Answer'}).status_code, 503)

    def test_upload_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from support.models import TicketReply
        response = self.client.post(self.path, {'body': 'Answer', 'attachment': SimpleUploadedFile('x.txt', b'x')})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(TicketReply.objects.exists())

    def test_body_validation(self):
        from support.models import TicketReply
        for body in ('', '   ', 'x' * 10001):
            response = self.client.post(self.path, {'body': body})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'errorlist')
            self.assertFalse(TicketReply.objects.exists())
            self.assertFalse(TicketAudit.objects.exists())
        self.assertEqual(self.client.post(self.path, {'body': 'x' * 10000}).status_code, 302)

    def test_read_chronological_escaped_replies_and_form(self):
        from support.models import TicketReply
        from django.utils import timezone
        first = TicketReply.objects.create(ticket=self.ticket, author=self.user, body='<script>first</script>')
        second = TicketReply.objects.create(ticket=self.ticket, author=self.user, body='second-answer')
        TicketReply.objects.filter(pk__in=[first.pk, second.pk]).update(created_at=timezone.now())
        response = self.client.get(f'/support/{self.ticket.pk}/')
        self.assertContains(response, '&lt;script&gt;first&lt;/script&gt;')
        self.assertNotContains(response, '<script>first</script>')
        self.assertLess(response.content.index(b'first'), response.content.index(b'second-answer'))
        self.assertContains(response, f'action="{self.path}"')
        self.assertContains(response, 'csrfmiddlewaretoken')

    def test_create_derives_ticket_and_author_and_atomic_audit(self):
        response = self.client.post(self.path, {'body': 'First answer', 'author': '999', 'tenant': '999', 'ticket': '999'})
        self.assertEqual(response.status_code, 302)
        from support.models import TicketReply
        reply = TicketReply.objects.get()
        self.assertEqual((reply.ticket_id, reply.author_id, reply.body), (self.ticket.pk, self.user.pk, 'First answer'))
        audit = TicketAudit.objects.get()
        self.assertEqual((audit.ticket_id, audit.actor_id, audit.action), (self.ticket.pk, self.user.pk, 'replied'))
        self.assertEqual(response.url, f'/support/{self.ticket.pk}/')
