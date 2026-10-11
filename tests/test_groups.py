from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from membership.models import Membership, Tenant

PASSWORD = 'Group-test-passphrase-829!'


@override_settings(SECURE_SSL_REDIRECT=False, AUTH_ATTEMPT_LIMIT=1000)
class GroupTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(max_accounts=100, name='Customer A')
        self.root = User.objects.create_superuser('root', password=PASSWORD)

    def member(self, name, *, tenant=None, status='pending', role='member'):
        return Membership.objects.create(
            user=User.objects.create_user(name, password=PASSWORD),
            tenant=tenant or self.tenant, status=status, role=role,
        )

    def post(self, path, **data):
        return self.client.post(path, {'password': PASSWORD, **data})

    def test_pending_and_legacy_suspended_accounts_can_be_retired(self):
        from membership.models import AuditEvent
        self.client.force_login(self.root)
        for status in ('pending', 'suspended'):
            subject = self.member(status, status=status)
            self.assertEqual(self.post(f'/manage/{subject.pk}/revoke/').status_code, 302)
            subject.user.refresh_from_db()
            self.assertFalse(subject.user.is_active)
            self.assertEqual(AuditEvent.objects.get(subject=subject).previous, status)

    def test_group_manager_cannot_retire_global_admin_with_membership(self):
        manager = self.member('manager', status='approved', role='admin')
        root_member = Membership.objects.create(user=self.root, tenant=self.tenant, status='approved')
        self.client.force_login(manager.user)
        self.assertEqual(self.post(f'/manage/{root_member.pk}/revoke/').status_code, 403)
        self.root.refresh_from_db()
        self.assertTrue(self.root.is_active)

    def test_sqlite_mutations_fail_closed_without_explicit_development_opt_in(self):
        from django.db import connection
        if connection.vendor != 'sqlite':
            self.assertEqual(connection.vendor, 'postgresql')
            return
        self.client.force_login(self.root)
        subject = self.member('blocked')
        with override_settings(MEMBERSHIP_ALLOW_UNSAFE_SQLITE=False):
            self.assertEqual(self.post(f'/manage/{subject.pk}/approve/').status_code, 503)
        subject.refresh_from_db()
        self.assertEqual(subject.status, 'pending')

    def test_group_management_forms_are_scoped(self):
        manager = self.member('manager', status='approved', role='admin')
        self.client.force_login(self.root)
        response = self.client.get('/manage/')
        self.assertContains(response, f'/manage/groups/{self.tenant.pk}/limits/')
        self.assertContains(response, f'/manage/{manager.pk}/role/')
        self.assertContains(response, 'NAS 실제 quota 강제 집행 아님')
        self.client.force_login(manager.user)
        response = self.client.get('/manage/')
        self.assertNotContains(response, '/limits/')
        self.assertNotContains(response, '/role/')
        self.assertContains(response, f'/manage/{manager.pk}/quota/')
        self.assertContains(response, '포털 계정 폐기')

    def test_manager_allocates_portal_quota_within_cap_and_reduction_rejects(self):
        self.tenant.storage_limit_bytes = 100
        self.tenant.save()
        manager = self.member('manager', status='approved', role='admin')
        first = self.member('first', status='approved')
        second = self.member('second', status='approved')
        self.client.force_login(manager.user)
        url = f'/manage/{first.pk}/quota/'
        self.assertEqual(self.post(url, quota_bytes='60').status_code, 302)
        self.assertEqual(self.post(f'/manage/{second.pk}/quota/', quota_bytes='41').status_code, 409)
        self.assertEqual(self.post(f'/manage/{second.pk}/quota/', quota_bytes='40').status_code, 302)
        for bad in ('-1', '1.5', str(2**63)):
            self.assertEqual(self.post(url, quota_bytes=bad).status_code, 400)
        other = self.member('other', tenant=Tenant.objects.create(name='Other'), status='approved')
        self.assertEqual(self.post(f'/manage/{other.pk}/quota/', quota_bytes='1').status_code, 404)
        self.client.force_login(self.root)
        self.assertEqual(self.post(f'/manage/groups/{self.tenant.pk}/limits/', max_accounts='100', storage_limit_bytes='99').status_code, 409)
        self.assertEqual(self.post(f'/manage/{first.pk}/revoke/').status_code, 302)
        # Retirement retains reservations because NAS data is not deleted.
        self.assertEqual(self.post(f'/manage/groups/{self.tenant.pk}/limits/', max_accounts='100', storage_limit_bytes='99').status_code, 409)
        first.refresh_from_db()
        self.assertEqual(first.quota_bytes, 60)

    def test_global_admin_appoints_and_replaces_managers_without_scope_changes(self):
        from membership.models import AuditEvent
        subject = self.member('new-manager', status='approved')
        url = f'/manage/{subject.pk}/role/'
        self.client.force_login(self.root)
        self.assertEqual(self.post(url, role='admin', tenant='999').status_code, 302)
        subject.refresh_from_db()
        self.assertEqual((subject.role, subject.tenant_id), ('admin', self.tenant.pk))
        self.assertEqual(AuditEvent.objects.get(subject=subject).action, 'role')
        self.assertEqual(self.post(url, role='member').status_code, 409)
        replacement = self.member('replacement', status='approved')
        self.assertEqual(self.post(f'/manage/{replacement.pk}/role/', role='admin').status_code, 302)
        self.assertEqual(self.post(url, role='member').status_code, 302)
        self.client.force_login(replacement.user)
        self.assertEqual(self.post(url, role='admin').status_code, 403)
        self.assertEqual(self.post(f'/manage/{replacement.pk}/role/', role='member').status_code, 403)
        self.client.force_login(self.root)
        pending = self.member('pending')
        self.assertEqual(self.post(f'/manage/{pending.pk}/role/', role='admin').status_code, 409)
        self.assertEqual(self.post(url, role='owner').status_code, 400)

    def test_self_and_last_manager_retirement_are_rejected(self):
        manager = self.member('last', status='approved', role='admin')
        self.client.force_login(manager.user)
        url = f'/manage/{manager.pk}/revoke/'
        self.assertEqual(self.post(url).status_code, 403)
        self.client.force_login(self.root)
        self.assertEqual(self.post(url).status_code, 409)
        manager.refresh_from_db()
        self.assertEqual(manager.status, 'approved')
        self.member('replacement', status='approved', role='admin')
        self.assertEqual(self.post(url).status_code, 302)

    def test_retirement_disables_login_is_idempotent_and_preserves_binding(self):
        from django.test import Client
        from membership.models import AuditEvent, NasBinding
        subject = self.member('retire', status='approved')
        binding = NasBinding.objects.create(membership=subject, tenant=self.tenant, external_id='retain-id')
        browser = Client()
        self.assertTrue(browser.login(username='retire', password=PASSWORD))
        self.client.force_login(self.root)
        url = f'/manage/{subject.pk}/revoke/'
        self.assertEqual(self.post(url).status_code, 302)
        subject.user.refresh_from_db()
        self.assertFalse(subject.user.is_active)
        self.assertFalse(browser.login(username='retire', password=PASSWORD))
        self.assertEqual(browser.get('/account/').status_code, 302)
        self.assertEqual(self.post(url).status_code, 302)
        self.assertEqual(AuditEvent.objects.filter(subject=subject, action='revoke').count(), 1)
        self.assertTrue(NasBinding.objects.filter(pk=binding.pk).exists())

    def test_approval_counts_active_admin_and_members_not_pending_or_retired(self):
        self.tenant.max_accounts = 2
        self.tenant.save()
        manager = self.member('manager', status='approved', role='admin')
        first = self.member('first')
        second = self.member('second')
        retired = self.member('retired', status='suspended')
        retired.user.is_active = False
        retired.user.save()
        self.client.force_login(manager.user)
        self.assertEqual(self.post(f'/manage/{first.pk}/approve/').status_code, 302)
        self.assertEqual(self.post(f'/manage/{second.pk}/approve/').status_code, 409)
        second.refresh_from_db()
        self.assertEqual(second.status, 'pending')
        from membership.models import AuditEvent
        self.assertFalse(AuditEvent.objects.filter(subject=second).exists())
        self.client.force_login(self.root)
        self.assertEqual(self.post(f'/manage/groups/{self.tenant.pk}/limits/', max_accounts='1', storage_limit_bytes='0').status_code, 409)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.max_accounts, 2)

    def test_only_global_admin_sets_valid_group_limits_with_audit(self):
        self.client.force_login(self.root)
        url = f'/manage/groups/{self.tenant.pk}/limits/'
        self.assertEqual(self.post(url, max_accounts='3', storage_limit_bytes='4096').status_code, 302)
        self.tenant.refresh_from_db()
        self.assertEqual((self.tenant.max_accounts, self.tenant.storage_limit_bytes), (3, 4096))
        from membership.models import GroupAudit
        audit = GroupAudit.objects.get(tenant=self.tenant)
        self.assertEqual((audit.actor_id, audit.action, audit.details),
                         (self.root.pk, 'limits', {'max_accounts': 3, 'storage_limit_bytes': 4096}))
        for field in ('max_accounts', 'storage_limit_bytes'):
            for bad in ('-1', '1.5', 'text', str(2**63), ''):
                payload = {'max_accounts': '3', 'storage_limit_bytes': '4096', field: bad}
                self.assertEqual(self.post(url, **payload).status_code, 400)
        manager = self.member('manager', status='approved', role='admin')
        self.client.force_login(manager.user)
        self.assertEqual(self.post(url, max_accounts='9', storage_limit_bytes='9999').status_code, 403)
        self.assertEqual(GroupAudit.objects.count(), 1)

    def test_hidden_group_cannot_receive_signup(self):
        self.tenant.signup_enabled = False
        self.tenant.save()
        response = self.client.post('/signup/', {'username': 'hidden', 'password1': PASSWORD,
                                                'password2': PASSWORD, 'tenant': self.tenant.pk})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='hidden').exists())
        self.assertNotContains(self.client.get('/signup/'), 'Customer A')

    def test_signup_requires_public_group_and_ignores_privilege_fields(self):
        payload = {'username': 'applicant', 'password1': PASSWORD, 'password2': PASSWORD,
                   'role': 'admin', 'status': 'approved', 'is_superuser': 'true'}
        self.assertEqual(self.client.post('/signup/', payload).status_code, 200)
        self.assertFalse(User.objects.filter(username='applicant').exists())
        for invalid in ('999', 'bad'):
            self.assertEqual(self.client.post('/signup/', {**payload, 'tenant': invalid}).status_code, 200)
            self.assertFalse(User.objects.filter(username='applicant').exists())
        self.assertEqual(self.client.post('/signup/', {**payload, 'tenant': self.tenant.pk}).status_code, 302)
        user = User.objects.get(username='applicant')
        self.assertEqual((user.membership.tenant_id, user.membership.status, user.membership.role),
                         (self.tenant.pk, 'pending', 'member'))
        self.assertFalse(user.is_superuser or user.is_staff)
        self.client.force_login(user)
        self.assertEqual(self.client.get('/service/').status_code, 403)
