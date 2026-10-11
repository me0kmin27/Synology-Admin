"""Real HTTP cookies/CSRF create -> detail -> list, without external services."""
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPCookieProcessor
from django.contrib.auth.models import User
from django.test import LiveServerTestCase, override_settings
from membership.models import Membership, Tenant
from tests.test_membership_http import Tokens
from support.models import Ticket, TicketAudit


@override_settings(SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
                   MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True, STATIC_URL='/static/', MEDIA_URL='/media/')
class SupportHTTPTests(LiveServerTestCase):
    def test_real_cookie_csrf_create_and_scoped_reads(self):
        password = 'Support-http-passphrase-728!'
        user = User.objects.create_user('http-support', password=password)
        tenant = Tenant.objects.create(name='HTTP support')
        Membership.objects.create(user=user, tenant=tenant, status='approved')
        browser = build_opener(HTTPCookieProcessor(CookieJar()))

        def get(path):
            return browser.open(self.live_server_url + path, timeout=10)

        def post(path, data):
            return browser.open(self.live_server_url + path, urlencode(data).encode(), timeout=10)

        def token(path):
            with get(path) as response:
                parser = Tokens()
                parser.feed(response.read().decode())
                self.assertIsNotNone(parser.token)
                return parser.token

        with post('/login/', {'username': user.username, 'password': password, 'csrfmiddlewaretoken': token('/login/')}) as response:
            self.assertTrue(response.url.endswith('/account/'))
        with self.assertRaises(HTTPError) as denied:
            post('/support/new/', {'title': 'Missing token', 'body': 'B'})
        self.assertEqual(denied.exception.code, 403)
        with post('/support/new/', {'title': 'HTTP ticket', 'body': '<script>unsafe</script>', 'csrfmiddlewaretoken': token('/support/new/')}) as response:
            self.assertEqual(response.status, 200)
            self.assertIn('no-store', response.headers['Cache-Control'])
            self.assertIn('&lt;script&gt;unsafe&lt;/script&gt;', response.read().decode())
        ticket = Ticket.objects.get()
        self.assertEqual(TicketAudit.objects.get().ticket_id, ticket.pk)
        with get('/support/') as response:
            self.assertIn(f'/support/{ticket.pk}/', response.read().decode())
