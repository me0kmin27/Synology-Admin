"""Real Chromium/HTTP, real no-I/O reader; no injected NAS observations."""
from django.contrib.auth.models import User
from tests.mfa_helpers import LiveServerTestCase, override_settings
from membership.models import Membership, Tenant
from playwright.sync_api import sync_playwright, expect


@override_settings(SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
                   MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True, STATIC_URL='/static/', MEDIA_URL='/media/')
class StorageBrowserTests(LiveServerTestCase):
    def test_unconnected_account_and_admin_group_with_real_login(self):
        password = 'Storage-browser-test-only-728!'
        tenant = Tenant.objects.create(name='Storage browser fixture', storage_limit_bytes=999888)
        users = []
        for role in ['member', 'admin']:
            user = User.objects.create_user('storage-' + role, password=password)
            Membership.objects.create(user=user, tenant=tenant, status='approved', role=role, quota_bytes=777666)
            users.append(user)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for user in users:
                context = browser.new_context()
                page = context.new_page()
                page.goto(self.live_server_url + '/login/')
                page.locator('[name=username]').fill(user.username)
                page.locator('[name=password]').fill(password)
                page.locator('button').click()
                if user.username.endswith('admin'):
                    from tests.mfa_helpers import browser_enroll
                    browser_enroll(page, password)
                    page.goto(self.live_server_url + '/account/')
                else:
                    page.wait_for_url('**/account/')
                page.get_by_role('link', name='서비스 상태').click()
                expect(page.get_by_role('heading', name='스토리지 대시보드')).to_be_visible()
                response = page.goto(self.live_server_url + '/service/?tenant=999&account=other&scope=volume')
                self.assertEqual(response.status, 200)
                self.assertIn('no-store', response.headers['cache-control'])
                expect(page.locator('body')).to_contain_text('NAS 미연결')
                expect(page.locator('[data-usage=account]')).to_contain_text(user.username)
                expect(page.locator('[data-usage=account] dd')).to_have_text([
                    '알 수 없음', '알 수 없음', '알 수 없음', '설정 안 됨', '관측 없음', '출처 없음'])
                expect(page.locator('[data-usage=group]')).to_have_count(1 if user.username.endswith('admin') else 0)
                expect(page.locator('body')).not_to_contain_text('777666')
                expect(page.locator('body')).not_to_contain_text('999888')
                context.close()
            browser.close()
        print('STORAGE BROWSER PASS: real login/HTTP; no-I/O reader unknown; own account; restricted group; forged scope ignored; no-store; no portal quotas presented as NAS data')
