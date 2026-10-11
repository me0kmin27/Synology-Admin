"""Test-only pre-enrolled fixtures; never imported by the application.

Existing privilege tests still exercise the real HTTP OTP challenge. MFA
acceptance uses the unmodified Django Client to test password-only denial.
"""
import time
from unittest.mock import patch
from cryptography.fernet import Fernet
from django.test import (Client as DjangoClient, TestCase as DjangoTestCase,
                         TransactionTestCase as DjangoTransactionTestCase,
                         LiveServerTestCase as DjangoLiveServerTestCase,
                         RequestFactory, SimpleTestCase, override_settings)
from django_otp.oath import TOTP
from django_otp.util import random_hex

TEST_KEY = Fernet.generate_key().decode()


def fixture_device(user):
    from membership.models import AdminOTPDevice
    from membership.mfa_crypto import seal
    device = AdminOTPDevice.objects.filter(user=user).first()
    if not device:
        device = AdminOTPDevice(user=user, name='Disposable test authenticator', confirmed=True)
        device.ciphertext = seal(device, bytes.fromhex(random_hex(20)))
        device.save()
    return device


def browser_enroll(page, password):
    import base64
    page.wait_for_url('**/mfa/enroll/')
    page.locator('[name=password]').fill(password)
    page.get_by_role('button', name='등록 시작').click()
    seed = base64.b32decode(page.locator('#otp-seed').inner_text())
    page.locator('[name=token]').fill(f'{TOTP(seed).token():06d}')
    page.get_by_role('button', name='OTP 확인').click()
    page.wait_for_url('**/manage/')
    return seed


class Client(DjangoClient):
    def force_login(self, user, backend=None):
        super().force_login(user, backend)
        from membership.mfa import is_admin
        if not is_admin(user):
            return
        device = fixture_device(user)
        # Distinct valid timestep for each test fixture login, not a gate bypass.
        instant = max(time.time(), (device.last_t + 1) * 30)
        generator = TOTP(device.bin_key)
        generator.time = instant
        with patch('django_otp.oath.time', return_value=instant):
            self.get('/mfa/verify/')
            data = {'token': f'{generator.token():06d}'}
            if 'csrftoken' in self.cookies:
                data['csrfmiddlewaretoken'] = self.cookies['csrftoken'].value
            response = self.post('/mfa/verify/', data)
        if response.status_code != 302 or response.url != '/manage/':
            raise AssertionError(f'Test OTP challenge failed: {response.status_code}')


@override_settings(MFA_ENCRYPTION_KEYS=[TEST_KEY])
class TestCase(DjangoTestCase):
    client_class = Client


@override_settings(MFA_ENCRYPTION_KEYS=[TEST_KEY])
class TransactionTestCase(DjangoTransactionTestCase):
    client_class = Client


@override_settings(MFA_ENCRYPTION_KEYS=[TEST_KEY])
class LiveServerTestCase(DjangoLiveServerTestCase):
    client_class = Client
