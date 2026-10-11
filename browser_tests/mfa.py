"""Chromium enrollment, fail-closed gate and new-session challenge."""
from django.contrib.auth.models import User
from tests.mfa_helpers import LiveServerTestCase, override_settings, browser_enroll
from playwright.sync_api import sync_playwright, expect


@override_settings(SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
                   MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True, STATIC_URL='/static/', MEDIA_URL='/media/')
class MFABrowserTests(LiveServerTestCase):
    def test_real_enrollment_gate_logout_and_replay(self):
        password = 'Browser-only-MFA-passphrase-827!'
        User.objects.create_superuser('browser-mfa', password=password)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context()
            page = context.new_page()
            page.goto(self.live_server_url + '/login/')
            page.locator('[name=username]').fill('browser-mfa')
            page.locator('[name=password]').fill(password)
            page.locator('button').click()
            seed = browser_enroll(page, password)
            expect(page.get_by_role('heading', name='회원 관리')).to_be_visible()
            page.goto(self.live_server_url + '/account/')
            page.get_by_role('button', name='로그아웃').click()
            page.wait_for_url('**/login/')
            page.locator('[name=username]').fill('browser-mfa')
            page.locator('[name=password]').fill(password)
            page.locator('button').click()
            page.wait_for_url('**/mfa/verify/')
            expect(page.locator('#otp-seed')).to_have_count(0)
            response = page.goto(self.live_server_url + '/manage/')
            self.assertTrue(page.url.endswith('/mfa/verify/'))
            self.assertIn('no-store', response.headers['cache-control'])
            browser.close()
        print('MFA BROWSER PASS: password login gated; enrollment seed only on protected response; OTP confirms; logout/new login requires fresh OTP')
