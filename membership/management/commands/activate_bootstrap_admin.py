"""Owner enters a password on a trusted local/SSH TTY; never via argv or HTTP."""
import getpass
import os
import secrets
from pathlib import Path
import sys
import warnings
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UsernameField
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.views.decorators.debug import sensitive_variables
from membership.locking import policy_transaction
from membership.models import BootstrapAdmin


class Command(BaseCommand):
    help = 'One-time activation via hidden owner-controlled TTY password prompt.'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='admin')
        parser.add_argument('--password-file', help='Generate once into a new 0600 file in an owned 0700 directory; never stdout.')

    @sensitive_variables()
    def handle(self, *args, **options):
        if not options.get('password_file') and not sys.stdin.isatty():
            raise CommandError('An interactive trusted TTY is required; stdin/argv secrets are not accepted.')
        if connection.vendor != 'postgresql' and not settings.MEMBERSHIP_ALLOW_UNSAFE_SQLITE:
            raise CommandError('PostgreSQL is required.')
        name = UsernameField(max_length=150).clean(options['username'])
        def pending():
            user = get_user_model().objects.filter(username=name).first()
            if (not user or user.is_active or user.has_usable_password()
                    or not BootstrapAdmin.objects.filter(user=user, must_change_password=True).exists()):
                raise CommandError('No pending bootstrap account; nothing changed.')
            return user
        user = pending()
        if options.get('password_file'):
            target = Path(options['password_file'])
            if not target.is_absolute():
                raise CommandError('Password file must be an absolute private path.')
            with policy_transaction():
                user = pending()
                password = secrets.token_urlsafe(48)
                validate_password(password, user)
                try:
                    directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        info = os.fstat(directory)
                        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                            raise CommandError('Password directory must be owned by this process and mode 0700.')
                        fd = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                        with os.fdopen(fd, 'w') as destination:
                            destination.write(password + '\n')
                            destination.flush()
                            os.fsync(destination.fileno())
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                except OSError:
                    raise CommandError('Cannot create private password file; no account was activated. Never overwrite an existing file.') from None
                user.set_password(password)
                user.is_active = True
                user.save(update_fields=['password', 'is_active'])
            self.stdout.write('Activated; initial secret saved only in the requested private file. MFA and password change required.')
            return
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                password = getpass.getpass('Initial password: ')
                confirmation = getpass.getpass('Confirm initial password: ')
            if password != confirmation:
                raise CommandError('Passwords did not match; nothing changed.')
            validate_password(password, user)
        except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
            raise CommandError('Secure prompt unavailable or cancelled; nothing changed.') from None
        except ValidationError:
            raise CommandError('Password does not meet configured validation rules; nothing changed.') from None
        with policy_transaction():
            user = pending()
            user.set_password(password)
            user.is_active = True
            user.save(update_fields=['password', 'is_active'])
        self.stdout.write('Activated. Use TLS or an SSH tunnel; confirm MFA, then change your initial password.')
