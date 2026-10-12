"""Authorization negatives use plain clients, not automatic MFA fixtures."""
from unittest.mock import patch
from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import get_resolver
from django_otp.oath import TOTP
from membership.models import AdminMFAPolicy, AdminOTPDevice, MFAPolicyAudit, Membership, Tenant
from tests.mfa_helpers import fixture_device


@override_settings(SECURE_SSL_REDIRECT=False, MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True, AUTH_ATTEMPT_LIMIT=1000)
class PolicySecurityTests(TestCase):
    password = 'Disposable-policy-password-823!'

    def setUp(self):
        keys = override_settings(MFA_ENCRYPTION_KEYS=[Fernet.generate_key().decode()])
        keys.enable()
        self.addCleanup(keys.disable)
        self.owner = User.objects.create_superuser('policy-owner', password=self.password)
        self.client.force_login(self.owner)

    def confirm(self, user=None, client=None):
        device = fixture_device(user or self.owner)
        client = client or self.client
        with patch('django_otp.oath.time', return_value=max(2000000000, (device.last_t + 1) * 30)):
            token = f'{TOTP(device.bin_key).token():06d}'
            self.assertEqual(client.post('/mfa/verify/', {'token': token}).status_code, 302)
        return device

    def toggle(self, required, device=None, **overrides):
        data = {'password': self.password, 'required': 'on' if required else ''}
        if device:
            device.refresh_from_db()
            with patch('django_otp.oath.time', return_value=(device.last_t + 1) * 30):
                data['token'] = f'{TOTP(device.bin_key).token():06d}'
                data.update(overrides)
                return self.client.post('/manage/mfa-policy/', data)
        data.update(overrides)
        return self.client.post('/manage/mfa-policy/', data)

    def test_optional_stale_policy_session_reauthenticates_without_forcing_enrollment(self):
        AdminMFAPolicy.objects.filter(pk=1).update(version=2)
        self.assertEqual(self.client.get('/manage/').url, '/login/')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/manage/').status_code, 200)
        self.assertFalse(AdminOTPDevice.objects.exists())

    def test_missing_policy_row_fails_closed_without_recreating_optional_default(self):
        AdminMFAPolicy.objects.all().delete()
        self.assertEqual(self.client.get('/manage/').status_code, 503)
        self.assertFalse(AdminMFAPolicy.objects.exists())

    def test_confirmed_opt_in_is_never_disabled_by_optional_policy(self):
        device = self.confirm()
        other = Client()
        other.force_login(self.owner)
        for path in ('/manage/', '/account/settings/', '/account/', '/'):
            self.assertEqual(other.get(path).url, '/mfa/verify/')
            self.assertEqual(other.post(path, {'password': self.password, 'username': 'downgrade'}).status_code, 403)
        self.assertEqual(self.client.get('/manage/').status_code, 200)
        self.assertFalse(AdminMFAPolicy.objects.get(pk=1).required)
        self.assertTrue(AdminOTPDevice.objects.get(pk=device.pk).confirmed)

    def test_enabling_requires_confirmed_device_without_auto_creation(self):
        self.assertEqual(self.toggle(True).status_code, 403)
        self.assertFalse(AdminOTPDevice.objects.exists())
        self.client.post('/mfa/enroll/', {'password': self.password})
        self.assertEqual(self.toggle(True).status_code, 403)
        self.assertFalse(AdminMFAPolicy.objects.get(pk=1).required)
        self.assertFalse(MFAPolicyAudit.objects.exists())

    def test_policy_is_globaladmin_only_csrf_protected_and_nonmutating_get(self):
        self.assertEqual(Client().get('/manage/mfa-policy/').status_code, 302)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        self.assertEqual(csrf.post('/manage/mfa-policy/', {'password': self.password}).status_code, 403)
        self.assertEqual(self.client.get('/manage/mfa-policy/').status_code, 200)
        self.assertEqual(self.client.put('/manage/mfa-policy/').status_code, 405)
        tenant = Tenant.objects.create(name='security')
        group = User.objects.create_user('group', password=self.password)
        Membership.objects.create(user=group, tenant=tenant, role='admin', status='approved')
        staff = User.objects.create_user('staff', is_staff=True)
        member = User.objects.create_user('member')
        for user in (group, staff, member):
            client = Client()
            client.force_login(user)
            for method in ('get', 'post'):
                self.assertEqual(getattr(client, method)('/manage/mfa-policy/', {'password': self.password}).status_code, 403)
        self.assertFalse(MFAPolicyAudit.objects.exists())

    def test_wrong_and_weak_current_password_cannot_toggle(self):
        device = self.confirm()
        self.assertEqual(self.toggle(True, device, password='wrong').status_code, 403)
        self.owner.set_password('short')
        self.owner.save()
        self.client.force_login(self.owner)
        self.confirm()
        self.assertEqual(self.toggle(True, device, password='short').status_code, 400)
        self.assertFalse(AdminMFAPolicy.objects.get(pk=1).required)

    def test_disable_requires_new_one_use_otp_old_policy_and_audit(self):
        device = self.confirm()
        self.assertEqual(self.toggle(True, device).status_code, 302)
        device.refresh_from_db()
        with patch('django_otp.oath.time', return_value=device.last_t * 30):
            replay = f'{TOTP(device.bin_key).token():06d}'
            self.assertEqual(self.toggle(False, token=replay).status_code, 403)
        device.refresh_from_db()
        self.assertEqual(device.throttling_failure_count, 1)
        self.assertTrue(AdminMFAPolicy.objects.get(pk=1).required)
        self.assertEqual(self.toggle(False, device).status_code, 429)
        device.throttle_reset()
        self.assertEqual(self.toggle(False, device).status_code, 302)
        policy = AdminMFAPolicy.objects.get(pk=1)
        self.assertFalse(policy.required)
        self.assertEqual(policy.version, 3)
        self.assertEqual(list(MFAPolicyAudit.objects.values_list('previous', 'required', 'version')), [(False, True, 2), (True, False, 3)])
        self.assertEqual(AdminOTPDevice.objects.count(), 1)
        other = Client()
        other.force_login(self.owner)
        self.assertEqual(other.get('/manage/').url, '/mfa/verify/')

    def test_enabling_steps_up_every_admin_role_route_and_stale_inner_mutation(self):
        tenant = Tenant.objects.create(name='routes', max_accounts=100)
        group = User.objects.create_user('group-admin', password=self.password)
        Membership.objects.create(user=group, tenant=tenant, role='admin', status='approved')
        staff = User.objects.create_user('staff', is_staff=True, password=self.password)
        users = [self.owner, group, staff]
        clients = []
        for user in users:
            browser = Client()
            browser.force_login(user)
            clients.append(browser)
        subject = Membership.objects.create(user=User.objects.create_user('subject'), tenant=tenant)
        request = RequestFactory().post(f'/manage/{subject.pk}/approve/', {'password': self.password})
        request.user = self.owner
        request.session = clients[0].session
        dict(request.session)  # deliberately materialize stale cache before toggle
        self.assertEqual(self.toggle(True, self.confirm()).status_code, 302)
        from membership.views import approve
        self.assertEqual(approve(request, subject.pk).status_code, 403)
        subject.refresh_from_db()
        self.assertEqual(subject.status, 'pending')
        safe = {'mfa/enroll/', 'mfa/verify/', 'login/', 'logout/', 'health/'}
        for browser in clients:
            for route in get_resolver().url_patterns:
                path = str(route.pattern).replace('<int:pk>', '1')
                if path in safe:
                    continue
                with self.subTest(route=path):
                    self.assertEqual(browser.get('/' + path).status_code, 302)
                    self.assertEqual(browser.post('/' + path).status_code, 403)
        ordinary = Client()
        ordinary.force_login(subject.user)
        self.assertEqual(ordinary.get('/account/').status_code, 200)

    def test_optional_credentials_and_mutations_reject_deleted_or_changed_sessions(self):
        from membership.views import approve
        from membership.account_settings import settings_view
        for kind in ('deleted', 'hash', 'role', 'version'):
            self.client.force_login(self.owner)
            request = RequestFactory().post('/account/settings/', {'password': self.password, 'username': 'forbidden'})
            request.user = self.owner
            request.session = self.client.session
            dict(request.session)
            if kind == 'deleted':
                Session.objects.filter(session_key=request.session.session_key).delete()
            elif kind == 'hash':
                request.session['_auth_user_hash'] = 'stale'
            elif kind == 'role':
                request.session['auth_scope'] = []
            else:
                request.session['mfa_policy_version'] = 0
            self.assertEqual(settings_view(request).status_code, 403)
            self.assertEqual(approve(request, 999).status_code, 403)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.username, 'policy-owner')

    def test_csrf_policy_denial_redacts_before_throttle_and_view(self):
        from django.views.debug import SafeExceptionReporterFilter
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.owner)
        response = browser.post('/manage/mfa-policy/', {'password': self.password, 'token': '123456'})
        self.assertEqual(response.status_code, 403)
        text = str(SafeExceptionReporterFilter().get_post_parameters(response.wsgi_request))
        self.assertNotIn(self.password, text)
        self.assertNotIn('123456', text)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    @override_settings(AUTH_ATTEMPT_LIMIT=0)
    def test_policy_throttle_redacts_password_and_token(self):
        from django.views.debug import SafeExceptionReporterFilter
        response = self.client.post('/manage/mfa-policy/', {'password': self.password, 'token': '123456'})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        text = str(SafeExceptionReporterFilter().get_post_parameters(response.wsgi_request))
        self.assertNotIn(self.password, text)
        self.assertNotIn('123456', text)
