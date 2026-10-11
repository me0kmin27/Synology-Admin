"""One transaction-scoped lock serializes the portal authorization policy.

Lock order: advisory lock -> fresh actor User -> subject/tenant rows.
All role/status/limit/quota writes must enter this boundary. Direct SQL or
out-of-band auth mutations must acquire the same advisory lock first.
PostgreSQL READ COMMITTED is required; SQLite is opt-in development only.
"""
from functools import wraps
from contextlib import contextmanager

from django.conf import settings
from django.contrib.auth import get_user_model

from django.db import connection, transaction
from django.http import HttpResponse
from .models import Membership

POLICY_LOCK_ID = 7310462901


@contextmanager
def policy_transaction():
    with transaction.atomic():
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(%s)', [POLICY_LOCK_ID])
        yield


def authorized_mutation(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if connection.vendor != 'postgresql' and not settings.MEMBERSHIP_ALLOW_UNSAFE_SQLITE:
            return HttpResponse('PostgreSQL is required for membership mutations.', status=503)
        with policy_transaction():
            # Never trust the User cached by AuthenticationMiddleware before waiting.
            actor = get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if not actor.is_active or not actor.check_password(request.POST.get('password', '')):
                return HttpResponse(status=403)
            version = Membership.objects.filter(user=actor).values_list('session_version', flat=True).first()
            if request.session.get('membership_version') != version:
                return HttpResponse(status=403)
            from .mfa import verified_session
            from .mfa_crypto import SeedUnavailable
            from .models import AdminOTPDevice
            device = AdminOTPDevice.objects.select_for_update().filter(user=actor).first()
            try:
                if not verified_session(request, actor, device):
                    return HttpResponse(status=403)
            except SeedUnavailable:
                return HttpResponse(status=503)
            request.user = actor
            return view(request, *args, **kwargs)
    return wrapped
