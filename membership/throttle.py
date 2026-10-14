"""DB guard using REMOTE_ADDR after the explicit transport-peer trust boundary."""
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
        if request.method != "POST" or not request.path.startswith(("/login/", "/auth/oidc/login/", "/signup/", "/manage/", "/mfa/", "/account/settings/")):
            return None
        request.sensitive_post_parameters = "__ALL__"
        now = int(time.time())
        window = now // 900
        scope = "manage" if request.path.startswith("/manage/") else request.path
        if request.path.startswith("/mfa/"):
            scope = "mfa"
        if scope in ("manage", "mfa", "/account/settings/"):
            identity = str(request.user.pk) if request.user.is_authenticated else "anonymous"
        else:
            # Match Django's username normalization, regardless of existing login.
            identity = UsernameField(max_length=150).to_python(request.POST.get("username", "")).casefold()[:150]
        values = ["ip:" + request.META.get("REMOTE_ADDR", "unknown")]
        # SSO has no local username: a shared empty identity would let one
        # anonymous client exhaust the entire site's SSO login budget.
        if scope != '/auth/oidc/login/':
            values.append("identity:" + identity)
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
