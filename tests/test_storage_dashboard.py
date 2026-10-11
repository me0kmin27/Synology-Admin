"""Portal HTTP tests; domain fixtures below are not live NAS observations."""
from django.contrib.auth.models import User
from tests.mfa_helpers import TestCase, override_settings
from membership.models import Membership, Tenant


@override_settings(SECURE_SSL_REDIRECT=False, MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True)
class StorageDashboardTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Own customer', storage_limit_bytes=987654)
        self.user = User.objects.create_user('own-account')
        self.member = Membership.objects.create(user=self.user, tenant=self.tenant, status='approved', quota_bytes=123456)
        self.client.force_login(self.user)

    def test_reader_subject_mismatch_fails_closed(self):
        from unittest.mock import patch
        from nas_usage import Subject, UsageObservation
        wrong = UsageObservation(Subject('other', 'account', 'other', 'portal-unmapped'))
        with patch('membership.storage.NotConfiguredReader.read_usage', return_value=wrong):
            response = self.client.get('/service/')
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, 'data-usage', status_code=503)
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_domain_fixtures_render_unknown_unlimited_stale_and_escaped_source(self):
        # Synthetic domain values injected ONLY in this test, never live adapter data.
        from datetime import datetime, timezone, timedelta
        from unittest.mock import patch
        from nas_usage import UsageObservation
        at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        cases = [
            ({'state': 'unknown'}, ['미수집', '알 수 없음', '출처 없음']),
            ({'state': 'observed', 'source': 'fixture-only<script>', 'observed_at': at,
              'limit_kind': 'unlimited', 'used_bytes': 0}, ['무제한', '해당 없음 (무제한)', '0 B', 'fixture-only&lt;script&gt;']),
            ({'state': 'observed', 'source': 'fixture-only', 'observed_at': at - timedelta(days=1),
              'limit_kind': 'limited', 'assigned_bytes': 100, 'used_bytes': 30},
             ['오래된 관측', '100 B (오래된 값)', '30 B (오래된 값)', '알 수 없음']),
        ]
        for values, labels in cases:
            with self.subTest(values=values), patch('membership.storage.timezone.now', return_value=at), patch(
                'membership.storage.NotConfiguredReader.read_usage',
                side_effect=lambda subject: UsageObservation(subject, **values),
            ):
                response = self.client.get('/service/')
                for label in labels:
                    self.assertContains(response, label)
                self.assertNotContains(response, '<script>')

    def test_denied_states_and_anonymous_are_not_cached(self):
        for status in ['pending', 'suspended']:
            Membership.objects.filter(pk=self.member.pk).update(status=status)
            self.client.force_login(self.user)
            response = self.client.get('/service/')
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response['Cache-Control'], 'no-store')
            self.assertNotContains(response, 'data-usage', status_code=403)
        self.client.logout()
        response = self.client.get('/service/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_cached_actor_revocation_and_epoch_are_rechecked(self):
        from tests.mfa_helpers import RequestFactory
        from membership.views import service
        for update in ({'is_active': False}, {'epoch': 1}):
            request = RequestFactory().get('/service/')
            request.user = User.objects.get(pk=self.user.pk)
            request.session = {'membership_version': 0}
            if 'is_active' in update:
                User.objects.filter(pk=self.user.pk).update(**update)
            else:
                User.objects.filter(pk=self.user.pk).update(is_active=True)
                Membership.objects.filter(pk=self.member.pk).update(session_version=1)
            with self.subTest(update=update):
                self.assertEqual(service(request).status_code, 403)

    def test_post_is_not_a_dashboard_action(self):
        self.assertEqual(self.client.post('/service/').status_code, 405)

    def test_group_admin_and_global_admin_only_see_own_group(self):
        other = Tenant.objects.create(name='Other hidden customer')
        for role, global_admin in [('admin', False), ('member', True)]:
            with self.subTest(role=role, global_admin=global_admin):
                Membership.objects.filter(pk=self.member.pk).update(role=role)
                User.objects.filter(pk=self.user.pk).update(is_superuser=global_admin)
                self.user.refresh_from_db()
                self.client.force_login(self.user)
                response = self.client.get('/service/', {'tenant': other.pk, 'account': 'someone-else', 'scope': 'volume'})
                self.assertContains(response, '그룹 사용량 · Own customer')
                self.assertNotContains(response, other.name)
                self.assertEqual([c['kind'] for c in response.context['cards']], ['account', 'group'])

    def test_approved_account_has_truthful_unconnected_dashboard(self):
        response = self.client.get('/service/')
        self.assertContains(response, '스토리지 대시보드')
        self.assertContains(response, 'NAS 미연결')
        self.assertContains(response, '내 계정')
        self.assertContains(response, '알 수 없음', count=3)
        self.assertContains(response, '최종 관측 시각')
        self.assertContains(response, '관측 없음')
        self.assertContains(response, '출처 없음')
        self.assertNotContains(response, '123456')
        self.assertNotContains(response, '987654')
        self.assertNotContains(response, '그룹 사용량')
        self.assertEqual(response['Cache-Control'], 'no-store')
