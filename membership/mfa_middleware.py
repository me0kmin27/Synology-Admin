"""Default-deny administrator gate, serialized with every policy writer.

No streaming privileged response is supported: render/work must finish under
this transaction. Locks serialize reads too; this is a bounded-portal tradeoff.
"""
from django.contrib.auth import get_user_model, logout
from django.http import HttpResponse
from django.shortcuts import redirect

from .locking import policy_transaction
from .mfa import is_admin, device_binding, role_binding
from .mfa_crypto import SeedUnavailable
from .models import AdminOTPDevice, BootstrapAdmin, AdminMFAPolicy
from .mfa_policy import admin_access, current_policy


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
                if (not request.session.exists(request.session.session_key)
                        or request.session.get('_auth_user_hash') != request.user.get_session_auth_hash()
                        or not request.user.is_active
                        or request.session.get('auth_scope') != role_binding(request.user)
                        or (previous and (not device or not device.confirmed or previous != device_binding(device)))):
                    logout(request)
                    response = redirect('/login/') if request.method in ('GET', 'HEAD') else HttpResponse(status=403)
                elif (BootstrapAdmin.objects.filter(user=request.user, must_change_password=True).exists()
                      and request.path not in self.safe_paths and request.path != '/account/settings/'):
                    response = redirect('/account/settings/') if request.method in ('GET', 'HEAD') else HttpResponse(status=403)
                elif request.path in self.safe_paths or not is_admin(request.user):
                    response = self.get_response(request)
                else:
                    try:
                        allowed = admin_access(request, request.user, device)
                    except (SeedUnavailable, AdminMFAPolicy.DoesNotExist):
                        response = HttpResponse(status=503)
                    else:
                        if not allowed:
                            if not current_policy().required and not (device and device.confirmed):
                                logout(request)
                                destination = '/login/'
                            else:
                                destination = '/mfa/verify/' if device else '/mfa/enroll/'
                            response = (redirect(destination)
                                        if request.method in ('GET', 'HEAD') else HttpResponse(status=403))
                        else:
                            response = self.get_response(request)
        if request.path.startswith('/mfa/') or request.user.is_authenticated:
            response['Cache-Control'] = 'no-store'
        return response
