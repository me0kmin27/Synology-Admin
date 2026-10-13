"""Rendered navigation is an affordance, never an authorization boundary."""
from html.parser import HTMLParser
from urllib.parse import urljoin
from django.contrib.auth.models import User
from tests.mfa_helpers import TestCase, override_settings
from membership.models import Membership, Tenant


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.primary = []
        self.in_nav = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'nav' and attrs.get('aria-label') == '주 메뉴':
            self.in_nav = True
        if tag == 'a' and 'href' in attrs:
            self.links.append(attrs['href'])
            if self.in_nav:
                self.primary.append(attrs['href'])

    def handle_endtag(self, tag):
        if tag == 'nav':
            self.in_nav = False


@override_settings(SECURE_SSL_REDIRECT=False, MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True)
class CompactUITests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Group A', max_accounts=20)
        self.other = Tenant.objects.create(name='Group B', max_accounts=20)
        self.member = User.objects.create_user('member')
        self.membership = Membership.objects.create(user=self.member, tenant=self.tenant, status='approved')
        self.manager = User.objects.create_user('manager')
        Membership.objects.create(user=self.manager, tenant=self.tenant, status='approved', role='admin')
        self.root = User.objects.create_superuser('root')

    def links(self, response):
        parser = Links()
        parser.feed(response.content.decode())
        return parser

    def test_navigation_only_offers_accessible_workspaces(self):
        cases = [(None, ['/', '/login/', '/signup/']),
                 (self.member, ['/account/', '/support/', '/chat/']),
                 (self.manager, ['/account/', '/support/', '/chat/', '/manage/']),
                 (self.root, ['/account/', '/support/', '/chat/', '/manage/'])]
        for user, expected in cases:
            self.client.logout()
            if user:
                self.client.force_login(user)
            response = self.client.get('/')
            self.assertEqual(self.links(response).primary, expected)
            for href in self.links(response).links:
                if href.startswith('/'):
                    self.assertLess(self.client.get(href, follow=True).status_code, 400, (user, href))
        self.membership.status = 'pending'
        self.membership.save()
        self.client.force_login(self.member)
        self.assertEqual(self.links(self.client.get('/account/')).primary, ['/account/'])
        self.assertNotIn('/service/', self.links(self.client.get('/account/')).links)

    def test_membership_list_is_compact_with_scoped_detail_fallback(self):
        self.client.force_login(self.manager)
        response = self.client.get('/manage/')
        self.assertNotContains(response, 'type="password"')
        target = f'/manage/?member={self.membership.pk}'
        self.assertIn(target, self.links(response).links)
        detail = self.client.get(target)
        self.assertContains(detail, 'type="password"')
        self.assertContains(detail, f'action="/manage/{self.membership.pk}/quota/"')
        outsider = Membership.objects.create(user=User.objects.create_user('outsider'), tenant=self.other, status='approved')
        self.assertEqual(self.client.get(f'/manage/?member={outsider.pk}').status_code, 404)
        self.assertEqual(self.client.get(f'/manage/?group={self.other.pk}').status_code, 404)
        self.assertEqual(self.client.get('/manage/?member=invalid').status_code, 404)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(target).status_code, 403)

    def test_every_registered_route_and_rendered_link_for_each_role(self):
        import json
        import os
        from pathlib import Path
        from config.urls import urlpatterns
        from support.models import Ticket
        from chat.models import Conversation
        ticket = Ticket.objects.create(tenant=self.tenant, author=self.member, title='own ticket', body='private')
        conversation = Conversation.objects.create(tenant=self.tenant, owner=self.member)
        records = []
        for role, user in [('anonymous', None), ('user', self.member), ('group-admin', self.manager), ('global-admin', self.root)]:
            self.client.logout()
            if user:
                self.client.force_login(user)
            for route in urlpatterns:
                pattern = str(route.pattern)
                pk = (ticket.pk if pattern.startswith('support/') else conversation.pk if pattern.startswith('chat/') else self.tenant.pk if pattern.startswith('manage/groups/') else self.membership.pk)
                path = '/' + pattern.replace('<int:pk>', str(pk))
                response = self.client.get(path)
                self.assertIn(response.status_code, (200, 302, 403, 405), (role, path))
                records.append({'role': role, 'route': pattern, 'path': path, 'status': response.status_code})
                if response.status_code == 200 and 'text/html' in response.get('Content-Type', ''):
                    for href in set(self.links(response).links):
                        if href.startswith('#'):
                            continue
                        target = urljoin(path, href)
                        self.assertTrue(target.startswith('/'), (role, path, target))
                        linked = self.client.get(target, follow=True)
                        self.assertLess(linked.status_code, 400, (role, path, target, linked.status_code))
        self.assertEqual(len(records), len(urlpatterns) * 4)
        if os.environ.get('ROUTE_AUDIT_PATH'):
            Path(os.environ['ROUTE_AUDIT_PATH']).write_text(json.dumps({'registered_routes': len(urlpatterns), 'role_route_checks': len(records), 'checks': records}, indent=2))

    def test_personalized_home_is_not_cacheable_and_root_is_identified(self):
        self.client.force_login(self.root)
        self.assertIn('no-store', self.client.get('/').get('Cache-Control', ''))
        response = self.client.get('/account/')
        self.assertContains(response, '<dd>root</dd>', html=True)
        self.assertContains(response, '전역 관리자')

    def test_unassigned_global_admin_not_offered_member_only_actions(self):
        self.client.force_login(self.root)
        self.assertNotIn('/service/', self.links(self.client.get('/account/')).links)
        self.assertNotIn('/support/new/', self.links(self.client.get('/support/')).links)
