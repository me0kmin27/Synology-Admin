"""One transaction-scoped lock serializes the portal authorization policy.

Lock order: advisory lock -> fresh actor User -> subject/tenant rows.
All role/status/limit/quota writes must enter this boundary. Direct SQL or
out-of-band auth mutations must acquire the same advisory lock first.
PostgreSQL READ COMMITTED is required; SQLite is opt-in development only.
"""
from functools import wraps

from django.conf import settings
from django.contrib.auth import get_user_model

from django.db import connection, transaction
from django.http import HttpResponse

POLICY_LOCK_ID = 7310462901


def authorized_mutation(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if connection.vendor != 'postgresql' and not settings.MEMBERSHIP_ALLOW_UNSAFE_SQLITE:
            return HttpResponse('PostgreSQL is required for membership mutations.', status=503)
        with transaction.atomic():
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_advisory_xact_lock(%s)', [POLICY_LOCK_ID])
            # Never trust the User cached by AuthenticationMiddleware before waiting.
            actor = get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if not actor.is_active or not actor.check_password(request.POST.get('password', '')):
                return HttpResponse(status=403)
            request.user = actor
            return view(request, *args, **kwargs)
    return wrapped
