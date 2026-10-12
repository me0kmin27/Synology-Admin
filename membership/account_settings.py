"""Self-service credentials; all writes share the authorization policy lock."""
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.conf import settings
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UsernameField
from django.contrib.sessions.models import Session
from django.db import connection, IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods
from .locking import policy_transaction
from .models import Membership, AdminOTPDevice, BootstrapAdmin, CredentialAudit, AdminMFAPolicy
from .mfa import is_admin, role_binding
from .mfa_policy import admin_access
from .mfa_crypto import SeedUnavailable


class CredentialsForm(forms.Form):
    username = UsernameField(max_length=150, label='아이디', validators=get_user_model()._meta.get_field('username').validators)
    new_password1 = forms.CharField(required=False, strip=False, widget=forms.PasswordInput, label='새 비밀번호')
    new_password2 = forms.CharField(required=False, strip=False, widget=forms.PasswordInput, label='새 비밀번호 확인')
    password = forms.CharField(strip=False, widget=forms.PasswordInput, label='현재 비밀번호')


@sensitive_variables()
@sensitive_post_parameters()
@login_required
@require_http_methods(['GET', 'POST'])
def settings_view(request):
    if connection.vendor != 'postgresql' and not settings.MEMBERSHIP_ALLOW_UNSAFE_SQLITE:
        return HttpResponse(status=503)
    with policy_transaction():
        actor = get_user_model().objects.select_for_update().get(pk=request.user.pk)
        member = Membership.objects.select_for_update().filter(user=actor).first()
        version = member.session_version if member else None
        if (not request.session.exists(request.session.session_key)
                or not actor.is_active or request.session.get('membership_version') != version
                or request.session.get('auth_scope') != role_binding(actor)
                or request.session.get('_auth_user_hash') != actor.get_session_auth_hash()):
            return HttpResponse(status=403)
        if is_admin(actor):
            try:
                if not admin_access(request, actor, AdminOTPDevice.objects.filter(user=actor).first()):
                    return HttpResponse(status=403)
            except (SeedUnavailable, AdminMFAPolicy.DoesNotExist):
                return HttpResponse(status=503)
        original_name = actor.username
        form = CredentialsForm(request.POST if request.method == 'POST' else None, initial={'username': actor.username})
        if request.method == 'POST' and form.is_valid():
            if not actor.check_password(form.cleaned_data['password']):
                return HttpResponse(status=403)
            name = form.cleaned_data['username']
            new = form.cleaned_data['new_password1']
            if not new and BootstrapAdmin.objects.filter(user=actor, must_change_password=True).exists():
                form.add_error('new_password1', '초기 비밀번호를 변경해야 합니다.')
            if new != form.cleaned_data['new_password2']:
                form.add_error('new_password2', '새 비밀번호가 일치하지 않습니다.')
            elif new:
                actor.username = name
                try:
                    validate_password(new, actor)
                    if actor.check_password(new):
                        raise ValidationError('현재 비밀번호와 다른 비밀번호를 사용하세요.')
                except ValidationError as error:
                    form.add_error('new_password1', error)
            if form.errors:
                return render(request, 'membership/settings.html', {'form': form}, status=400)
            if get_user_model().objects.filter(username=name).exclude(pk=actor.pk).exists():
                form.add_error('username', '사용할 수 없는 아이디입니다.')
            else:
                try:
                    with transaction.atomic():
                        actor.username = name
                        if new:
                            actor.set_password(new)
                        actor.save(update_fields=['username', 'password'])
                except IntegrityError:
                    form.add_error('username', '사용할 수 없는 아이디입니다.')
                else:
                    CredentialAudit.objects.create(actor=actor, username_changed=name != original_name, password_changed=bool(new))
                    if new:
                        BootstrapAdmin.objects.filter(user=actor).update(must_change_password=False)
                    if member:
                        member.session_version += 1
                        member.save(update_fields=['session_version'])
                    request.user = actor
                    update_session_auth_hash(request, actor)
                    for session in Session.objects.exclude(session_key=request.session.session_key).iterator():
                        if session.get_decoded().get('_auth_user_id') == str(actor.pk):
                            session.delete()
                    request.session['membership_version'] = member.session_version if member else None
                    request.session['auth_scope'] = role_binding(actor)
                    request.session.save()
                    return redirect('/account/settings/')
        return render(request, 'membership/settings.html', {'form': form}, status=400 if request.method == 'POST' else 200)
