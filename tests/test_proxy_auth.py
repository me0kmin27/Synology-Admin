"""Production-security HTTP flow, without MFA test-client shortcuts."""
from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django_otp.oath import TOTP


@override_settings(
    ALLOWED_HOSTS=['test.keiminem.com'],
    CSRF_TRUSTED_ORIGINS=['https://test.keiminem.com'],
    TRUSTED_PROXY_NETWORKS=['192.168.1.142/32'],
    SECURE_SSL_REDIRECT=True, SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True,
    MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True,
)
class ProxyAuthTests(TestCase):
    @override_settings(SECURE_SSL_REDIRECT=False, AUTH_ATTEMPT_LIMIT=2)
    def test_untrusted_forwarded_ip_cannot_evade_transport_ip_throttle(self):
        client = Client(HTTP_HOST='test.keiminem.com', REMOTE_ADDR='192.168.1.141')
        for index, expected in enumerate([200, 200, 429]):
            response = client.post('/login/', {'username': f'missing-{index}', 'password': 'invalid'},
                                   HTTP_X_FORWARDED_FOR=f'203.0.113.{index + 1}', HTTP_X_FORWARDED_PROTO='https')
            self.assertEqual(response.status_code, expected)

    def test_csrf_login_enrollment_otp_and_secure_cookies(self):
        from membership.models import AdminMFAPolicy
        AdminMFAPolicy.objects.filter(pk=1).update(required=True)
        with override_settings(MFA_ENCRYPTION_KEYS=[Fernet.generate_key().decode()]):
            User.objects.create_superuser('proxy-admin', password='Disposable-proxy-test-823!')
            client = Client(enforce_csrf_checks=True,
                            HTTP_HOST='test.keiminem.com', REMOTE_ADDR='192.168.1.142',
                            HTTP_X_FORWARDED_PROTO='https', HTTP_X_FORWARDED_FOR='203.0.113.7')
            self.assertEqual(client.get('/login/').status_code, 200)
            self.assertTrue(client.cookies['csrftoken']['secure'])
            credentials = {'username': 'proxy-admin', 'password': 'Disposable-proxy-test-823!'}
            self.assertEqual(client.post('/login/', credentials, HTTP_ORIGIN='https://test.keiminem.com').status_code, 403)

            def post(path, data, origin='https://test.keiminem.com'):
                return client.post(path, {**data, 'csrfmiddlewaretoken': client.cookies['csrftoken'].value}, HTTP_ORIGIN=origin)

            for origin in ['https://evil.invalid', 'http://test.keiminem.com', 'https://test.keiminem.com:8443', 'https://test.keiminem.com,https://evil.invalid']:
                self.assertEqual(post('/login/', credentials, origin).status_code, 403)
            login = post('/login/', credentials)
            self.assertEqual(login.status_code, 302)
            self.assertTrue(login.cookies['sessionid']['secure'])
            self.assertEqual(client.get('/manage/').url, '/mfa/enroll/')
            self.assertEqual(post('/mfa/enroll/', {'password': credentials['password']}).status_code, 200)
            from membership.models import AdminOTPDevice
            device = AdminOTPDevice.objects.get(user__username='proxy-admin')
            self.assertEqual(client.get('/manage/').url, '/mfa/verify/')
            otp = post('/mfa/verify/', {'token': f'{TOTP(device.bin_key).token():06d}'})
            self.assertEqual(otp.status_code, 302)
            self.assertTrue(otp.cookies['sessionid']['secure'])
            self.assertEqual(client.get('/manage/').status_code, 200)
