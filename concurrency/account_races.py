"""PostgreSQL-only credential races, with proven advisory-lock contention."""
import secrets
from django.contrib.auth.models import User
from django.db import connection
from tests.mfa_helpers import Client, TransactionTestCase, override_settings
from concurrency.races import PostgreSQLRaces
from membership.models import CredentialAudit


@override_settings(SECURE_SSL_REDIRECT=False, AUTH_ATTEMPT_LIMIT=1000)
class AccountRaces(TransactionTestCase):
    request = PostgreSQLRaces.request
    simultaneous = PostgreSQLRaces.simultaneous

    def setUp(self):
        self.assertEqual(connection.vendor, 'postgresql', 'Real PostgreSQL is required')
        self.password = secrets.token_urlsafe(24)

    def browser(self, user):
        browser = Client()
        browser.force_login(user)
        return browser

    def test_two_renames_to_normalized_identifier_have_one_winner(self):
        users = [User.objects.create_user(name, password=self.password) for name in ('first', 'second')]
        results = self.simultaneous([(self.browser(user), '/account/settings/', {'password': self.password, 'username': name})
                                    for user, name in zip(users, ('shared', 'ｓｈａｒｅｄ'))])
        self.assertEqual(sorted(results), [302, 400])
        self.assertEqual(User.objects.filter(username='shared').count(), 1)
        self.assertEqual(CredentialAudit.objects.count(), 1)

    def test_same_owner_queued_old_session_cannot_overwrite_winner(self):
        # No Membership exists: session deletion must also protect global owners.
        user = User.objects.create_superuser('owner', password=self.password)
        browsers = [self.browser(user), self.browser(user)]
        results = self.simultaneous([(browser, '/account/settings/', {'password': self.password, 'username': name})
                                    for browser, name in zip(browsers, ('winner-one', 'winner-two'))])
        self.assertEqual(sorted(results), [302, 403])
        self.assertEqual(CredentialAudit.objects.count(), 1)
        self.assertEqual(sum('_auth_user_id' in browser.session for browser in browsers), 1)

    def test_concurrent_password_changes_have_one_winner(self):
        user = User.objects.create_user('owner', password=self.password)
        new = [secrets.token_urlsafe(24), secrets.token_urlsafe(24)]
        results = self.simultaneous([(self.browser(user), '/account/settings/', {'password': self.password, 'username': 'owner', 'new_password1': value, 'new_password2': value}) for value in new])
        self.assertEqual(sorted(results), [302, 403])
        user.refresh_from_db()
        self.assertEqual(sum(user.check_password(value) for value in new), 1)
        self.assertEqual(CredentialAudit.objects.count(), 1)
