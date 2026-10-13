from django.db import migrations, models


def legacy_slugs(apps, schema_editor):
    Tenant = apps.get_model('membership', 'Tenant')
    for tenant in Tenant.objects.using(schema_editor.connection.alias).all().iterator():
        tenant.slug = f'legacy-{tenant.pk}'
        tenant.save(using=schema_editor.connection.alias, update_fields=['slug'])


class Migration(migrations.Migration):
    dependencies = [('membership', '0015_mfa_policy_audit')]
    operations = [
        migrations.AddField(model_name='tenant', name='slug', field=models.SlugField(max_length=100, unique=True, null=True, blank=True)),
        migrations.RunPython(legacy_slugs, migrations.RunPython.noop),
    ]
