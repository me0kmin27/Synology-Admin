"""Real HTTP MFA acceptance; only disposable test secrets."""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from cryptography.fernet import Fernet


@override_settings(SECURE_SSL_REDIRECT=False, MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True)
class MFATests(TestCase):
    def setUp(self):
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
