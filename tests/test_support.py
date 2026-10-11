from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from membership.models import Membership, Tenant


@override_settings(SECURE_SSL_REDIRECT=False, MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True)
class TicketTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Support A')
        self.user = User.objects.create_user('requester')
        self.member = Membership.objects.create(user=self.user, tenant=self.tenant, status='approved')
        self.client.force_login(self.user)

    def test_account_links_to_support(self):
        self.assertContains(self.client.get('/account/'), 'href="/support/"')

    def test_pending_suspended_retired_anonymous_and_staff_are_denied(self):
        from support.models import Ticket
        ticket = Ticket.objects.create(tenant=self.tenant, author=self.user, title='Private', body='private')
        paths = ('/support/', '/support/new/', f'/support/{ticket.pk}/')
        for status in ('pending', 'suspended'):
            self.member.status = status
            self.member.save()
            self.client.force_login(self.user)
            for path in paths:
                self.assertEqual(self.client.get(path).status_code, 403)
            self.assertEqual(self.client.post('/support/new/', {'title': 'bad', 'body': 'bad'}).status_code, 403)
        self.user.is_active = False
        self.user.save()
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.post('/support/new/', {}).status_code, 302)
        staff = User.objects.create_user('staff', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get('/support/').status_code, 403)
        self.assertEqual(Ticket.objects.count(), 1)

    def test_csrf_valid_and_missing_token_methods_and_no_edit_or_delete(self):
        from django.test import Client
        from support.models import Ticket, TicketAudit
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        self.assertEqual(browser.post('/support/new/', {'title': 'A', 'body': 'B'}).status_code, 403)
        self.assertContains(browser.get('/support/new/'), 'csrfmiddlewaretoken')
        token = browser.cookies['csrftoken'].value
        response = browser.post('/support/new/', {'title': 'A', 'body': 'B', 'csrfmiddlewaretoken': token})
        self.assertEqual(response.status_code, 302)
        ticket = Ticket.objects.get()
        for method in ('post', 'put', 'patch', 'delete'):
            self.assertEqual(getattr(self.client, method)(response.url, {'author': '999'}).status_code, 405)
        for suffix in ('edit/', 'delete/', 'audit/'):
            self.assertEqual(self.client.post(response.url + suffix).status_code, 404)
        self.assertEqual(self.client.put('/support/new/', {}).status_code, 405)
        ticket.refresh_from_db()
        self.assertEqual(ticket.author_id, self.user.pk)
        self.assertEqual(TicketAudit.objects.count(), 1)

    def test_audit_failure_rolls_back_ticket_and_retirement_protects_history(self):
        from unittest.mock import patch
        from django.db.models.deletion import ProtectedError
        from support.models import Ticket, TicketAudit
        with patch('support.views.TicketAudit.objects.create', side_effect=RuntimeError('audit unavailable')):
            with self.assertRaisesMessage(RuntimeError, 'audit unavailable'):
                self.client.post('/support/new/', {'title': 'A', 'body': 'B'})
        self.assertFalse(Ticket.objects.exists())
        self.client.post('/support/new/', {'title': 'A', 'body': 'B'})
        self.user.is_active = False
        self.user.save()
        self.assertEqual(TicketAudit.objects.get().actor_id, self.user.pk)
        with self.assertRaises(ProtectedError):
            self.user.delete()
        with self.assertRaises(ProtectedError):
            Ticket.objects.get().delete()

    def test_input_validation_pagination_and_body_not_in_audit(self):
        from support.models import Ticket, TicketAudit
        for payload in ({}, {'title': ' ', 'body': 'B'}, {'title': 'A'*161, 'body': 'B'}, {'title': 'A', 'body': 'B'*10001}):
            self.assertEqual(self.client.post('/support/new/', payload).status_code, 200)
            self.assertFalse(Ticket.objects.exists())
        self.client.post('/support/new/', {'title': 'Private title', 'body': 'Private body'})
        self.assertNotIn('Private', str(TicketAudit.objects.values().get()))
        for i in range(26):
            Ticket.objects.create(tenant=self.tenant, author=self.user, title=f'Ticket {i}', body='B')
        self.assertEqual(len(self.client.get('/support/').context['page']), 25)
        cursor = self.client.get('/support/').context['next_cursor']
        self.assertEqual(len(self.client.get('/support/', {'before': cursor}).context['page']), 2)

    def test_stale_inflight_session_and_sqlite_default_fail_closed(self):
        from django.test import RequestFactory
        from django.db import connection
        from support.views import create
        from support.models import Ticket
        request = RequestFactory().post('/support/new/', {'title': 'A', 'body': 'B'})
        request.user = self.user
        request.session = {'membership_version': 0}
        self.member.session_version = 1
        self.member.save()
        from django.core.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            create(request)
        self.assertFalse(Ticket.objects.exists())
        if connection.vendor == 'sqlite':
            self.client.force_login(self.user)
            with override_settings(MEMBERSHIP_ALLOW_UNSAFE_SQLITE=False):
                self.assertEqual(self.client.post('/support/new/', {'title': 'A', 'body': 'B'}).status_code, 503)

    def test_upload_is_explicitly_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from support.models import Ticket
        response = self.client.post('/support/new/', {'title': 'Valid', 'body': 'Body',
            'attachment': SimpleUploadedFile('bad.html', b'<script>bad</script>')})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Ticket.objects.exists())

    def test_private_pages_are_never_cached(self):
        for path in ('/support/', '/support/new/', '/support/999/'):
            self.assertIn('no-store', self.client.get(path).headers.get('Cache-Control', ''))

    def test_scoped_list_detail_and_escaped_content(self):
        from support.models import Ticket
        other_tenant = Tenant.objects.create(name='Support B')
        peer = User.objects.create_user('peer')
        manager = User.objects.create_user('manager')
        root = User.objects.create_superuser('root')
        Membership.objects.create(user=manager, tenant=self.tenant, status='approved', role='admin')
        own = Ticket.objects.create(tenant=self.tenant, author=self.user, title='<script>own</script>', body='<img src=x onerror=alert(1)>')
        same = Ticket.objects.create(tenant=self.tenant, author=peer, title='Peer ticket', body='private')
        other = Ticket.objects.create(tenant=other_tenant, author=peer, title='Other tenant', body='private')
        for actor, visible in ((self.user, [own]), (manager, [own, same]), (root, [own, same, other])):
            self.client.force_login(actor)
            response = self.client.get('/support/?tenant=' + str(other_tenant.pk))
            self.assertEqual(response.status_code, 200)
            for ticket in (own, same, other):
                detail = self.client.get(f'/support/{ticket.pk}/')
                self.assertEqual(detail.status_code, 200 if ticket in visible else 404)
                if ticket in visible:
                    self.assertContains(response, f'/support/{ticket.pk}/')
                else:
                    self.assertNotContains(response, f'/support/{ticket.pk}/')
            self.assertContains(self.client.get(f'/support/{own.pk}/'), '&lt;script&gt;own&lt;/script&gt;')
            self.assertNotContains(self.client.get(f'/support/{own.pk}/'), '<img src=x')

    def test_create_uses_session_author_and_tenant_and_atomic_audit(self):
        response = self.client.post('/support/new/', {
            'title': 'Connection problem', 'body': 'Cannot connect',
            'author': '999', 'tenant': '999', 'status': 'closed',
        })
        self.assertEqual(response.status_code, 302)
        from support.models import Ticket, TicketAudit
        ticket = Ticket.objects.get()
        self.assertEqual((ticket.author_id, ticket.tenant_id, ticket.title, ticket.body),
                         (self.user.pk, self.tenant.pk, 'Connection problem', 'Cannot connect'))
        audit = TicketAudit.objects.get(ticket=ticket)
        self.assertEqual((audit.actor_id, audit.action), (self.user.pk, 'created'))
        self.assertEqual(response.url, f'/support/{ticket.pk}/')
