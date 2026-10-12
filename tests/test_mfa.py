"""Real HTTP MFA acceptance; only disposable test secrets."""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from cryptography.fernet import Fernet


@override_settings(SECURE_SSL_REDIRECT=False, MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True)
class MFATests(TestCase):
    def setUp(self):
        from membership.models import AdminMFAPolicy
        AdminMFAPolicy.objects.filter(pk=1).update(required=True)
        self.keys = override_settings(MFA_ENCRYPTION_KEYS=[Fernet.generate_key().decode()])
        self.keys.enable()
        self.addCleanup(self.keys.disable)
        self.user = User.objects.create_superuser('otp-admin', password='Disposable-password-823!')
        self.client.force_login(self.user)

    def enroll(self):
        self.assertEqual(self.client.post('/mfa/enroll/', {'password': 'Disposable-password-823!'}).status_code, 200)
        from membership.models import AdminOTPDevice
        return AdminOTPDevice.objects.get(user=self.user)

    def token(self, device):
        from django_otp.oath import TOTP
        return f'{TOTP(device.bin_key).token():06d}'

    def test_confirmation_rotates_session_and_replay_failure_commits(self):
        device = self.enroll()
        old = self.client.session.session_key
        token = self.token(device)
        response = self.client.post('/mfa/verify/', {'token': token})
        self.assertEqual(response.status_code, 302)
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertGreater(device.last_t, -1)
        self.assertNotEqual(old, self.client.session.session_key)
        self.assertEqual(self.client.post('/mfa/verify/', {'token': token}).status_code, 403)
        device.refresh_from_db()
        self.assertEqual(device.throttling_failure_count, 1)
        self.assertEqual(self.client.post('/mfa/verify/', {'token': token}).status_code, 429)

    def test_pending_enrollment_is_bound_to_session_and_expires(self):
        from django.test import Client
        from django.utils import timezone
        from datetime import timedelta
        device = self.enroll()
        other = Client()
        other.force_login(self.user)
        self.assertEqual(other.post('/mfa/verify/', {'token': self.token(device)}).status_code, 403)
        device.refresh_from_db()
        self.assertFalse(device.confirmed)
        device.created_at = timezone.now() - timedelta(seconds=301)
        device.save(update_fields=['created_at'])
        self.assertEqual(self.client.post('/mfa/verify/', {'token': self.token(device)}).status_code, 403)
        self.assertEqual(self.client.post('/mfa/enroll/', {'password': 'Disposable-password-823!'}).status_code, 200)

    def test_password_only_administrators_are_gated_on_all_routes(self):
        from membership.models import Membership, Tenant
        from django.urls import get_resolver
        tenant = Tenant.objects.create(name='MFA tenant')
        group = User.objects.create_user('group-admin')
        Membership.objects.create(user=group, tenant=tenant, role='admin', status='approved')
        safe = {'mfa/enroll/', 'mfa/verify/', 'login/', 'logout/', 'health/'}
        for user in (self.user, group):
            self.client.force_login(user)
            for route in get_resolver().url_patterns:
                path = str(route.pattern).replace('<int:pk>', '1')
                if path in safe:
                    continue
                for method in ('get', 'post'):
                    with self.subTest(user=user.username, route=path, method=method):
                        response = getattr(self.client, method)('/' + path)
                        self.assertEqual(response.status_code, 302 if method == 'get' else 403)
                        if method == 'get':
                            self.assertEqual(response.url, '/mfa/enroll/')
        self.client.force_login(self.user)
        device = self.enroll()
        self.assertEqual(self.client.get('/manage/').url, '/mfa/verify/')
        self.assertEqual(self.client.post('/mfa/verify/', {'token': self.token(device)}).status_code, 302)
        self.assertEqual(self.client.get('/manage/').status_code, 200)

    def test_mfa_expiry_key_loss_and_role_device_changes_fail_closed(self):
        from django.utils import timezone
        device = self.enroll()
        self.client.post('/mfa/verify/', {'token': self.token(device)})
        session = self.client.session
        session['mfa_at'] = timezone.now().timestamp() - 901
        session.save()
        self.assertEqual(self.client.get('/manage/').status_code, 302)
        session = self.client.session
        session['mfa_at'] = timezone.now().timestamp()
        session.save()
        with override_settings(MFA_ENCRYPTION_KEYS=[]):
            self.assertEqual(self.client.get('/manage/').status_code, 503)
        self.user.is_staff = False
        self.user.save(update_fields=['is_staff'])
        self.assertEqual(self.client.get('/manage/').status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.client.force_login(self.user)
        device.delete()
        self.assertEqual(self.client.get('/manage/').url, '/mfa/enroll/')

    @override_settings(AUTH_ATTEMPT_LIMIT=2)
    def test_enrollment_password_throttle_is_shared_across_sessions(self):
        from django.test import Client
        for _ in range(2):
            other = Client()
            other.force_login(self.user)
            self.assertEqual(other.post('/mfa/enroll/', {'password': 'wrong'}).status_code, 403)
        self.assertEqual(self.client.post('/mfa/enroll/', {'password': 'wrong'}).status_code, 429)

    @override_settings(AUTH_ATTEMPT_LIMIT=0)
    def test_throttle_denial_redacts_sensitive_post_before_view(self):
        from django.views.debug import SafeExceptionReporterFilter
        response = self.client.post('/mfa/enroll/', {'password': 'never-report-me', 'token': '123456'})
        self.assertEqual(response.status_code, 429)
        filtered = SafeExceptionReporterFilter().get_post_parameters(response.wsgi_request)
        self.assertNotIn('never-report-me', str(filtered))
        self.assertNotIn('123456', str(filtered))
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_confirmed_device_cannot_be_reenrolled_and_new_login_needs_fresh_otp(self):
        from django.test import Client
        from unittest.mock import patch
        from django_otp.oath import TOTP
        device = self.enroll()
        self.client.post('/mfa/verify/', {'token': self.token(device)})
        self.assertEqual(self.client.post('/mfa/enroll/', {'password': 'Disposable-password-823!'}).status_code, 409)
        other = Client()
        other.force_login(self.user)
        self.assertEqual(other.get('/manage/').url, '/mfa/verify/')
        device.refresh_from_db()
        instant = (device.last_t + 1) * 30
        with patch('django_otp.oath.time', return_value=instant):
            self.assertEqual(other.post('/mfa/verify/', {'token': f'{TOTP(device.bin_key).token():06d}'}).status_code, 302)
        self.assertEqual(other.get('/manage/').status_code, 200)
        device.delete()
        for browser in (self.client, other):
            self.assertEqual(browser.get('/manage/').status_code, 302)
            self.assertNotIn('_auth_user_id', browser.session)

    def test_invalid_keys_tamper_and_cross_row_ciphertext_fail_closed(self):
        from membership.models import AdminOTPDevice
        device = self.enroll()
        original = device.ciphertext
        for keys in ([], ['invalid-key'], [Fernet.generate_key().decode()]):
            with self.subTest(key_case=len(keys)), override_settings(MFA_ENCRYPTION_KEYS=keys):
                self.assertEqual(self.client.post('/mfa/verify/', {'token': '123456'}).status_code, 503)
        device.ciphertext = original[:-5] + 'AAAAA'
        device.save()
        self.assertEqual(self.client.post('/mfa/verify/', {'token': '123456'}).status_code, 503)
        from membership.mfa_crypto import SeedUnavailable
        other = AdminOTPDevice(user=User.objects.create_superuser('ciphertext-recipient'), ciphertext=original)
        other.save()
        with self.assertRaises(SeedUnavailable):
            other.bin_key
        device.refresh_from_db()
        self.assertFalse(device.confirmed)
        self.assertEqual(device.last_t, -1)

    def test_csrf_anonymous_and_non_admin_enrollment_denied(self):
        from django.test import Client
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        for path in ('/mfa/enroll/', '/mfa/verify/'):
            self.assertEqual(csrf.post(path, {'password': 'Disposable-password-823!', 'token': '123456'}).status_code, 403)
            self.assertEqual(Client().get(path).status_code, 302)
        self.client.force_login(User.objects.create_user('ordinary'))
        self.assertEqual(self.client.post('/mfa/enroll/', {'password': 'x'}).status_code, 403)

    def test_management_mutation_rechecks_mfa_inside_authorization_boundary(self):
        from django.test import RequestFactory
        from membership.views import approve
        from membership.models import Membership, Tenant
        tenant = Tenant.objects.create(name='Locked MFA scope', max_accounts=10)
        subject = Membership.objects.create(user=User.objects.create_user('approval-target'), tenant=tenant)
        request = RequestFactory().post(f'/manage/{subject.pk}/approve/', {'password': 'Disposable-password-823!'})
        request.user = self.user
        request.session = self.client.session
        self.assertEqual(approve(request, subject.pk).status_code, 403)
        subject.refresh_from_db()
        self.assertEqual(subject.status, 'pending')

    def test_enrollment_requires_password_and_stores_only_bound_ciphertext(self):
        response = self.client.post('/mfa/enroll/', {'password': 'wrong'})
        self.assertEqual(response.status_code, 403)
        response = self.client.post('/mfa/enroll/', {'password': 'Disposable-password-823!'})
        self.assertEqual(response.status_code, 200)
        from membership.models import AdminOTPDevice
        device = AdminOTPDevice.objects.get(user=self.user)
        self.assertFalse(device.confirmed)
        self.assertEqual(device.last_t, -1)
        import base64
        seed = base64.b32encode(device.bin_key).decode()
        self.assertContains(response, seed)
        self.assertNotIn(seed, device.ciphertext)
        self.assertNotIn(device.bin_key.hex(), device.ciphertext)
        self.assertNotIn('key', [field.name for field in device._meta.fields])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertNotIn(seed, str(dict(self.client.session)))
