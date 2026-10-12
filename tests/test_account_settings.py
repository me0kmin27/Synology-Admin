from django.contrib.auth.models import User
from django.test import override_settings
from tests.mfa_helpers import TestCase, Client
from membership.models import Membership, Tenant


@override_settings(SECURE_SSL_REDIRECT=False, MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True)
class AccountSettingsTests(TestCase):
    def setUp(self):
        import secrets
        self.password = secrets.token_urlsafe(24)
        self.user = User.objects.create_user('original', password=self.password)
        self.member = Membership.objects.create(user=self.user, tenant=Tenant.objects.create(name='owner'), status='approved')
        self.client.force_login(self.user)

    def test_identifier_change_normalizes_and_revokes_other_sessions(self):
        other = Client()
        other.force_login(self.user)
        old_key = self.client.session.session_key
        response = self.client.post('/account/settings/', {'password': self.password, 'username': 'ｒｅｎａｍｅｄ'})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'renamed')
        self.assertNotEqual(old_key, self.client.session.session_key)
        self.assertEqual(self.client.get('/account/').status_code, 200)
        self.assertEqual(other.get('/account/').status_code, 302)
        self.member.refresh_from_db()
        self.assertEqual(self.member.session_version, 1)

    def test_bootstrap_forces_change_after_mfa_before_privileged_access(self):
        from membership.models import BootstrapAdmin
        self.user.is_superuser = True
        self.user.save()
        BootstrapAdmin.objects.create(user=self.user)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/manage/').url, '/account/settings/')
        self.assertEqual(self.client.post('/manage/1/approve/', {'password': self.password}).status_code, 403)
        self.assertEqual(self.client.post('/account/settings/', {'username': 'newadmin', 'password': self.password}).status_code, 400)
        import secrets
        new = secrets.token_urlsafe(24)
        self.assertEqual(self.client.post('/account/settings/', {'username': 'newadmin', 'password': self.password, 'new_password1': new, 'new_password2': new}).status_code, 302)
        self.assertEqual(self.client.get('/manage/').status_code, 200)
        self.assertFalse(BootstrapAdmin.objects.get(user=self.user).must_change_password)

    @override_settings(AUTH_ATTEMPT_LIMIT=1)
    def test_reauth_throttle_and_secret_redaction(self):
        from django.views.debug import SafeExceptionReporterFilter
        data = {'username': 'other', 'password': 'wrong-secret', 'new_password1': 'secret-new', 'new_password2': 'secret-new'}
        self.assertEqual(self.client.post('/account/settings/', data).status_code, 403)
        response = self.client.post('/account/settings/', data)
        self.assertEqual(response.status_code, 429)
        filtered = str(SafeExceptionReporterFilter().get_post_parameters(response.wsgi_request))
        self.assertNotIn('wrong-secret', filtered)
        self.assertNotIn('secret-new', filtered)

    def test_audit_records_only_change_flags(self):
        from django.apps import apps
        self.assertTrue(any(m.__name__ == 'CredentialAudit' for m in apps.get_models()))
        self.client.post('/account/settings/', {'username': 'changed', 'password': self.password})
        from membership.models import CredentialAudit
        event = CredentialAudit.objects.get()
        self.assertEqual(event.actor_id, self.user.pk)
        self.assertTrue(event.username_changed)
        self.assertFalse(event.password_changed)
        self.assertNotIn(self.password, str(event.__dict__))

    def test_rejects_csrf_invalid_password_and_weak_mismatched_passwords(self):
        from django.test import Client as PlainClient
        csrf = PlainClient(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post('/account/settings/', {'username': 'changed', 'password': self.password}).status_code, 403)
        self.assertEqual(PlainClient().post('/account/settings/', {}).status_code, 302)
        self.assertEqual(self.client.put('/account/settings/').status_code, 405)
        before = (self.user.username, self.user.password)
        for first, second in [('short', 'short'), ('long-enough-but-mismatch', 'different'), (self.password, self.password)]:
            response = self.client.post('/account/settings/', {'username': 'changed', 'password': self.password, 'new_password1': first, 'new_password2': second})
            self.assertEqual(response.status_code, 400)
            self.user.refresh_from_db()
            self.assertEqual((self.user.username, self.user.password), before)

    def test_admin_requires_mfa_and_cannot_edit_privileges(self):
        from membership.models import AdminMFAPolicy
        AdminMFAPolicy.objects.filter(pk=1).update(required=True)
        from django.test import Client as PlainClient
        self.user.is_superuser = True
        self.user.save()
        plain = PlainClient()
        plain.force_login(self.user)
        self.assertEqual(plain.post('/account/settings/', {'username': 'changed', 'password': self.password}).status_code, 403)
        self.client.force_login(self.user)
        response = self.client.post('/account/settings/', {'username': 'changed', 'password': self.password, 'is_active': False, 'is_superuser': False, 'role': 'member', 'tenant': 999})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_superuser)
        self.assertTrue(self.user.is_active)
        self.assertEqual(self.client.get('/manage/').status_code, 200)
        self.member.refresh_from_db()
        self.assertEqual(self.member.tenant.name, 'owner')

    def test_normalized_duplicate_rejected_without_partial_password_change(self):
        User.objects.create_user('taken')
        import secrets
        new = secrets.token_urlsafe(24)
        response = self.client.post('/account/settings/', {'username': 'ｔａｋｅｎ', 'password': self.password, 'new_password1': new, 'new_password2': new})
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'original')
        self.assertTrue(self.user.check_password(self.password))

    def test_deleted_inflight_session_cannot_change_credentials(self):
        from django.contrib.sessions.models import Session
        from django.test import RequestFactory
        from membership.account_settings import settings_view
        request = RequestFactory().post('/account/settings/', {'username': 'stale', 'password': self.password})
        request.user = self.user
        request.session = self.client.session
        dict(request.session)
        Session.objects.filter(session_key=request.session.session_key).delete()
        self.assertEqual(settings_view(request).status_code, 403)

    def test_gate_rechecks_deleted_session_and_password_hash_after_policy_wait(self):
        from django.contrib.sessions.models import Session
        from django.test import RequestFactory
        from django.http import HttpResponse
        from membership.mfa_middleware import AdminMFAMiddleware
        for mutation in ('delete', 'password'):
            self.client.force_login(self.user)
            request = RequestFactory().get('/account/')
            request.user = self.user
            request.session = self.client.session
            dict(request.session)
            if mutation == 'delete':
                Session.objects.filter(session_key=request.session.session_key).delete()
            else:
                fresh = User.objects.get(pk=self.user.pk)
                fresh.set_unusable_password()
                fresh.save()
            response = AdminMFAMiddleware(lambda request: HttpResponse('private'))(request)
            self.assertEqual(response.status_code, 302)
            self.assertNotIn('_auth_user_id', request.session)

    def test_bootstrap_gate_is_rechecked_inside_mutation_boundary(self):
        from django.test import RequestFactory
        from membership.models import BootstrapAdmin
        from membership.views import approve
        self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        BootstrapAdmin.objects.create(user=self.user)
        request = RequestFactory().post('/manage/999/approve/', {'password': self.password})
        request.user = self.user
        request.session = self.client.session
        self.assertEqual(approve(request, 999).status_code, 403)

    def test_csrf_denial_redacts_credential_fields(self):
        from django.test import Client as PlainClient
        from django.views.debug import SafeExceptionReporterFilter
        browser = PlainClient(enforce_csrf_checks=True)
        browser.force_login(self.user)
        response = browser.post('/account/settings/', {'username': 'changed', 'password': self.password})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(self.password, str(SafeExceptionReporterFilter().get_post_parameters(response.wsgi_request)))

    def test_password_change_validates_and_updates_hash(self):
        import secrets
        new = secrets.token_urlsafe(24)
        response = self.client.post('/account/settings/', {'password': self.password, 'username': 'bothchanged', 'new_password1': new, 'new_password2': new})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new))
        self.assertFalse(self.user.check_password(self.password))
        self.assertEqual(self.client.get('/account/').status_code, 200)

