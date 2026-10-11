from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class GroupMigrationTests(TransactionTestCase):
    def test_existing_active_members_seed_capacity_without_deleting_accounts(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        before = [('membership', '0007_tenant_signup_enabled')]
        executor.migrate(before)
        try:
            apps = executor.loader.project_state(before).apps
            User = apps.get_model('auth', 'User')
            Tenant = apps.get_model('membership', 'Tenant')
            Membership = apps.get_model('membership', 'Membership')
            tenant = Tenant.objects.create(name='Existing customer')
            for name, status, role, active in [('admin', 'approved', 'admin', True), ('member', 'approved', 'member', True), ('pending', 'pending', 'member', True), ('inactive', 'approved', 'member', False)]:
                user = User.objects.create(username=name, is_active=active)
                Membership.objects.create(user=user, tenant=tenant, status=status, role=role)
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            from membership.models import Tenant as CurrentTenant, Membership as CurrentMembership
            self.assertEqual(CurrentTenant.objects.get(pk=tenant.pk).max_accounts, 2)
            self.assertEqual(CurrentMembership.objects.count(), 4)
            self.assertEqual(CurrentTenant.objects.get(pk=tenant.pk).storage_limit_bytes, 0)
        finally:
            MigrationExecutor(connection).migrate(latest)
