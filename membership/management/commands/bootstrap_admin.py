"""Reserve an inert initial owner. Activation is interactive SSH-console only."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UsernameField
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from membership.locking import policy_transaction
from membership.models import BootstrapAdmin


class Command(BaseCommand):
    help = 'Reserve an inactive admin account without any usable/shared password.'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='admin')

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql' and not settings.MEMBERSHIP_ALLOW_UNSAFE_SQLITE:
            raise CommandError('PostgreSQL is required.')
        User = get_user_model()
        name = UsernameField(max_length=150, validators=User._meta.get_field('username').validators).clean(options['username'])
        with policy_transaction():
            existing = User.objects.filter(username=name).first()
            if existing:
                if BootstrapAdmin.objects.filter(user=existing).exists():
                    self.stdout.write('Bootstrap account already exists; unchanged.')
                    return
                raise CommandError('Identifier already exists; no account was modified.')
            if User.objects.filter(is_superuser=True).exists() or BootstrapAdmin.objects.exists():
                raise CommandError('An administrator already exists; bootstrap refused.')
            user = User.objects.create_user(username=name, password=None, is_active=False, is_staff=True, is_superuser=True)
            BootstrapAdmin.objects.create(user=user)
        self.stdout.write('Inactive bootstrap account created; activate from an owner-controlled SSH console.')
