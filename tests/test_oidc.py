import json
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
import requests
from django.test import TestCase, override_settings, Client
from membership.models import Tenant

ISSUER = 'https://sso.example/application/o/portal/'
CONFIG = dict(OIDC_ENABLED=True, OIDC_ISSUER=ISSUER, OIDC_CLIENT_ID='portal',
              OIDC_CLIENT_SECRET='test-only', OIDC_REDIRECT_URI='https://testserver/auth/oidc/callback/')
METADATA = dict(issuer=ISSUER, authorization_endpoint='https://sso.example/application/o/authorize/',
                token_endpoint='https://sso.example/application/o/token/',
                jwks_uri=ISSUER + 'jwks/')


def response(data):
    result = requests.Response()
    result.status_code = 200
    result._content = json.dumps(data).encode()
    return result


@override_settings(**CONFIG)
class OIDCFlowTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Customer', signup_enabled=True)

    def begin(self):
        with patch('requests.sessions.Session.send', return_value=response(METADATA)):
            result = self.client.post('/auth/oidc/login/', {'tenant': self.tenant.pk}, secure=True)
        self.assertEqual(result.status_code, 302)
        return {k: v[0] for k, v in parse_qs(urlsplit(result.url).query).items()}

    def finish(self, query, changes=None, signing_key=None):
        import time
        from authlib.jose import JsonWebKey, JsonWebToken
        if not hasattr(self, 'key'):
            self.key = JsonWebKey.generate_key('RSA', 2048, is_private=True, options={'kid': 'test'})
        claims = dict(iss=ISSUER, sub='stable-subject', aud='portal', iat=int(time.time()),
                      exp=int(time.time()) + 120, nonce=query['nonce'], email='existing@example.com',
                      groups=['admin'], is_superuser=True)
        claims.update(changes or {})
        encoded = JsonWebToken(['RS256']).encode({'alg': 'RS256', 'kid': 'test'}, claims,
                                                signing_key or self.key).decode()
        def send(session, prepared, **kwargs):
            if prepared.url.endswith('/token/'):
                body = parse_qs(prepared.body)
                import base64, hashlib
                challenge = base64.urlsafe_b64encode(hashlib.sha256(body['code_verifier'][0].encode()).digest()).rstrip(b'=').decode()
                self.assertEqual(challenge, query['code_challenge'])
                return response(dict(access_token='transient-only', token_type='Bearer', id_token=encoded))
            if prepared.url.endswith('/jwks/'):
                return response({'keys': [self.key.as_dict(is_private=False)]})
            return response(METADATA)
        with patch('requests.sessions.Session.send', autospec=True, side_effect=send):
            return self.client.get('/auth/oidc/callback/', {'state': query['state'], 'code': 'one-use-code', 'tenant': '999'}, secure=True)

    def test_verified_identity_creates_pending_user_without_email_linking(self):
        from django.contrib.auth import get_user_model
        existing = get_user_model().objects.create_user('existing', email='existing@example.com', password='unchanged')
        query = self.begin()
        result = self.finish(query)
        self.assertEqual(result.status_code, 302)
        self.assertEqual(result.url, '/account/')
        user = get_user_model().objects.get(pk=self.client.session['_auth_user_id'])
        self.assertNotEqual(user.pk, existing.pk)
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertEqual(user.membership.status, 'pending')
        self.assertEqual(user.membership.role, 'member')
        self.assertEqual(user.membership.tenant, self.tenant)
        self.assertEqual(self.client.session['membership_version'], 0)
        self.assertNotIn('transient-only', str(dict(self.client.session)))
        self.assertEqual(self.client.get('/service/', secure=True).status_code, 403)
        self.assertEqual(self.client.get('/auth/oidc/callback/', {'state': query['state'], 'code': 'replay'}, secure=True).status_code, 400)

    def test_invalid_tokens_fail_closed(self):
        import time
        for change in ({'iss': 'https://evil.example/'}, {'aud': 'other'}, {'nonce': 'wrong'},
                       {'exp': int(time.time()) - 10}, {'iat': int(time.time()) + 600},
                       {'sub': ''}, {'aud': ['portal', 'other'], 'azp': 'other'}):
            with self.subTest(change=change):
                query = self.begin()
                self.assertEqual(self.finish(query, change).status_code, 400)
                self.assertNotIn('_auth_user_id', self.client.session)
        from authlib.jose import JsonWebKey
        key = JsonWebKey.generate_key('RSA', 2048, is_private=True)
        self.assertEqual(self.finish(self.begin(), signing_key=key).status_code, 400)

    def test_state_browser_expiry_and_configuration_binding(self):
        from membership.models import OIDCLoginAttempt
        from django.utils import timezone
        from datetime import timedelta
        query = self.begin()
        with patch('requests.sessions.Session.send') as send:
            self.assertEqual(Client().get('/auth/oidc/callback/', {'state': query['state'], 'code': 'stolen'}, secure=True).status_code, 400)
            self.assertEqual(self.client.get('/auth/oidc/callback/', {'state': 'wrong', 'code': 'x'}, secure=True).status_code, 400)
            with override_settings(OIDC_CLIENT_ID='changed'):
                self.assertEqual(self.client.get('/auth/oidc/callback/', {'state': query['state'], 'code': 'x'}, secure=True).status_code, 400)
            send.assert_not_called()
        OIDCLoginAttempt.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.finish(query).status_code, 400)

    def test_existing_principal_reused_without_tenant_reassignment(self):
        from django.contrib.auth import get_user_model
        query = self.begin()
        self.finish(query)
        pk = self.client.session['_auth_user_id']
        self.client.logout()
        self.tenant = Tenant.objects.create(name='Other customer')
        self.assertEqual(self.finish(self.begin(), {'email': 'changed@example.com'}).status_code, 302)
        self.assertEqual(self.client.session['_auth_user_id'], pk)
        self.assertNotEqual(get_user_model().objects.get(pk=pk).membership.tenant, self.tenant)

    def test_suspended_user_cannot_return(self):
        from membership.models import Membership
        self.finish(self.begin())
        Membership.objects.update(status='suspended')
        self.client.logout()
        self.assertEqual(self.finish(self.begin()).status_code, 403)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_closed_tenant_and_callback_injection(self):
        query = self.begin()
        self.tenant.signup_enabled = False
        self.tenant.save()
        self.assertEqual(self.finish(query).status_code, 403)
        self.assertEqual(self.client.post('/auth/oidc/login/', {'tenant': self.tenant.pk}, secure=True).status_code, 400)

    def test_outage_consumes_state_and_local_login_remains(self):
        query = self.begin()
        with patch('requests.sessions.Session.send', side_effect=requests.Timeout):
            result = self.client.get('/auth/oidc/callback/', {'state': query['state'], 'code': 'x'}, secure=True)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.finish(query).status_code, 400)
        self.assertEqual(self.client.get('/login/', secure=True).status_code, 200)

    def test_provider_error_is_not_a_server_error(self):
        query = self.begin()
        with patch('requests.sessions.Session.send', side_effect=[response(METADATA), response({'error': 'invalid_grant'})]):
            result = self.client.get('/auth/oidc/callback/', {'state': query['state'], 'code': 'bad'}, secure=True)
        self.assertEqual(result.status_code, 400)

    def test_login_ui_exposes_only_enabled_sso(self):
        result = self.client.get('/login/', secure=True)
        self.assertContains(result, 'action="/auth/oidc/login/"')
        self.assertContains(result, self.tenant.name)
        with override_settings(OIDC_ENABLED=False):
            self.assertNotContains(self.client.get('/login/', secure=True), 'action="/auth/oidc/login/"')

    @override_settings(AUTH_ATTEMPT_LIMIT=1)
    def test_start_is_throttled(self):
        self.begin()
        self.assertEqual(self.client.post('/auth/oidc/login/', secure=True).status_code, 429)

    def test_malformed_discovery_fails_closed(self):
        for document in ([], None, {'issuer': ISSUER, 'authorization_endpoint': None}):
            with self.subTest(document=document), patch('requests.sessions.Session.send', return_value=response(document)):
                self.assertEqual(self.client.post('/auth/oidc/login/', secure=True).status_code, 503)

    @override_settings(AUTH_ATTEMPT_LIMIT=1)
    def test_sso_throttle_does_not_share_anonymous_identity(self):
        self.begin()
        with patch('requests.sessions.Session.send', return_value=response(METADATA)):
            self.assertEqual(Client(REMOTE_ADDR='192.0.2.99').post('/auth/oidc/login/', secure=True).status_code, 302)

    def test_insecure_cookie_configuration_disables_sso_not_local_login(self):
        for overrides in ({'SESSION_COOKIE_SECURE': False}, {'CSRF_COOKIE_SECURE': False}, {'OIDC_ISSUER': 'http://sso.example/'}):
            with self.subTest(overrides=overrides), override_settings(**overrides):
                with patch('requests.sessions.Session.send', return_value=response(METADATA)) as send:
                    self.assertEqual(self.client.post('/auth/oidc/login/', secure=True).status_code, 503)
                    send.assert_not_called()
                self.assertEqual(self.client.get('/login/', secure=True).status_code, 200)

    def test_start_uses_pkce_nonce_and_csrf(self):
        with patch('requests.sessions.Session.send', return_value=response(METADATA)):
            result = self.client.post('/auth/oidc/login/', {'tenant': self.tenant.pk}, secure=True)
        self.assertEqual(result.status_code, 302)
        query = parse_qs(urlsplit(result.url).query)
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertEqual(query['response_type'], ['code'])
        self.assertEqual(query['scope'], ['openid profile email'])
        self.assertTrue(query['nonce'][0])
        self.assertTrue(query['state'][0])
        self.assertEqual(Client(enforce_csrf_checks=True).post('/auth/oidc/login/', secure=True).status_code, 403)
        self.assertEqual(self.client.get('/auth/oidc/login/', secure=True).status_code, 405)


class OIDCDisabledTests(TestCase):
    def test_disabled_endpoints_fail_closed_local_login_survives(self):
        for path in ('/auth/oidc/login/', '/auth/oidc/callback/'):
            self.assertEqual(self.client.post(path, secure=True).status_code, 503)
        self.assertEqual(self.client.get('/login/', secure=True).status_code, 200)
