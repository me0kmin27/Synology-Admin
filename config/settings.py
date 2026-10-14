import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
if len(SECRET_KEY) < 50:
    raise ValueError("DJANGO_SECRET_KEY must contain at least 50 characters")
DEBUG = False
MEMBERSHIP_ALLOW_UNSAFE_SQLITE = os.environ.get('DJANGO_ALLOW_UNSAFE_SQLITE') == '1'
LOCAL_HTTP = os.environ.get("DJANGO_LOCAL_HTTP") == "1"
from .proxy_settings import allowed_hosts, csrf_origins, trusted_networks

ALLOWED_HOSTS = allowed_hosts()
CSRF_TRUSTED_ORIGINS = csrf_origins(ALLOWED_HOSTS)
TRUSTED_PROXY_NETWORKS = trusted_networks()
# Only our first middleware authenticates the transport peer and scheme.
SECURE_PROXY_SSL_HEADER = None
USE_X_FORWARDED_HOST = False
USE_X_FORWARDED_PORT = False
ROOT_URLCONF = "config.urls"
INSTALLED_APPS = ["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "membership", "support", "chat"]
MIDDLEWARE = [
    "config.proxy.TrustedProxyMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "config.errors.NavigationErrorMiddleware",
    "support.middleware.SupportPrivacyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "membership.middleware.MembershipSessionMiddleware",
    "membership.throttle.AuthThrottleMiddleware",
    "membership.mfa_middleware.AdminMFAMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": os.environ.get("DJANGO_DB_PATH", str(BASE_DIR / "db.sqlite3"))}}
if os.environ.get('DJANGO_DB_ENGINE') == 'postgresql':
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ['PGDATABASE'], 'USER': os.environ['PGUSER'],
        'PASSWORD': os.environ.get('PGPASSWORD', ''),
        'HOST': os.environ.get('PGHOST', '127.0.0.1'),
        'PORT': os.environ.get('PGPORT', '5432'),
    }}
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True, "OPTIONS": {"context_processors": ["membership.navigation.navigation", "membership.oidc.login_context"]}}]
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SECURE_SSL_REDIRECT = not LOCAL_HTTP
# Only the non-authenticated, non-sensitive DB liveness endpoint stays HTTP.
SECURE_REDIRECT_EXEMPT = [r'^health/$']
SESSION_COOKIE_SECURE = not LOCAL_HTTP
CSRF_COOKIE_SECURE = not LOCAL_HTTP
SECURE_HSTS_SECONDS = 0 if LOCAL_HTTP else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not LOCAL_HTTP
SECURE_HSTS_PRELOAD = not LOCAL_HTTP
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 1800
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
AUTH_ATTEMPT_LIMIT = 20
MFA_ENCRYPTION_KEYS = [key for key in os.environ.get("MFA_ENCRYPTION_KEYS", "").split(",") if key]
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/account/"
LOGOUT_REDIRECT_URL = "/login/"

# Optional authentik integration. No defaults infer or activate a live provider.
OIDC_ENABLED = os.environ.get('OIDC_ENABLED') == '1'
OIDC_ISSUER = os.environ.get('OIDC_ISSUER', '')
OIDC_CLIENT_ID = os.environ.get('OIDC_CLIENT_ID', '')
OIDC_CLIENT_SECRET = os.environ.get('OIDC_CLIENT_SECRET', '')
OIDC_REDIRECT_URI = os.environ.get('OIDC_REDIRECT_URI', '')
