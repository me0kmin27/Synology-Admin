"""Progressive dialogs over real authorized HTTP, not mocked responses."""
import secrets
from django.contrib.auth.models import User
from membership.models import Membership, Tenant, AdminMFAPolicy
from playwright.sync_api import sync_playwright, expect
from tests.mfa_helpers import LiveServerTestCase, override_settings


@override_settings(SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False,
                   CSRF_COOKIE_SECURE=False, MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True,
                   STATIC_URL='/static/', MEDIA_URL='/media/')
class CompactBrowserTests(LiveServerTestCase):
    def setUp(self):
        AdminMFAPolicy.objects.filter(pk=1).update(required=False)
        self.password = secrets.token_urlsafe(24)
        self.admin = User.objects.create_superuser('compact-admin', password=self.password)
        self.tenant = Tenant.objects.create(name='Compact group', max_accounts=20)
        self.subject = Membership.objects.create(user=User.objects.create_user('compact-member'), tenant=self.tenant, status='approved')

    def login(self, page):
        page.goto(self.live_server_url + '/login/')
        page.locator('[name=username]').fill(self.admin.username)
        page.locator('[name=password]').fill(self.password)
        page.get_by_role('button', name='제출').click()
        page.wait_for_url('**/account/')

    def test_inflight_mutation_cannot_be_closed_or_submitted_twice(self):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            self.login(page)
            page.goto(self.live_server_url + '/manage/')
            page.locator(f'a[href="/manage/?member={self.subject.pk}"]').click()
            dialog = page.get_by_role('dialog')
            form = dialog.locator(f'form[action$="/manage/{self.subject.pk}/quota/"]')
            form.locator('[name=password]').fill(self.password)
            held = []
            page.route('**/quota/', lambda route: held.append(route))
            with page.expect_request('**/quota/'):
                form.locator('button').click()
            page.keyboard.press('Escape')
            expect(dialog).to_be_visible()
            self.assertTrue(page.evaluate("""(() => {
                const event = new Event('beforeunload', {cancelable: true});
                window.dispatchEvent(event); return event.defaultPrevented;
            })()"""))
            dialog.get_by_role('button', name='닫기', exact=True).click()
            expect(dialog).to_be_visible()
            form.locator('button').click()
            self.assertEqual(len(held), 1)
            navigation = []
            def delay_document(route):
                if route.request.is_navigation_request():
                    navigation.append(route)
                else:
                    route.continue_()
            page.route('**/manage/', delay_document)
            page.evaluate('''() => { setInterval(() => document.querySelector('dialog form[action$="/quota/"]')?.requestSubmit(), 20); }''')
            with page.expect_request(lambda request: request.is_navigation_request() and request.url.endswith('/manage/')):
                held[0].continue_()
            # While the destination document is stalled, the old form cannot repeat.
            page.wait_for_timeout(100)
            self.assertEqual(len(held), 1)
            navigation[0].continue_()
            expect(dialog).not_to_be_visible()
            browser.close()
        from membership.models import GroupAudit
        self.assertEqual(GroupAudit.objects.filter(action='quota').count(), 1)

    def test_modal_focus_validation_escape_and_fallback(self):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            self.login(page)
            page.goto(self.live_server_url + '/manage/')
            trigger = page.locator(f'a[href="/manage/?member={self.subject.pk}"]')
            trigger.click()
            dialog = page.get_by_role('dialog')
            expect(dialog).to_be_visible()
            expect(dialog.get_by_role('button', name='닫기', exact=True)).to_be_focused()
            page.keyboard.press('Shift+Tab')
            self.assertTrue(page.evaluate('document.activeElement.closest("dialog") !== null'))
            from pathlib import Path
            artifacts = Path('.runtime/compact-ui')
            artifacts.mkdir(parents=True, exist_ok=True)
            expect(dialog.locator('form').first).to_be_visible()
            for width in (390, 1440):
                page.set_viewport_size({'width': width, 'height': 900})
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                page.screenshot(path=str(artifacts / f'member-dialog-{width}.png'), mask=[page.locator('input[type=password]')])
            page.set_viewport_size({'width': 390, 'height': 844})
            form = dialog.locator(f'form[action$="/manage/{self.subject.pk}/quota/"]')
            form.locator('button').click()
            expect(form.locator('[name=password]')).to_be_focused()
            page.keyboard.press('Escape')
            expect(dialog).not_to_be_visible()
            expect(trigger).to_be_focused()
            trigger.click()
            expect(dialog).to_be_visible()
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
            form.locator('[name=password]').fill('deliberately-wrong')
            form.locator('button').click()
            expect(dialog.get_by_role('alert')).to_contain_text('403')
            page.keyboard.press('Escape')
            page.goto(self.live_server_url + '/account/')
            page.get_by_role('link', name='아이디·비밀번호 변경', exact=True).click()
            expect(dialog).to_be_visible()
            dialog.locator('[name=username]').fill(self.admin.username)
            dialog.locator('[name=password]').fill(self.password)
            dialog.locator('[name=new_password1]').fill('Mismatch-disposable-123!')
            dialog.locator('[name=new_password2]').fill('Other-disposable-456!')
            dialog.get_by_role('button', name='변경 저장').click()
            expect(dialog.locator('.errorlist')).to_contain_text('일치하지 않습니다')
            self.assertEqual(errors, [])
            nojs = browser.new_context(java_script_enabled=False, storage_state=page.context.storage_state())
            fallback = nojs.new_page()
            fallback.goto(self.live_server_url + '/manage/')
            fallback.locator(f'a[href="/manage/?member={self.subject.pk}"]').click()
            expect(fallback.locator('main input[type=password]').first).to_be_visible()
            self.assertIn('?member=', fallback.url)
            browser.close()
