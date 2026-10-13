from unittest.mock import patch
from django.contrib.auth.models import User
from tests.mfa_helpers import TestCase, Client, override_settings
from membership.models import Tenant, Membership, GroupAudit

PASSWORD = 'Menu-test-passphrase-829!'

@override_settings(SECURE_SSL_REDIRECT=False, AUTH_ATTEMPT_LIMIT=1000)
class MenuFixTests(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser('menu-root', password=PASSWORD)
        self.client.force_login(self.root)

    def test_account_identity_and_global_role_without_membership(self):
        response = self.client.get('/account/')
        self.assertContains(response, 'menu-root')
        self.assertContains(response, '전역 관리자')
        self.assertNotContains(response, '회원 정보 없음')

    def test_global_service_honest_empty_and_tenant_policy_overview(self):
        self.assertContains(self.client.get('/service/'), '등록된 그룹 없음')
        Tenant.objects.create(name='Visible policy', max_accounts=7, storage_limit_bytes=123)
        response = self.client.get('/service/')
        self.assertContains(response, 'Visible policy')
        self.assertContains(response, 'NAS 연결 안 됨')
        self.assertContains(response, '포털 정책')
        self.assertNotContains(response, 'data-usage="account"')

    def test_home_authentication_and_optional_otp_copy(self):
        response = self.client.get('/')
        self.assertNotContains(response, 'href="/login/"')
        self.assertNotContains(response, 'href="/signup/"')
        self.assertContains(response, 'OTP 정책')
        self.assertNotContains(response, '추가 OTP 인증 필요')
        self.client.logout()
        self.assertContains(self.client.get('/'), 'href="/signup/"')

    def test_global_support_and_chat_explain_review_without_creation(self):
        response = self.client.get('/support/')
        self.assertNotContains(response, 'href="/support/new/"')
        self.assertContains(response, '전역 검토')
        self.assertContains(self.client.get('/support/new/'), '접근 권한', status_code=403)
        response = self.client.get('/chat/')
        self.assertContains(response, '회원이 시작한 대화')
        self.assertNotContains(response, '내 대화 시작')
        self.assertEqual(self.client.post('/chat/').status_code, 403)

    def payload(self, **overrides):
        return dict(password=PASSWORD, name='New group', slug='new-group', max_accounts='3', storage_limit_bytes='4096', **overrides)

    def test_group_creation_ui_endpoint_and_audit(self):
        self.assertContains(self.client.get('/manage/'), '/manage/groups/new/')
        self.assertEqual(self.client.get('/manage/groups/new/').status_code, 405)
        self.assertEqual(self.client.post('/manage/groups/new/', self.payload()).status_code, 302)
        tenant = Tenant.objects.get(name='New group')
        self.assertEqual((tenant.slug, tenant.max_accounts, tenant.storage_limit_bytes), ('new-group', 3, 4096))
        audit = GroupAudit.objects.get(tenant=tenant)
        self.assertEqual((audit.actor_id, audit.action), (self.root.pk, 'create'))
        self.assertEqual(audit.details, {'name': 'New group', 'slug': 'new-group', 'max_accounts': 3, 'storage_limit_bytes': 4096})
        self.assertFalse(Membership.objects.exists())

    def test_creation_validation_duplicates_and_reauthentication(self):
        for field, values in {'name': ['', ' '*5, 'x'*101], 'slug': ['', 'bad slug', 'UPPER', 'x'*101], 'max_accounts': ['-1', '1.5', str(2**63)], 'storage_limit_bytes': ['-1', '', str(2**63)]}.items():
            for value in values:
                data = self.payload(); data[field] = value
                self.assertEqual(self.client.post('/manage/groups/new/', data).status_code, 400, (field, value))
        data = self.payload(); data['password'] = 'wrong'
        self.assertContains(self.client.post('/manage/groups/new/', data), '접근 권한', status_code=403)
        self.assertFalse(Tenant.objects.exists())
        self.client.post('/manage/groups/new/', self.payload())
        for changes in ({}, {'name': 'Other'}, {'slug': 'other'}):
            data = self.payload(); data.update(changes)
            self.assertContains(self.client.post('/manage/groups/new/', data), '충돌', status_code=409)
        self.assertEqual(Tenant.objects.count(), 1)
        self.assertEqual(GroupAudit.objects.count(), 1)

    def test_creation_authorization_csrf_and_audit_rollback(self):
        browser = Client(enforce_csrf_checks=True); browser.force_login(self.root)
        self.assertEqual(browser.post('/manage/groups/new/', self.payload()).status_code, 403)
        with patch('membership.groups.GroupAudit.objects.create', side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):
                self.client.post('/manage/groups/new/', self.payload())
        self.assertFalse(Tenant.objects.exists())
        tenant = Tenant.objects.create(name='Existing')
        user = User.objects.create_user('manager', password=PASSWORD)
        Membership.objects.create(user=user, tenant=tenant, status='approved', role='admin')
        self.client.force_login(user)
        self.assertNotContains(self.client.get('/manage/'), '/manage/groups/new/')
        self.assertEqual(self.client.post('/manage/groups/new/', self.payload()).status_code, 403)
        self.assertContains(self.client.get('/service/'), '용량 미수집')

    def test_member_navigation_denial_is_readable_and_api_is_unchanged(self):
        user = User.objects.create_user('pending', password=PASSWORD)
        Membership.objects.create(user=user)
        self.client.force_login(user)
        for path in ('/service/', '/manage/', '/support/', '/chat/'):
            self.assertContains(self.client.get(path), '접근 권한', status_code=403)
        response = self.client.get('/chat/999/events/')
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, '내 계정 확인', status_code=403)

    def test_json_conflict_response_passes_through_unchanged(self):
        from django.http import JsonResponse
        from django.test import RequestFactory
        from config.errors import NavigationErrorMiddleware
        response = JsonResponse({'error': 'Nonce already used for a different message.'}, status=409)
        request = RequestFactory().post('/chat/1/events/')
        self.assertIs(NavigationErrorMiddleware(lambda request: response)(request), response)
        self.assertEqual(response.json() if hasattr(response, 'json') else __import__('json').loads(response.content),
                         {'error': 'Nonce already used for a different message.'})

    def test_created_group_allows_signup_approval_and_manager_workflow(self):
        self.client.post('/manage/groups/new/', self.payload())
        tenant = Tenant.objects.get(slug='new-group')
        self.client.logout()
        self.assertEqual(self.client.post('/signup/', {'tenant': tenant.pk, 'username': 'applicant',
            'password1': PASSWORD, 'password2': PASSWORD}).status_code, 302)
        member = Membership.objects.get(user__username='applicant')
        self.client.force_login(self.root)
        self.assertEqual(self.client.post(f'/manage/{member.pk}/approve/', {'password': PASSWORD}).status_code, 302)
        self.assertEqual(self.client.post(f'/manage/{member.pk}/role/', {'password': PASSWORD, 'role': 'admin'}).status_code, 302)
        self.client.force_login(member.user)
        self.assertContains(self.client.get('/manage/'), 'New group')
        self.assertContains(self.client.get('/service/'), '용량 미수집')

    def test_manager_role_select_reflects_current_role(self):
        tenant = Tenant.objects.create(name='Role selection')
        user = User.objects.create_user('role-manager', password=PASSWORD)
        member = Membership.objects.create(user=user, tenant=tenant, status='approved', role='admin')
        response = self.client.get('/manage/')
        from html.parser import HTMLParser
        class Options(HTMLParser):
            def __init__(self):
                super().__init__(); self.target = False; self.selected = []
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'form':
                    self.target = attrs.get('action') == f'/manage/{member.pk}/role/'
                if self.target and tag == 'option' and 'selected' in attrs:
                    self.selected.append(attrs['value'])
        options = Options(); options.feed(response.content.decode())
        self.assertEqual(options.selected, ['admin'])

    def test_navigation_error_content_length_matches_rendered_body(self):
        user = User.objects.create_user('pending-length', password=PASSWORD)
        Membership.objects.create(user=user)
        self.client.force_login(user)
        response = self.client.get('/service/')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(int(response['Content-Length']), len(response.content))

    def test_global_support_review_role_is_visible_with_existing_tickets(self):
        from support.models import Ticket
        tenant = Tenant.objects.create(name='Support customer')
        author = User.objects.create_user('ticket-author', password=PASSWORD)
        Ticket.objects.create(tenant=tenant, author=author, title='Member request', body='Help')
        response = self.client.get('/support/')
        self.assertContains(response, '전역 검토')
        self.assertNotContains(response, 'href="/support/new/"')
