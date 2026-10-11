"""Portal policy only. No NAS provisioning or quota enforcement."""
import re

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.debug import sensitive_post_parameters
from .locking import authorized_mutation
from django.views.decorators.http import require_POST

from .models import GroupAudit, Membership, Tenant


def active_accounts(tenant):
    return Membership.objects.filter(tenant=tenant, status='approved', user__is_active=True)


def allocated_bytes(tenant):
    return Membership.objects.filter(tenant=tenant).aggregate(total=Sum('quota_bytes'))['total'] or 0


@sensitive_post_parameters()
@login_required
@require_POST
@authorized_mutation
def quota(request, pk):
    from .views import managed_members
    try:
        value = unsigned_integer(request.POST.get('quota_bytes', ''))
    except ValueError:
        return HttpResponse(status=400)
    with transaction.atomic():
        subject = get_object_or_404(managed_members(request.user).select_for_update(), pk=pk)
        if subject.status != 'approved' or not subject.user.is_active:
            return HttpResponse(status=409)
        tenant = Tenant.objects.select_for_update().get(pk=subject.tenant_id)
        if allocated_bytes(tenant) - subject.quota_bytes + value > tenant.storage_limit_bytes:
            return HttpResponse(status=409)
        previous = subject.quota_bytes
        subject.quota_bytes = value
        subject.save(update_fields=['quota_bytes'])
        GroupAudit.objects.create(actor=request.user, tenant=tenant, action='quota',
                                  details={'membership_id': subject.pk, 'previous': previous, 'quota_bytes': value})
    return redirect('/manage/')


def unsigned_integer(value):
    if not re.fullmatch(r'[0-9]{1,19}', value) or int(value) > 2**63 - 1:
        raise ValueError
    return int(value)


@sensitive_post_parameters()
@login_required
@require_POST
@authorized_mutation
def role(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
    new_role = request.POST.get('role')
    if new_role not in ('member', 'admin'):
        return HttpResponse(status=400)
    with transaction.atomic():
        subject = get_object_or_404(Membership.objects.select_for_update(), pk=pk)
        if subject.user_id == request.user.pk or subject.user.is_superuser:
            raise PermissionDenied
        if subject.status != 'approved' or not subject.user.is_active:
            return HttpResponse(status=409)
        if subject.role == new_role:
            return redirect('/manage/')
        if subject.role == 'admin' and active_accounts(subject.tenant).filter(role='admin').count() <= 1:
            return HttpResponse(status=409)
        previous = subject.role
        subject.role = new_role
        subject.session_version += 1
        subject.save(update_fields=['role', 'session_version'])
        from .models import AuditEvent
        AuditEvent.objects.create(actor=request.user, subject=subject, action='role', previous=previous, current=new_role)
    return redirect('/manage/')


@sensitive_post_parameters()
@login_required
@require_POST
@authorized_mutation
def limits(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
    try:
        data = {field: unsigned_integer(request.POST.get(field, ''))
                for field in ('max_accounts', 'storage_limit_bytes')}
    except ValueError:
        return HttpResponse(status=400)
    with transaction.atomic():
        tenant = get_object_or_404(Tenant.objects.select_for_update(), pk=pk)
        if data['max_accounts'] < active_accounts(tenant).count() or data['storage_limit_bytes'] < allocated_bytes(tenant):
            return HttpResponse(status=409)
        for field, value in data.items():
            setattr(tenant, field, value)
        tenant.save(update_fields=list(data))
        GroupAudit.objects.create(actor=request.user, tenant=tenant, action='limits', details=data)
    return redirect('/manage/')
