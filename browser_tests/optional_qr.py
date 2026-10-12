"""Real Chromium pixels decoded independently; only a fixed synthetic seed."""
import base64
import io
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlparse
from PIL import Image
import zxingcpp
from django.contrib.auth.models import User
from django_otp.oath import TOTP
from membership.models import AdminMFAPolicy
from tests.mfa_helpers import LiveServerTestCase, override_settings
from playwright.sync_api import sync_playwright, expect


@override_settings(SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
                   MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True, STATIC_URL='/static/', MEDIA_URL='/media/')
class OptionalQRBrowserTests(LiveServerTestCase):
    def test_real_post_qr_decodes_exact_synthetic_uri_under_csp(self):
        AdminMFAPolicy.objects.filter(pk=1).update(required=False)
        username = '테스트+owner@example.com'
        password = 'Browser-only-optional-passphrase-827!'
        User.objects.create_superuser(username, password=password)
        fake_seed = bytes.fromhex('11' * 20)
        with patch('membership.mfa.random_hex', return_value=fake_seed.hex()), sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 390, 'height': 844})
            page = context.new_page()
            external = []
            page.on('request', lambda request: external.append(request.url) if not request.url.startswith(self.live_server_url + '/') else None)

            def csp_response(route):
                response = route.fetch()
                route.fulfill(response=response, headers={**response.headers,
                    'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'"})

            page.route('**/mfa/enroll/', csp_response)
            page.goto(self.live_server_url + '/login/')
            page.locator('[name=username]').fill(username)
            page.locator('[name=password]').fill(password)
            page.locator('button').click()
            page.wait_for_url('**/account/')
            page.goto(self.live_server_url + '/manage/')
            expect(page.get_by_role('heading', name='회원 관리')).to_be_visible()
            page.get_by_role('link', name='내 OTP 등록').click()
            expect(page.locator('#otp-qr')).to_have_count(0)
            page.locator('[name=password]').fill(password)
            with page.expect_response(lambda r: r.url.endswith('/mfa/enroll/') and r.request.method == 'POST') as response_info:
                page.get_by_role('button', name='등록 시작').click()
            self.assertEqual(response_info.value.status, 200)
            self.assertIn('no-store', response_info.value.headers['cache-control'])
            expect(page.locator('#otp-qr')).to_be_visible()
            png = page.locator('#otp-qr').screenshot()
            decoded = zxingcpp.read_barcode(Image.open(io.BytesIO(png)))
            self.assertIsNotNone(decoded, 'Actual browser QR pixels could not be decoded')
            uri = urlparse(decoded.text)
            self.assertEqual((uri.scheme, uri.netloc), ('otpauth', 'totp'))
            self.assertEqual(unquote(uri.path), '/Synology-Admin:' + username)
            self.assertIn('%2B', uri.path)
            self.assertIn('%40', uri.path)
            self.assertEqual(parse_qs(uri.query), {
                'secret': [base64.b32encode(fake_seed).decode()], 'issuer': ['Synology-Admin'],
                'algorithm': ['SHA1'], 'digits': ['6'], 'period': ['30'],
            })
            self.assertEqual(external, [])
            self.assertLessEqual(page.locator('#otp-qr').bounding_box()['width'], 310)
            path = Path('.runtime/optional-qr-synthetic.png')
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(png)  # synthetic seed only; never save production enrollment
            page.locator('[name=token]').fill(f'{TOTP(fake_seed).token():06d}')
            page.get_by_role('button', name='OTP 확인').click()
            page.wait_for_url('**/manage/')
            page.goto(self.live_server_url + '/mfa/enroll/')
            expect(page.locator('#otp-qr')).to_have_count(0)
            page.goto(self.live_server_url + '/account/')
            page.get_by_role('button', name='로그아웃').click()
            page.wait_for_url('**/login/')
            page.locator('[name=username]').fill(username)
            page.locator('[name=password]').fill(password)
            page.locator('button').click()
            page.wait_for_url('**/mfa/verify/')
            browser.close()
        print('OPTIONAL QR BROWSER PASS: actual POST SVG pixels decoded; exact synthetic URI; CSP; no external requests; confirmed opt-in challenges new login')
