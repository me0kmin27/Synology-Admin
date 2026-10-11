"""Actual loopback HTTP + cookie/CSRF cursor navigation (no response mocks)."""
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, build_opener

from django.contrib.auth.models import User
from django.test import LiveServerTestCase, override_settings

from membership.models import Membership, Tenant
from support.models import Ticket, TicketReply
from tests.test_membership_http import Tokens


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.next = None
        self.articles = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('rel') == 'next':
            self.next = attrs['href']
        if tag == 'article':
            self.articles += 1


@override_settings(SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
                   MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True, STATIC_URL='/static/', MEDIA_URL='/media/')
class PaginationHTTPTests(LiveServerTestCase):
    def test_invalid_post_navigation_and_revoked_cursor_over_real_http(self):
        password = 'Pagination-http-only-728!'
        user = User.objects.create_user('http-pagination', password=password)
        tenant = Tenant.objects.create(name='HTTP pagination')
        member = Membership.objects.create(user=user, tenant=tenant, status='approved')
        ticket = Ticket.objects.create(tenant=tenant, author=user, title='HTTP pages', body='private')
        replies = TicketReply.objects.bulk_create([
            TicketReply(ticket=ticket, author=user, body=f'<script>answer-{i}</script>') for i in range(27)
        ])
        browser = build_opener(HTTPCookieProcessor(CookieJar()))
        base = self.live_server_url

        def fetch(path, data=None):
            payload = urlencode(data).encode() if data is not None else None
            with browser.open(urljoin(base, path), payload, timeout=10) as response:
                text = response.read().decode()
                self.assertIn('no-store', response.headers['Cache-Control'])
                return response.url, text

        _, login = fetch('/login/')
        tokens = Tokens()
        tokens.feed(login)
        fetch('/login/', {'username': user.username, 'password': password, 'csrfmiddlewaretoken': tokens.token})
        path = f'/support/{ticket.pk}/'
        _, first = fetch(path)
        links = PageLinks()
        links.feed(first)
        self.assertEqual(links.articles, 25)
        tokens = Tokens()
        tokens.feed(first)
        post_url, invalid = fetch(path + 'replies/', {'body': '', 'csrfmiddlewaretoken': tokens.token})
        invalid_links = PageLinks()
        invalid_links.feed(invalid)
        self.assertEqual(invalid_links.articles, 25)
        self.assertIn('errorlist', invalid)
        self.assertEqual(urljoin(post_url, invalid_links.next), base + path + f'?after={replies[24].pk}')
        newer = TicketReply.objects.create(ticket=ticket, author=user, body='new arrival')
        _, second = fetch(urljoin(post_url, invalid_links.next))
        second_links = PageLinks()
        second_links.feed(second)
        self.assertEqual(second_links.articles, 3)
        self.assertIsNone(second_links.next)
        self.assertIn('&lt;script&gt;answer-25&lt;/script&gt;', second)
        self.assertNotIn('<script>', second)
        self.assertIn(newer.body, second)
        self.assertNotIn('answer-24', second)
        self.assertEqual(TicketReply.objects.filter(ticket=ticket).count(), 28)
        member.status = 'suspended'
        member.session_version += 1
        member.save()
        denied_url, denied_body = fetch(urljoin(post_url, invalid_links.next))
        self.assertIn('/login/?next=', denied_url)
        self.assertNotIn('answer-', denied_body)
