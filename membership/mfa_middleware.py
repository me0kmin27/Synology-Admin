"""Default-deny administrator gate, serialized with every policy writer.

No streaming privileged response is supported: render/work must finish under
this transaction. Locks serialize reads too; this is a bounded-portal tradeoff.
"""
from django.contrib.auth import get_user_model, logout
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from .locking import policy_transaction
from .mfa import is_admin, device_binding, role_binding
from .mfa_crypto import SeedUnavailable
from .models import AdminOTPDevice


class AdminMFAMiddleware:
    safe_paths = frozenset(('/mfa/enroll/', '/mfa/verify/', '/login/', '/logout/', '/health/'))

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            response = self.get_response(request)
        else:
            with policy_transaction():
                request.user = get_user_model().objects.get(pk=request.user.pk)
                device = AdminOTPDevice.objects.filter(user=request.user).first()
                previous = request.session.get('mfa_device')
                if (not request.user.is_active
                        or request.session.get('auth_scope') != role_binding(request.user)
                        or (previous and (not device or not device.confirmed or previous != device_binding(device)))):
                    logout(request)
                    response = redirect('/login/') if request.method in ('GET', 'HEAD') else HttpResponse(status=403)
                elif request.path in self.safe_paths or not is_admin(request.user):
                    response = self.get_response(request)
                else:
                    try:
                        if device:
                            device.bin_key  # Missing key/tampered envelope also denies existing sessions.
                    except SeedUnavailable:
                        response = HttpResponse(status=503)
                    else:
                        age = timezone.now().timestamp() - request.session.get('mfa_at', 0)
                        if not device or not device.confirmed or not previous or not 0 <= age <= 900:
                            response = (redirect('/mfa/verify/' if device else '/mfa/enroll/')
                                        if request.method in ('GET', 'HEAD') else HttpResponse(status=403))
                        else:
                            response = self.get_response(request)
        if request.path.startswith('/mfa/') or request.user.is_authenticated:
            response['Cache-Control'] = 'no-store'
        return response
