"""Global administrator enrollment policy; no device reset or recovery."""
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import connection
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods
from .locking import policy_transaction
from .mfa import device_binding
from .mfa_crypto import SeedUnavailable
from .mfa_policy import admin_access, current_policy
from .models import AdminOTPDevice, BootstrapAdmin, MFAPolicyAudit


class PolicyForm(forms.Form):
    required = forms.BooleanField(required=False, label='모든 관리자 OTP 등록 필수')
    password = forms.CharField(strip=False, widget=forms.PasswordInput, label='현재 비밀번호')
    token = forms.RegexField(r'^[0-9]{6}$', required=False, label='새 OTP', widget=forms.TextInput(attrs={'autocomplete': 'one-time-code', 'inputmode': 'numeric'}))


@sensitive_variables()
@sensitive_post_parameters()
@login_required
@require_http_methods(['GET', 'POST'])
def policy_settings(request):
    if connection.vendor != 'postgresql' and not settings.MEMBERSHIP_ALLOW_UNSAFE_SQLITE:
        return HttpResponse(status=503)
    with policy_transaction():
        actor = get_user_model().objects.select_for_update().get(pk=request.user.pk)
        if not actor.is_active or not actor.is_superuser or BootstrapAdmin.objects.filter(user=actor, must_change_password=True).exists():
            return HttpResponse(status=403)
        policy = current_policy()
        device = AdminOTPDevice.objects.select_for_update().filter(user=actor).first()
        try:
            if not admin_access(request, actor, device):
                return HttpResponse(status=403)
        except SeedUnavailable:
            return HttpResponse(status=503)
        form = PolicyForm(request.POST if request.method == 'POST' else None, initial={'required': policy.required})
        if request.method == 'POST' and form.is_valid():
            if not actor.check_password(form.cleaned_data['password']):
                return HttpResponse(status=403)
            try:
                validate_password(form.cleaned_data['password'], actor)
            except ValidationError:
                form.add_error('password', '강력한 비밀번호로 변경한 후 다시 시도하세요.')
                return render(request, 'membership/mfa_policy.html', {'form': form, 'policy': policy}, status=400)
            required = form.cleaned_data['required']
            if required or policy.required or device is not None:
                if not device or not device.confirmed:
                    return HttpResponse(status=403)
                if not device.verify_is_allowed()[0]:
                    return HttpResponse(status=429)
                try:
                    if not device.verify_token(form.cleaned_data['token']):
                        return HttpResponse(status=403)
                except SeedUnavailable:
                    return HttpResponse(status=503)
            previous = policy.required
            if required != previous:
                policy.required = required
                policy.version += 1
                policy.save(update_fields=['required', 'version'])
                MFAPolicyAudit.objects.create(actor=actor, previous=previous, required=required, version=policy.version)
            request.session.cycle_key()
            request.session['mfa_policy_version'] = policy.version
            if device and device.confirmed:
                request.session['mfa_device'] = device_binding(device)
                request.session['mfa_at'] = timezone.now().timestamp()
            request.session.save()
            return redirect('/manage/mfa-policy/')
        return render(request, 'membership/mfa_policy.html', {'form': form, 'policy': policy}, status=400 if request.method == 'POST' else 200)
