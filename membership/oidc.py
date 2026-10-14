"""Optional authentik code flow. Never use provider claims for authorization."""
import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

import requests
from authlib.integrations.requests_client import OAuth2Session
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_variables, sensitive_post_parameters

from .models import OIDCLoginAttempt, Tenant


def login_context(request):
    if request.path != '/login/':
        return {}
    try:
        configuration()
    except ValueError:
        return {}
    return {'oidc_available': True, 'oidc_tenants': Tenant.objects.filter(signup_enabled=True).order_by('name')}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def configuration():
    if (not getattr(settings, 'OIDC_ENABLED', False)
            or not settings.SESSION_COOKIE_SECURE or not settings.CSRF_COOKIE_SECURE):
        raise ValueError('Disabled or insecure cookies')
    values = [getattr(settings, 'OIDC_' + name, '') for name in
              ('ISSUER', 'CLIENT_ID', 'CLIENT_SECRET', 'REDIRECT_URI')]
    issuer, client_id, secret, callback_uri = values
    for value in (issuer, callback_uri):
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('Invalid URL')
    if not issuer.endswith('/') or not client_id or not secret:
        raise ValueError('Incomplete configuration')
    if urlsplit(callback_uri).path != '/auth/oidc/callback/':
        raise ValueError('Invalid callback')
    return issuer, client_id, secret, callback_uri


def metadata(issuer):
    with requests.Session() as client:
        result = client.get(issuer + '.well-known/openid-configuration', timeout=5, allow_redirects=False)
        result.raise_for_status()
        if result.status_code != 200:
            raise ValueError('Discovery failed')
        document = result.json()
    if not isinstance(document, dict) or document.get('issuer') != issuer:
        raise ValueError('Issuer mismatch')
    for name in ('authorization_endpoint', 'token_endpoint', 'jwks_uri'):
        endpoint = urlsplit(document[name])
        if (endpoint.scheme != 'https' or endpoint.netloc != urlsplit(issuer).netloc
                or endpoint.username or endpoint.password or endpoint.fragment or endpoint.query):
            raise ValueError('Untrusted endpoint')
    return document


def oauth(config, state=None):
    issuer, client_id, secret, callback_uri = config
    return OAuth2Session(client_id, secret, scope='openid profile email', state=state,
                         redirect_uri=callback_uri, code_challenge_method='S256',
                         token_endpoint_auth_method='client_secret_basic', default_timeout=5)


def config_binding(config):
    return salted_hmac('oidc-configuration', '\0'.join(config)).hexdigest()


@never_cache
@sensitive_variables()
@sensitive_post_parameters()
def start(request):
    try:
        config = configuration()
    except ValueError:
        return HttpResponse('SSO is unavailable. Use local login.', status=503)
    if request.method != 'POST':
        return HttpResponse(status=405)
    if request.user.is_authenticated:
        return HttpResponse(status=409)
    tenant = None
    selected = request.POST.get('tenant', '')
    if selected:
        if not selected.isascii() or not selected.isdigit() or len(selected) > 18:
            return HttpResponse(status=400)
        tenant = Tenant.objects.filter(pk=selected, signup_enabled=True).first()
        if not tenant:
            return HttpResponse(status=400)
    try:
        document = metadata(config[0])
        nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        with oauth(config) as client:
            uri, state = client.create_authorization_url(document['authorization_endpoint'],
                                                         nonce=nonce, code_verifier=verifier)
    except (ValueError, KeyError, requests.RequestException):
        return HttpResponse('SSO is unavailable. Use local login.', status=503)
    browser = request.session.get('oidc_browser') or secrets.token_urlsafe(32)
    request.session['oidc_browser'] = browser
    OIDCLoginAttempt.objects.filter(expires_at__lt=timezone.now()).delete()
    OIDCLoginAttempt.objects.create(state_hash=digest(state), browser_hash=digest(browser),
        configuration_hash=config_binding(config), nonce=nonce, verifier=verifier,
        tenant=tenant, expires_at=timezone.now() + timedelta(minutes=5))
    return redirect(uri)


@never_cache
@sensitive_variables()
def callback(request):
    from authlib.jose import JsonWebToken, JoseError
    from authlib.oidc.core import CodeIDToken
    from authlib.integrations.base_client.errors import OAuthError
    from django.contrib.auth import get_user_model, login
    from django.db import connection
    from .locking import policy_transaction
    from .models import OIDCIdentity, Membership

    try:
        config = configuration()
    except ValueError:
        return HttpResponse('SSO is unavailable. Use local login.', status=503)
    if request.method != 'GET':
        return HttpResponse(status=405)
    if connection.vendor != 'postgresql' and not settings.MEMBERSHIP_ALLOW_UNSAFE_SQLITE:
        return HttpResponse(status=503)
    state = request.GET.get('state', '')
    browser = request.session.get('oidc_browser', '')
    if not state or len(state) > 256 or not browser or request.user.is_authenticated:
        return HttpResponse(status=400)
    # Conditional UPDATE, not session.pop: simultaneous callbacks can only have
    # one winner. Commit consumption BEFORE remote I/O (including failures).
    attempts = OIDCLoginAttempt.objects.filter(state_hash=digest(state), browser_hash=digest(browser),
        configuration_hash=config_binding(config), consumed=False, expires_at__gt=timezone.now())
    attempt = attempts.first()
    if not attempt or attempts.update(consumed=True, verifier='', nonce='') != 1:
        return HttpResponse(status=400)
    if request.GET.get('error') or not request.GET.get('code'):
        return HttpResponse(status=400)
    try:
        document = metadata(config[0])
        with oauth(config, state=state) as client:
            token = client.fetch_token(document['token_endpoint'], grant_type='authorization_code',
                code=request.GET['code'], code_verifier=attempt.verifier,
                allow_redirects=False)
        with requests.Session() as client:
            result = client.get(document['jwks_uri'], timeout=5, allow_redirects=False)
            result.raise_for_status()
            if result.status_code != 200:
                raise ValueError('Key retrieval failed')
            keys = result.json()
        claims = JsonWebToken(['RS256']).decode(token['id_token'], keys, claims_cls=CodeIDToken,
            claims_options={'iss': {'essential': True, 'value': config[0]},
                            'aud': {'essential': True, 'value': config[1]}},
            claims_params={'nonce': attempt.nonce, 'client_id': config[1],
                           'access_token': token.get('access_token')})
        claims.validate(leeway=0)
        subject = claims['sub']
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise ValueError('Invalid subject')
    except (ValueError, KeyError, TypeError, JoseError, OAuthError, requests.RequestException):
        return HttpResponse('SSO authentication failed. Restart login or use local login.', status=400)
    with policy_transaction():
        identity = OIDCIdentity.objects.select_related('user').filter(issuer=config[0], subject=subject).first()
        if identity:
            user = get_user_model().objects.select_for_update().get(pk=identity.user_id)
            member = Membership.objects.filter(user=user).first()
            if not user.is_active or not member or member.status == 'suspended':
                return HttpResponse(status=403)
        else:
            tenant = None
            if attempt.tenant_id:
                tenant = Tenant.objects.select_for_update().filter(pk=attempt.tenant_id, signup_enabled=True).first()
                if not tenant:
                    return HttpResponse(status=403)
            # Deliberately ignore email, username, group and privilege claims.
            user = get_user_model().objects.create_user(username='oidc_' + secrets.token_hex(24), password=None,
                                                        is_staff=False, is_superuser=False)
            Membership.objects.create(user=user, tenant=tenant, status='pending', role='member')
            OIDCIdentity.objects.create(issuer=config[0], subject=subject, user=user)
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return redirect('/account/')
