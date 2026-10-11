"""Explicit real Chromium + HTTP acceptance. Never skipped when invoked."""
from django.contrib.auth.models import User
from tests.mfa_helpers import LiveServerTestCase, override_settings
from membership.models import Membership, Tenant
from playwright.sync_api import sync_playwright, expect


@override_settings(SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
                   MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True, STATIC_URL='/static/', MEDIA_URL='/media/')
class ChatBrowserTests(LiveServerTestCase):
    def test_two_clients_automatic_updates_disconnect_resume_and_plain_text(self):
        password = 'Chat-browser-only-passphrase-728!'
        tenant = Tenant.objects.create(name='Browser test customer')
        owner = User.objects.create_user('browser-owner', password=password)
        manager = User.objects.create_user('browser-manager', password=password)
        Membership.objects.create(user=owner, tenant=tenant, status='approved')
        Membership.objects.create(user=manager, tenant=tenant, status='approved', role='admin')
        with sync_playwright() as p:
            browser = p.chromium.launch()
            a, b = browser.new_context(), browser.new_context()
            first, second = a.new_page(), b.new_page()
            for page, user in ((first, owner), (second, manager)):
                page.goto(self.live_server_url + '/login/')
                page.locator('[name=username]').fill(user.username)
                page.locator('[name=password]').fill(password)
                page.locator('button').click()
                if user == manager:
                    from tests.mfa_helpers import browser_enroll
                    browser_enroll(page, password)
                    page.goto(self.live_server_url + '/account/')
                else:
                    page.wait_for_url('**/account/')
            first.goto(self.live_server_url + '/chat/')
            expect(first.get_by_role('button', name='내 대화 시작')).to_be_visible()
            first.get_by_role('button', name='내 대화 시작').click()
            first.wait_for_url('**/chat/*/')
            conversation_url = first.url
            second.goto(conversation_url)
            first.locator('[name=body]').fill('<img src=x onerror=alert(1)> hello')
            first.get_by_role('button', name='보내기').click()
            expect(second.locator('#messages')).to_contain_text('<img src=x onerror=alert(1)> hello', timeout=12000)
            expect(second.locator('#messages img')).to_have_count(0)
            a.set_offline(True)
            second.locator('[name=body]').fill('sent while owner disconnected')
            second.get_by_role('button', name='보내기').click()
            expect(second.locator('#messages')).to_contain_text('sent while owner disconnected', timeout=12000)
            expect(first.locator('#transport')).to_contain_text('재연결', timeout=15000)
            a.set_offline(False)
            expect(first.locator('#messages')).to_contain_text('sent while owner disconnected', timeout=40000)
            expect(first.locator('#messages li')).to_have_count(2)
            # Another automatic poll after reconnection cannot duplicate either event.
            with first.expect_response(lambda r: '/events/?after=' in r.url and r.status == 200, timeout=10000):
                pass
            expect(first.locator('#messages li')).to_have_count(2)
            second.reload()
            expect(second.locator('#messages li')).to_have_count(2, timeout=12000)
            self.assertEqual(first.url, conversation_url)  # No manual refresh/navigation on receiver.
            # Server commits, but its HTTP acknowledgement is lost; manual retry
            # must reuse the nonce, not create a second message.
            def lose_ack(route):
                response = route.fetch()
                self.assertEqual(response.status, 201)
                route.abort('failed')
            second.route('**/events/', lose_ack, times=1)
            second.locator('[name=body]').fill('lost acknowledgement')
            second.get_by_role('button', name='보내기').click()
            expect(second.locator('#send-status')).to_contain_text('확인되지 않았습니다')
            self.assertTrue(second.locator('[name=body]').evaluate('(e) => e.readOnly'))
            second.get_by_role('button', name='보내기').click()
            expect(second.locator('#send-status')).to_have_text('전송됨')
            expect(first.locator('#messages li')).to_have_count(3, timeout=12000)
            from chat.models import Message
            # Playwright's sync context runs an event loop on this thread.
            # Keep Django's synchronous ORM on a worker, not ASYNC_UNSAFE.
            from concurrent.futures import ThreadPoolExecutor
            from django.db import connections
            def verify_and_deactivate():
                try:
                    self.assertEqual(Message.objects.count(), 3)
                    User.objects.filter(pk=owner.pk).update(is_active=False)
                finally:
                    connections.close_all()
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(verify_and_deactivate).result(timeout=10)
            expect(first.locator('#transport')).to_contain_text('세션이 종료', timeout=12000)
            expect(first.locator('#messages li')).to_have_count(0)
            expect(first.get_by_role('button', name='보내기')).to_be_disabled()
            print('BROWSER ACCEPTANCE: two independent HTTP cookie sessions; automatic delivery; offline reconnect; reload replay; plain-text XSS; lost-ack idempotent retry; retirement clears UI; no duplicates PASS')
            browser.close()
