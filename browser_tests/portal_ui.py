"""Real HTTP/Chromium UI acceptance. All accounts are disposable test fixtures."""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright, expect
from tests.mfa_helpers import LiveServerTestCase, override_settings


@override_settings(SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False,
                   CSRF_COOKIE_SECURE=False, MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True,
                   STATIC_URL='/static/', MEDIA_URL='/media/')
class PortalUIBrowserTests(LiveServerTestCase):
    def test_responsive_keyboard_shell(self):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width in (1440, 390):
                page = browser.new_page(viewport={'width': width, 'height': 960})
                page.goto(self.live_server_url + '/')
                expect(page.locator('main#main-content')).to_be_visible()
                page.keyboard.press('Tab')
                expect(page.get_by_role('link', name='본문으로 건너뛰기')).to_be_focused()
                page.keyboard.press('Enter')
                expect(page.locator('main#main-content')).to_be_focused()
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                expect(page.get_by_role('navigation', name='주 메뉴')).to_be_visible()
                expect(page.locator('body')).to_contain_text('NAS 연결 안 됨')
                page.close()
            browser.close()

    def test_all_pages_real_forms_and_screenshots(self):
        import base64
        from django.contrib.auth.models import User
        from django_otp.oath import TOTP
        from membership.models import Membership, Tenant
        from support.models import Ticket
        from chat.models import Conversation

        password = 'UI-disposable-test-only-783!'
        tenant = Tenant.objects.create(name='브라우저 검증 그룹 (테스트)', max_accounts=20)
        admin = User.objects.create_superuser('ui-admin-test', password=password)
        Membership.objects.create(user=admin, tenant=tenant, status='approved', role='admin')
        approved = User.objects.create_user('ui-approved-test', password=password)
        Membership.objects.create(user=approved, tenant=tenant, status='approved')
        artifacts = Path(os.environ.get('UI_SCREENSHOT_DIR', '.runtime/ui-screenshots'))
        artifacts.mkdir(parents=True, exist_ok=True)
        records, errors, external = [], [], []

        def db_call(function):
            # Playwright owns an event loop; keep sync ORM on a worker.
            from concurrent.futures import ThreadPoolExecutor
            from django.db import connections
            def run():
                try:
                    return function()
                finally:
                    connections.close_all()
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(run).result(timeout=10)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: external.append(request.url) if not request.url.startswith(self.live_server_url) else None)

            def capture(name):
                from urllib.parse import urlparse
                expected_paths = {
                    'landing': '/', 'signup': '/signup/', 'login': '/login/',
                    'login-error': '/login/', 'account-pending': '/account/',
                    'account-approved': '/account/', 'service': '/service/',
                    'service-admin': '/service/', 'support-empty': '/support/',
                    'support-form': '/support/new/', 'support-list': '/support/',
                    'chat-empty': '/chat/', 'chat-list': '/chat/',
                    'mfa-enroll': '/mfa/enroll/', 'mfa-verify': '/mfa/enroll/',
                    'manage': '/manage/', 'mfa-challenge': '/mfa/verify/',
                    'settings': '/account/settings/', 'settings-error': '/account/settings/',
                    'settings-saved': '/account/settings/',
                }
                if name in expected_paths:
                    self.assertEqual(urlparse(page.url).path, expected_paths[name], name)
                expect(page.locator('main#main-content')).to_be_visible()
                if name == 'manage':
                    self.assertEqual(page.locator('input[type=password]').evaluate_all('els => els.filter(e => !e.labels?.length).length'), 0, 'Reauthentication needs visible labels, not only aria-label')
                expect(page.locator('main h1')).to_have_count(1)
                self.assertTrue(page.title().endswith('Synology-Admin'))
                self.assertEqual(page.locator('html').get_attribute('lang'), 'ko')
                for width in (1440, 390):
                    page.set_viewport_size({'width': width, 'height': 1000})
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width, name)
                    unlabeled = page.locator('input:not([type=hidden]),select,textarea').evaluate_all('els => els.filter(e => !e.labels?.length && !e.getAttribute("aria-label") && !e.getAttribute("aria-labelledby")).map(e => e.name)')
                    self.assertEqual(unlabeled, [], name)
                    path = artifacts / f'{name}-{width}.png'
                    page.screenshot(path=str(path), full_page=True, mask_color='#dce2e9', mask=[page.locator('#otp-seed'), page.locator('input[type=password]'), page.locator('[name=token]')])
                    records.append({'page': name, 'width': width, 'screenshot': str(path)})
                page.set_viewport_size({'width': 1440, 'height': 1000})

            page.goto(self.live_server_url + '/')
            capture('landing')
            page.goto(self.live_server_url + '/signup/')
            self.assertRegex(page.locator('.helptext').first.inner_text(), '[가-힣]')
            capture('signup')
            page.locator('[name=username]').fill('ui-member-test')
            page.locator('[name=password1]').fill(password)
            page.locator('[name=password2]').fill(password)
            page.locator('[name=tenant]').select_option(str(tenant.pk))
            page.locator('main button[type=submit]').click()
            page.wait_for_url('**/login/')
            capture('login')
            page.locator('[name=username]').fill('ui-member-test')
            page.locator('[name=password]').fill('incorrect-fixture-password')
            page.locator('main button[type=submit]').click()
            expect(page.locator('.errorlist')).to_be_visible()
            self.assertRegex(page.locator('.errorlist').inner_text(), '[가-힣]')
            capture('login-error')
            page.locator('[name=password]').fill(password)
            page.locator('main button[type=submit]').click()
            page.wait_for_url('**/account/')
            capture('account-pending')
            # Switch to a pre-approved disposable fixture, not a production authorization bypass.
            page.get_by_role('button', name='로그아웃').click()
            page.wait_for_url('**/login/')
            page.locator('[name=username]').fill(approved.username)
            page.locator('[name=password]').fill(password)
            page.locator('main button[type=submit]').click()
            page.wait_for_url('**/account/')
            capture('account-approved')
            settings_link = page.get_by_role('link', name='아이디·비밀번호 변경', exact=True)
            expect(settings_link).to_be_visible()
            settings_link.click()
            capture('settings')
            page.locator('[name=username]').fill('ui-renamed-test')
            page.locator('[name=new_password1]').fill('UI-replacement-test-only-839!')
            page.locator('[name=new_password2]').fill('UI-mismatch-test-only-839!')
            page.get_by_label('현재 비밀번호').fill(password)
            page.get_by_role('button', name='변경 저장').click()
            expect(page.locator('.errorlist')).to_contain_text('일치하지 않습니다')
            capture('settings-error')
            page.locator('[name=new_password1]').fill('UI-replacement-test-only-839!')
            page.locator('[name=new_password2]').fill('UI-replacement-test-only-839!')
            page.get_by_label('현재 비밀번호').fill(password)
            with page.expect_navigation():
                page.get_by_role('button', name='변경 저장').click()
            expect(page.locator('[name=username]')).to_have_value('ui-renamed-test')
            self.assertTrue(db_call(lambda: User.objects.get(pk=approved.pk).check_password('UI-replacement-test-only-839!')))
            self.assertEqual(db_call(lambda: User.objects.get(pk=approved.pk).username), 'ui-renamed-test')
            capture('settings-saved')
            page.goto(self.live_server_url + '/service/')
            capture('service')
            expect(page.locator('[data-usage=account] dd')).to_have_text(['알 수 없음', '알 수 없음', '알 수 없음', '설정 안 됨', '관측 없음', '출처 없음'])
            page.goto(self.live_server_url + '/support/')
            capture('support-empty')
            page.goto(self.live_server_url + '/support/new/')
            capture('support-form')
            page.locator('[name=title]').fill('브라우저 검증용 지원 요청')
            page.locator('[name=body]').fill('테스트 데이터입니다. 실제 고객 정보가 아닙니다.')
            page.get_by_role('button', name='등록', exact=True).click()
            ticket_id = db_call(lambda: Ticket.objects.get(author=approved).pk)
            page.wait_for_url(f'**/support/{ticket_id}/')
            page.locator('[name=body]').fill('검증용 답변 — ' + '긴문자열' * 40)
            page.get_by_role('button', name='답변 등록').click()
            capture('support-detail')
            page.goto(self.live_server_url + '/support/')
            capture('support-list')
            page.goto(self.live_server_url + '/chat/')
            capture('chat-empty')
            page.get_by_role('button', name='내 대화 시작').click()
            conversation_id = db_call(lambda: Conversation.objects.get(owner=approved).pk)
            page.wait_for_url(f'**/chat/{conversation_id}/')
            page.locator('[name=body]').fill('검증용 메시지 <script>텍스트로 표시</script>')
            page.get_by_role('button', name='보내기').click()
            expect(page.locator('#send-status')).to_have_text('전송됨')
            expect(page.locator('#messages')).to_contain_text('<script>텍스트로 표시</script>', timeout=10000)
            capture('chat-detail')
            page.goto(self.live_server_url + '/chat/')
            capture('chat-list')
            page.goto(self.live_server_url + '/account/')
            page.get_by_role('button', name='로그아웃').click()
            page.wait_for_url('**/login/')
            page.locator('[name=username]').fill(admin.username)
            page.locator('[name=password]').fill(password)
            page.locator('main button[type=submit]').click()
            page.wait_for_url('**/mfa/enroll/')
            capture('mfa-enroll')
            page.locator('[name=password]').fill(password)
            page.get_by_role('button', name='등록 시작').click()
            seed = base64.b32decode(page.locator('#otp-seed').inner_text())
            capture('mfa-verify')
            page.locator('[name=token]').fill(f'{TOTP(seed).token():06d}')
            page.get_by_role('button', name='OTP 확인').click()
            page.wait_for_url('**/manage/')
            capture('manage')
            page.goto(self.live_server_url + '/service/')
            expect(page.locator('[data-usage=group]')).to_be_visible()
            capture('service-admin')
            page.goto(self.live_server_url + '/mfa/verify/')
            expect(page.locator('#otp-seed')).to_have_count(0)
            capture('mfa-challenge')
            browser.close()
        self.assertEqual(errors, [])
        self.assertEqual(external, [])
        (artifacts / 'manifest.json').write_text(json.dumps({'pages': len({r['page'] for r in records}), 'captures': len(records), 'console_errors': errors, 'external_requests': external, 'records': records}, ensure_ascii=False, indent=2))
        print(f'PORTAL UI: {len({r["page"] for r in records})} page states, {len(records)} desktop/mobile captures; real signup/login/OTP/ticket/reply/chat/logout; no external requests or JS errors')
