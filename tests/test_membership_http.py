"""Real loopback WSGI + cookie jars + HTML forms; no mocked NAS responses."""
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPCookieProcessor
from django.contrib.auth.models import User
from tests.mfa_helpers import LiveServerTestCase, override_settings
from membership.models import Membership, Tenant, AuditEvent, NasBinding


class Tokens(HTMLParser):
    token = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name") == "csrfmiddlewaretoken":
            self.token = attrs["value"]


@override_settings(SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, STATIC_URL="/static/", MEDIA_URL="/media/")
class MembershipHTTPTests(LiveServerTestCase):
    def request(self, browser, path, data=None):
        try:
            with browser.open(self.live_server_url + path, data=None if data is None else urlencode(data).encode(), timeout=10) as response:
                return response.status, response.read().decode(), response.url
        except HTTPError as error:
            return error.code, error.read().decode(), error.url

    def form(self, browser, get_path, post_path, data):
        status, html, _ = self.request(browser, get_path)
        self.assertEqual(status, 200)
        parser = Tokens()
        parser.feed(html)
        self.assertIsNotNone(parser.token)
        return self.request(browser, post_path, {**data, "csrfmiddlewaretoken": parser.token})

    def test_browser_forms_signup_assign_approve_link_revoke_logout(self):
        password = "Integration-passphrase-729!"
        root = User.objects.create_superuser("root", password=password)
        tenant = Tenant.objects.create(max_accounts=100, name="HTTP tenant")
        member_browser = build_opener(HTTPCookieProcessor(CookieJar()))
        admin_browser = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, url = self.form(member_browser, "/signup/", "/signup/", {"username": "http-member", "password1": password, "password2": password, "role": "admin", "tenant": tenant.pk})
        self.assertEqual(status, 200)
        self.assertTrue(url.endswith("/login/"))
        subject = Membership.objects.get(user__username="http-member")
        self.assertEqual(subject.status, "pending")
        self.form(member_browser, "/login/", "/login/", {"username": "http-member", "password": password})
        self.assertEqual(self.request(member_browser, "/service/")[0], 403)
        self.assertEqual(self.request(member_browser, "/manage/")[0], 403)
        self.form(admin_browser, "/login/", "/login/", {"username": "root", "password": password})
        self.assertEqual(self.request(admin_browser, f"/manage/{subject.pk}/approve/", {"password": password})[0], 403)
        self.assertEqual(self.form(admin_browser, '/mfa/enroll/', '/mfa/enroll/', {'password': password})[0], 200)
        from membership.models import AdminOTPDevice
        from django_otp.oath import TOTP
        device = AdminOTPDevice.objects.get(user=root)
        otp = f'{TOTP(device.bin_key).token():06d}'
        self.assertEqual(self.form(admin_browser, '/mfa/verify/', '/mfa/verify/', {'token': otp})[0], 200)
        self.assertEqual(self.form(admin_browser, "/manage/", f"/manage/{subject.pk}/assign/", {"password": password, "tenant": tenant.pk})[0], 409)
        self.assertEqual(self.form(admin_browser, "/manage/", f"/manage/{subject.pk}/approve/", {"password": password})[0], 200)
        self.form(member_browser, "/login/", "/login/", {"username": "http-member", "password": password})
        status, html, _ = self.request(member_browser, "/service/")
        self.assertEqual(status, 200)
        self.assertIn("용량 미수집", html)
        self.assertEqual(self.form(admin_browser, "/manage/", f"/manage/{subject.pk}/link/", {"password": password, "external_id": "http-nas-id", "ownership_confirmed": "on"})[0], 200)
        self.assertEqual(NasBinding.objects.get(membership=subject).external_id, "http-nas-id")
        self.assertEqual(self.form(admin_browser, "/manage/", f"/manage/{subject.pk}/revoke/", {"password": password})[0], 200)
        _, _, url = self.request(member_browser, "/service/")
        self.assertIn("/login/", url)
        self.assertEqual(list(AuditEvent.objects.filter(subject=subject).order_by("pk").values_list("action", flat=True)), ["approve", "link", "revoke"])
        self.form(admin_browser, "/account/", "/logout/", {})
        _, _, url = self.request(admin_browser, "/manage/")
        self.assertIn("/login/", url)
