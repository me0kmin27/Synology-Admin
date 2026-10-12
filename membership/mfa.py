"""Administrator TOTP enrollment. No recovery or reset bypass."""
import base64
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods
from django_otp.util import random_hex
from .locking import policy_transaction
from .models import AdminOTPDevice, Membership
from .mfa_crypto import seal, SeedUnavailable


def is_admin(user):
    return user.is_active and (user.is_superuser or user.is_staff or Membership.objects.filter(
        user=user, status='approved', role='admin').exists())


def role_binding(user):
    member = Membership.objects.filter(user=user).values_list(
        'role', 'status', 'tenant_id', 'session_version').first()
    return [user.is_active, user.is_staff, user.is_superuser, list(member) if member else None]


def device_binding(device):
    return salted_hmac('mfa-device', f'{device.identity}:{device.ciphertext}').hexdigest()


def verified_session(request, actor, device):
    if (not device or not device.confirmed
            or request.session.get('auth_scope') != role_binding(actor)
            or request.session.get('mfa_device') != device_binding(device)):
        return False
    age = timezone.now().timestamp() - request.session.get('mfa_at', 0)
    if not 0 <= age <= 900:
        return False
    device.bin_key
    return True


def session_binding(request):
    return salted_hmac('mfa-enrollment', request.session.session_key or '').hexdigest()


@sensitive_variables()
@sensitive_post_parameters()
@login_required
@require_http_methods(['GET', 'POST'])
def enroll(request):
    if connection.vendor != 'postgresql' and not settings.MEMBERSHIP_ALLOW_UNSAFE_SQLITE:
        return HttpResponse(status=503)
    with policy_transaction():
        actor = get_user_model().objects.get(pk=request.user.pk)
        if not is_admin(actor):
            return HttpResponse(status=403)
        if request.method == 'GET':
            response = render(request, 'membership/mfa.html', {'enroll': True})
        elif not actor.check_password(request.POST.get('password', '')):
            return HttpResponse(status=403)
        else:
            existing = AdminOTPDevice.objects.select_for_update().filter(user=actor).first()
            if existing:
                if existing.confirmed or (timezone.now() - existing.created_at).total_seconds() <= 300:
                    return HttpResponse(status=409)
                existing.delete()
            device = AdminOTPDevice(user=actor, name='Portal administrator', enrollment_session=session_binding(request))
            seed = bytes.fromhex(random_hex(20))
            try:
                device.ciphertext = seal(device, seed)
            except SeedUnavailable:
                return HttpResponse(status=503)
            device.save()
            from .mfa_qr import enrollment_qr
            response = render(request, 'membership/mfa.html', {
                'seed': base64.b32encode(seed).decode(), 'qr_svg': enrollment_qr(seed, actor.username),
            })
        response['Cache-Control'] = 'no-store'
        return response


@sensitive_variables()
@sensitive_post_parameters()
@login_required
@require_http_methods(['GET', 'POST'])
def verify(request):
    if connection.vendor != 'postgresql' and not settings.MEMBERSHIP_ALLOW_UNSAFE_SQLITE:
        return HttpResponse(status=503)
    with policy_transaction():
        actor = get_user_model().objects.get(pk=request.user.pk)
        if not is_admin(actor):
            return HttpResponse(status=403)
        device = AdminOTPDevice.objects.select_for_update().filter(user=actor).first()
        if device is None:
            return redirect('/mfa/enroll/')
        if request.method == 'GET':
            response = render(request, 'membership/mfa.html')
            response['Cache-Control'] = 'no-store'
            return response
        if not device.confirmed and (
                device.enrollment_session != session_binding(request)
                or not 0 <= (timezone.now() - device.created_at).total_seconds() <= 300):
            return HttpResponse(status=403)
        if not device.verify_is_allowed()[0]:
            return HttpResponse(status=429)
        try:
            verified = device.verify_token(request.POST.get('token', ''))
        except SeedUnavailable:
            return HttpResponse(status=503)
        if not verified:
            return HttpResponse(status=403)  # Return, never roll back failed attempt.
        device.confirmed = True
        device.save(update_fields=['confirmed'])
        request.session.cycle_key()
        request.session['mfa_device'] = device_binding(device)
        request.session['mfa_at'] = timezone.now().timestamp()
        from .mfa_policy import current_policy
        request.session['mfa_policy_version'] = current_policy().version
        request.session.save()
        return redirect('/manage/')
