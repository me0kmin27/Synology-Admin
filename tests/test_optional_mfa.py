"""Optional enrollment policy acceptance with disposable identities only."""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from membership.models import AdminOTPDevice, BootstrapAdmin


@override_settings(SECURE_SSL_REDIRECT=False, MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True)
class OptionalMFATests(TestCase):
    def test_global_owner_can_discover_policy_and_opt_in_enrollment(self):
        user = User.objects.create_superuser('ui-owner')
        self.client.force_login(user)
        response = self.client.get('/manage/')
        self.assertContains(response, 'href="/manage/mfa-policy/"')
        self.assertContains(response, 'href="/mfa/enroll/"')

    def test_enrollment_post_contains_local_qr_but_get_never_reveals_it(self):
        from cryptography.fernet import Fernet
        from unittest.mock import patch
        with override_settings(MFA_ENCRYPTION_KEYS=[Fernet.generate_key().decode()]):
            user = User.objects.create_superuser('테스트+owner@example.com', password='Disposable-QR-password-823!')
            self.client.force_login(user)
            with patch('membership.mfa.random_hex', return_value='11' * 20):
                response = self.client.post('/mfa/enroll/', {'password': 'Disposable-QR-password-823!'})
            self.assertContains(response, '<svg')
            self.assertContains(response, 'id="otp-qr"')
            self.assertNotContains(response, '<img')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertNotContains(self.client.get('/mfa/enroll/'), '<svg')
            self.assertEqual(self.client.post('/mfa/enroll/', {'password': 'Disposable-QR-password-823!'}).status_code, 409)

    def test_global_owner_enables_with_fresh_otp_and_steps_up_other_admins(self):
        from cryptography.fernet import Fernet
        from django.test import Client
        from django_otp.oath import TOTP
        from membership.models import AdminMFAPolicy
        from tests.mfa_helpers import fixture_device
        with override_settings(MFA_ENCRYPTION_KEYS=[Fernet.generate_key().decode()]):
            owner = User.objects.create_superuser('policy-owner', password='Disposable-policy-password-823!')
            self.client.force_login(owner)
            device = fixture_device(owner)
            token = f'{TOTP(device.bin_key).token():06d}'
            # A password-only actor with confirmed device must challenge first.
            self.assertEqual(self.client.post('/mfa/verify/', {'token': token}).status_code, 302)
            other = Client()
            other.force_login(User.objects.create_superuser('another-owner'))
            self.assertEqual(other.get('/manage/').status_code, 200)
            from unittest.mock import patch
            device.refresh_from_db()
            with patch('django_otp.oath.time', return_value=(device.last_t + 1) * 30):
                token = f'{TOTP(device.bin_key).token():06d}'
                response = self.client.post('/manage/mfa-policy/', {
                    'required': 'on', 'password': 'Disposable-policy-password-823!', 'token': token,
                })
            self.assertEqual(response.status_code, 302)
            policy = AdminMFAPolicy.objects.get(pk=1)
            self.assertTrue(policy.required)
            self.assertEqual(policy.version, 2)
            self.assertEqual(other.get('/manage/').url, '/mfa/enroll/')
            self.assertEqual(self.client.get('/manage/').status_code, 200)

    def test_bootstrap_changes_initial_password_without_enrollment_by_default(self):
        user = User.objects.create_superuser('optional-owner', password='Disposable-owner-password-823!')
        BootstrapAdmin.objects.create(user=user)
        self.assertTrue(self.client.login(username=user.username, password='Disposable-owner-password-823!'))
        self.assertRedirects(self.client.get('/manage/'), '/account/settings/')
        response = self.client.post('/account/settings/', {
            'username': user.username, 'password': 'Disposable-owner-password-823!',
            'new_password1': 'Changed-disposable-owner-947!',
            'new_password2': 'Changed-disposable-owner-947!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get('/manage/').status_code, 200)
        self.assertFalse(AdminOTPDevice.objects.exists())
        self.assertFalse(BootstrapAdmin.objects.get(user=user).must_change_password)
