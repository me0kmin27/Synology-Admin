"""Database-backed fixed-window guard; never trust forwarded headers."""
import time
from django.conf import settings
from django.contrib.auth.forms import UsernameField
from django.db.models import F
from django.http import HttpResponse
from django.utils.crypto import salted_hmac
from django.utils.deprecation import MiddlewareMixin
from .models import AuthAttempt


class AuthThrottleMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method != "POST" or not request.path.startswith(("/login/", "/signup/", "/manage/")):
            return None
        now = int(time.time())
        window = now // 900
        scope = "manage" if request.path.startswith("/manage/") else request.path
        if scope == "manage":
            identity = str(request.user.pk) if request.user.is_authenticated else "anonymous"
        else:
            # Match Django's username normalization, regardless of existing login.
            identity = UsernameField(max_length=150).to_python(request.POST.get("username", "")).casefold()[:150]
        values = ["ip:" + request.META.get("REMOTE_ADDR", "unknown"), "identity:" + identity]
        AuthAttempt.objects.filter(window__lt=window).delete()
        for value in values:
            key = salted_hmac("auth-throttle", f"{window}:{scope}:{value}", algorithm="sha256").hexdigest()
            attempt, _ = AuthAttempt.objects.get_or_create(key=key, defaults={"window": window})
            updated = AuthAttempt.objects.filter(pk=attempt.pk, count__lt=settings.AUTH_ATTEMPT_LIMIT).update(count=F("count") + 1)
            if not updated:
                response = HttpResponse("요청 제한. 잠시 후 다시 시도하세요.", status=429)
                response["Retry-After"] = str(900 - now % 900)
                response["Cache-Control"] = "no-store"
                return response
        return None
