from django.contrib.auth.models import User
from django.test import TestCase, override_settings


@override_settings(SECURE_SSL_REDIRECT=False)
class SignupTests(TestCase):
    def test_pending_login_status_and_post_logout(self):
        from membership.models import Tenant
        tenant = Tenant.objects.create(max_accounts=100, name='Signup')
        self.client.post('/signup/', {'username': 'pending', 'password1': 'Long-test-passphrase-829!', 'password2': 'Long-test-passphrase-829!', 'tenant': tenant.pk})
        response = self.client.post('/login/', {'username': 'pending', 'password': 'Long-test-passphrase-829!'})
        self.assertRedirects(response, '/account/', fetch_redirect_response=False)
        self.assertContains(self.client.get('/account/'), 'pending')
        self.assertEqual(self.client.get('/service/').status_code, 403)
        self.assertEqual(self.client.get('/logout/').status_code, 405)
        self.assertEqual(self.client.post('/logout/').status_code, 302)
        self.assertEqual(self.client.get('/account/').status_code, 302)

    def test_admin_approval_is_scoped_audited_and_requires_reauthentication(self):
        from membership.models import Membership, Tenant
        tenant = Tenant.objects.create(max_accounts=100, name='A')
        admin = User.objects.create_user('operator', password='Operator-passphrase-829!')
        Membership.objects.create(user=admin, tenant=tenant, status='approved', role='admin')
        user = User.objects.create_user('subject')
        subject = Membership.objects.create(user=user, tenant=tenant)
        self.client.force_login(admin)
        url = f'/manage/{subject.pk}/approve/'
        self.assertEqual(self.client.post(url, {'password': 'wrong'}).status_code, 403)
        self.assertEqual(self.client.post(url, {'password': 'Operator-passphrase-829!'}).status_code, 302)
        subject.refresh_from_db()
        self.assertEqual(subject.status, 'approved')
        from membership.models import AuditEvent
        event = AuditEvent.objects.get(subject=subject)
        self.assertEqual((event.actor_id, event.action, event.previous, event.current), (admin.pk, 'approve', 'pending', 'approved'))
        self.assertEqual(self.client.post(url, {'password': 'Operator-passphrase-829!'}).status_code, 409)
        other = Membership.objects.create(user=User.objects.create_user('other'), tenant=Tenant.objects.create(max_accounts=100, name='B'))
        self.assertEqual(self.client.post(f'/manage/{other.pk}/approve/', {'password': 'Operator-passphrase-829!'}).status_code, 404)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(user)
        self.assertEqual(self.client.post(url).status_code, 403)

    def test_revoke_ends_all_active_sessions_and_prevents_replay(self):
        from membership.models import Membership, Tenant, AuditEvent
        from django.test import Client
        from django.contrib.sessions.models import Session
        tenant = Tenant.objects.create(max_accounts=100, name='A')
        admin = User.objects.create_superuser('root', password='Operator-passphrase-829!')
        user = User.objects.create_user('subject', password='Member-passphrase-829!')
        subject = Membership.objects.create(user=user, tenant=tenant, status='approved')
        browsers = [Client(), Client()]
        for browser in browsers:
            browser.post('/login/', {'username': 'subject', 'password': 'Member-passphrase-829!'})
            self.assertEqual(browser.get('/service/').status_code, 200)
        keys = [browser.session.session_key for browser in browsers]
        self.client.force_login(admin)
        response = self.client.post(f'/manage/{subject.pk}/revoke/', {'password': 'Operator-passphrase-829!'})
        self.assertEqual(response.status_code, 302)
        subject.refresh_from_db()
        self.assertEqual(subject.status, 'suspended')
        self.assertFalse(Session.objects.filter(session_key__in=keys).exists())
        self.assertEqual(AuditEvent.objects.get(subject=subject).action, 'revoke')
        for browser in browsers:
            self.assertEqual(browser.get('/service/').status_code, 302)
        browsers[0].post('/login/', {'username': 'subject', 'password': 'Member-passphrase-829!'})
        self.assertEqual(browsers[0].get('/service/').status_code, 302)

    def test_management_ui_assigns_unassigned_applicant_only_by_global_admin(self):
        from membership.models import Membership, Tenant, AuditEvent
        tenant = Tenant.objects.create(max_accounts=100, name='A')
        root = User.objects.create_superuser('root', password='Operator-passphrase-829!')
        subject = Membership.objects.create(user=User.objects.create_user('applicant'))
        self.client.force_login(root)
        response = self.client.get('/manage/')
        self.assertContains(response, 'applicant')
        self.assertContains(response, 'csrfmiddlewaretoken')
        response = self.client.post(f'/manage/{subject.pk}/assign/', {'tenant': tenant.pk, 'password': 'Operator-passphrase-829!'})
        self.assertEqual(response.status_code, 302)
        subject.refresh_from_db()
        self.assertEqual(subject.tenant_id, tenant.pk)
        self.assertEqual(subject.status, 'pending')
        self.assertEqual(AuditEvent.objects.get(subject=subject).action, 'assign')
        operator = User.objects.create_user('operator', password='Operator-passphrase-829!')
        Membership.objects.create(user=operator, tenant=tenant, status='approved', role='admin')
        hidden = Membership.objects.create(user=User.objects.create_user('hidden'))
        self.client.force_login(operator)
        self.assertNotContains(self.client.get('/manage/'), '<h2>hidden</h2>')
        self.assertEqual(self.client.post(f'/manage/{hidden.pk}/assign/', {'tenant': tenant.pk, 'password': 'Operator-passphrase-829!'}).status_code, 403)

    def test_nas_link_is_unique_identifier_mapping_not_provisioning(self):
        from membership.models import Membership, Tenant, AuditEvent
        tenant = Tenant.objects.create(max_accounts=100, name='A')
        root = User.objects.create_superuser('root', password='Operator-passphrase-829!')
        subject = Membership.objects.create(user=User.objects.create_user('subject'), tenant=tenant, status='approved')
        self.client.force_login(root)
        url = f'/manage/{subject.pk}/link/'
        payload = {'password': 'Operator-passphrase-829!', 'external_id': 'nas-user-123', 'ownership_confirmed': 'on'}
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        from membership.models import NasBinding
        binding = NasBinding.objects.get(membership=subject)
        self.assertEqual(binding.external_id, 'nas-user-123')
        self.assertEqual(binding.tenant_id, tenant.pk)
        self.assertEqual(AuditEvent.objects.get(subject=subject).action, 'link')
        self.assertEqual(self.client.post(url, payload).status_code, 409)
        other = Membership.objects.create(user=User.objects.create_user('other'), tenant=tenant, status='approved')
        self.assertEqual(self.client.post(f'/manage/{other.pk}/link/', payload).status_code, 409)
        pending = Membership.objects.create(user=User.objects.create_user('pending'), tenant=tenant)
        self.assertEqual(self.client.post(f'/manage/{pending.pk}/link/', payload).status_code, 409)
        self.client.force_login(subject.user)
        self.assertEqual(self.client.post(url, payload).status_code, 403)
        self.assertEqual(NasBinding.objects.count(), 1)

    def test_weak_password_is_rejected(self):
        response = self.client.post('/signup/', {'username': 'weak', 'password1': '123', 'password2': '123'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='weak').exists())

    @override_settings(AUTH_ATTEMPT_LIMIT=3)
    def test_login_throttle_is_shared_across_clients(self):
        from django.test import Client
        for _ in range(3):
            self.assertEqual(Client().post('/login/', {'username': 'absent', 'password': 'wrong'}).status_code, 200)
        response = Client().post('/login/', {'username': 'absent', 'password': 'wrong'})
        self.assertEqual(response.status_code, 429)
        self.assertIn('Retry-After', response.headers)

    def test_membership_database_rejects_invalid_states(self):
        from membership.models import Membership, Tenant
        from django.db import IntegrityError, transaction
        tenant = Tenant.objects.create(max_accounts=100, name='A')
        for i, fields in enumerate(({'status': 'arbitrary', 'tenant': tenant}, {'role': 'owner', 'tenant': tenant}, {'status': 'approved'})):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                Membership.objects.create(user=User.objects.create_user(f'bad-{i}'), **fields)

    def test_session_has_bounded_expiry(self):
        from django.conf import settings
        self.assertLessEqual(settings.SESSION_COOKIE_AGE, 1800)
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)

    def test_signup_creates_pending_nonprivileged_identity(self):
        from membership.models import Tenant
        tenant = Tenant.objects.create(max_accounts=100, name='Signup')
        response = self.client.get('/signup/')
        self.assertEqual(response.status_code, 200)
        response = self.client.post('/signup/', {
            'username': 'applicant', 'password1': 'Long-test-passphrase-829!',
            'password2': 'Long-test-passphrase-829!', 'is_staff': 'true',
            'is_superuser': 'true', 'status': 'approved', 'role': 'admin', 'tenant': tenant.pk,
        })
        self.assertRedirects(response, '/login/', fetch_redirect_response=False)
        user = User.objects.get(username='applicant')
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertTrue(user.check_password('Long-test-passphrase-829!'))
        self.assertEqual(user.membership.status, 'pending')
        self.assertEqual(user.membership.role, 'member')
        self.assertEqual(user.membership.tenant_id, tenant.pk)
