import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
if len(SECRET_KEY) < 50:
    raise ValueError("DJANGO_SECRET_KEY must contain at least 50 characters")
DEBUG = False
MEMBERSHIP_ALLOW_UNSAFE_SQLITE = os.environ.get('DJANGO_ALLOW_UNSAFE_SQLITE') == '1'
LOCAL_HTTP = os.environ.get("DJANGO_LOCAL_HTTP") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
ROOT_URLCONF = "config.urls"
INSTALLED_APPS = ["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "membership", "support", "chat"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "support.middleware.SupportPrivacyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "membership.middleware.MembershipSessionMiddleware",
    "membership.throttle.AuthThrottleMiddleware",
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
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True}]
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SECURE_SSL_REDIRECT = not LOCAL_HTTP
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
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/account/"
LOGOUT_REDIRECT_URL = "/login/"
