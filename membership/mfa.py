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


def device_binding(device):
    return salted_hmac('mfa-device', f'{device.identity}:{device.ciphertext}').hexdigest()


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
            if AdminOTPDevice.objects.filter(user=actor).exists():
                return HttpResponse(status=409)
            device = AdminOTPDevice(user=actor, name='Portal administrator', enrollment_session=session_binding(request))
            seed = bytes.fromhex(random_hex(20))
            try:
                device.ciphertext = seal(device, seed)
            except SeedUnavailable:
                return HttpResponse(status=503)
            device.save()
            response = render(request, 'membership/mfa.html', {'seed': base64.b32encode(seed).decode()})
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
        request.session.save()
        return redirect('/manage/')
