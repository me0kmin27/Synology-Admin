from django.db import migrations


def seed_existing_capacity(apps, schema_editor):
    Tenant = apps.get_model('membership', 'Tenant')
    Membership = apps.get_model('membership', 'Membership')
    alias = schema_editor.connection.alias
    for tenant in Tenant.objects.using(alias).filter(max_accounts=0).iterator():
        count = Membership.objects.using(alias).filter(
            tenant_id=tenant.pk, status='approved', user__is_active=True,
        ).count()
        if count:
            Tenant.objects.using(alias).filter(pk=tenant.pk).update(max_accounts=count)


class Migration(migrations.Migration):
    dependencies = [('membership', '0009_membership_quota_bytes')]
    operations = [migrations.RunPython(seed_existing_capacity, migrations.RunPython.noop)]
