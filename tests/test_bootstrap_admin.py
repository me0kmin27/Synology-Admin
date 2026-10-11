from io import StringIO
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings


@override_settings(MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True)
class BootstrapTests(TestCase):
    def test_default_is_inactive_unusable_and_repeat_does_not_overwrite(self):
        from django.core.management import get_commands
        self.assertIn('bootstrap_admin', get_commands())
        output = StringIO()
        call_command('bootstrap_admin', stdout=output)
        user = User.objects.get(username='admin')
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertTrue(user.is_superuser)
        before = user.password
        call_command('bootstrap_admin', stdout=output)
        user.refresh_from_db()
        self.assertEqual(before, user.password)
        self.assertNotIn(before, output.getvalue())

    def test_generated_password_is_file_only_private_and_never_overwrites(self):
        import tempfile, pathlib, stat
        from django.core.management import get_commands, CommandError
        call_command('bootstrap_admin', stdout=StringIO())
        from membership.management.commands.activate_bootstrap_admin import Command
        self.assertIn('--password-file', Command().create_parser('manage.py', 'activate_bootstrap_admin').format_help())
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / 'initial-password'
            output = StringIO()
            call_command('activate_bootstrap_admin', password_file=str(target), stdout=output)
            initial = target.read_text().strip()
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            user = User.objects.get(username='admin')
            self.assertTrue(user.check_password(initial))
            self.assertNotIn(initial, output.getvalue())
            with self.assertRaises(CommandError):
                call_command('activate_bootstrap_admin', password_file=str(target), stdout=output)
            self.assertEqual(initial, target.read_text().strip())

    def test_existing_identifier_or_admin_never_overwritten(self):
        from django.core.management import CommandError
        existing = User.objects.create_user('admin')
        before = existing.password
        with self.assertRaises(CommandError):
            call_command('bootstrap_admin', stdout=StringIO())
        existing.refresh_from_db()
        self.assertFalse(existing.is_superuser)
        self.assertEqual(before, existing.password)
        existing.delete()
        User.objects.create_superuser('owner')
        with self.assertRaises(CommandError):
            call_command('bootstrap_admin', stdout=StringIO())
        self.assertFalse(User.objects.filter(username='admin').exists())

    def test_unsafe_existing_or_symlink_file_fails_without_activation(self):
        import tempfile, pathlib, os
        from django.core.management import CommandError
        call_command('bootstrap_admin', stdout=StringIO())
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / 'password'
            target.write_text('existing')
            for path in (target, pathlib.Path(directory) / 'symlink'):
                if path != target:
                    path.symlink_to(target)
                with self.assertRaises(CommandError):
                    call_command('activate_bootstrap_admin', password_file=str(path), stdout=StringIO())
                self.assertEqual(target.read_text(), 'existing')
                self.assertFalse(User.objects.get(username='admin').is_active)
            os.chmod(directory, 0o755)
            with self.assertRaises(CommandError):
                call_command('activate_bootstrap_admin', password_file=str(pathlib.Path(directory) / 'new'), stdout=StringIO())
            self.assertFalse(User.objects.get(username='admin').is_active)

    def test_activation_requires_tty_and_validated_secret_then_is_one_time(self):
        import secrets
        from unittest.mock import patch
        from django.core.management import get_commands, CommandError
        self.assertIn('activate_bootstrap_admin', get_commands())
        call_command('bootstrap_admin', stdout=StringIO())
        with patch('sys.stdin.isatty', return_value=False), self.assertRaises(CommandError):
            call_command('activate_bootstrap_admin', stdout=StringIO())
        new = secrets.token_urlsafe(24)
        with patch('sys.stdin.isatty', return_value=True), patch('getpass.getpass', side_effect=[new, new]):
            call_command('activate_bootstrap_admin', stdout=StringIO())
        user = User.objects.get(username='admin')
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password(new))
        with patch('sys.stdin.isatty', return_value=True), self.assertRaises(CommandError):
            call_command('activate_bootstrap_admin', stdout=StringIO())
