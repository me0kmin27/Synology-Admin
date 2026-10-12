import re

from django.contrib.auth.decorators import login_required
from .forms import SignupForm
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from .locking import authorized_mutation
from django.views.decorators.http import require_http_methods, require_POST

from .models import AuditEvent, Membership, NasBinding, Tenant
from .groups import active_accounts


def managed_members(user):
    if user.is_superuser and user.is_active:
        return Membership.objects.all()
    operator = Membership.objects.filter(user=user, status="approved", role="admin", tenant__isnull=False).first()
    if not operator:
        raise PermissionDenied
    return Membership.objects.filter(tenant_id=operator.tenant_id)


@sensitive_post_parameters()
@login_required
@require_POST
@authorized_mutation
def approve(request, pk):
    with transaction.atomic():
        subject = get_object_or_404(managed_members(request.user).select_for_update(), pk=pk)
        if subject.user_id == request.user.pk:
            return HttpResponseForbidden()
        if subject.status != "pending" or subject.tenant_id is None:
            return HttpResponse(status=409)
        tenant = Tenant.objects.select_for_update().get(pk=subject.tenant_id)
        if not subject.user.is_active or active_accounts(tenant).count() >= tenant.max_accounts:
            return HttpResponse(status=409)
        changed = Membership.objects.filter(pk=pk, status="pending").update(status="approved")
        if not changed:
            return HttpResponse(status=409)
        AuditEvent.objects.create(actor=request.user, subject=subject, action="approve", previous="pending", current="approved")
    return redirect("/account/")



@sensitive_post_parameters()
@login_required
@require_POST
@authorized_mutation
def revoke(request, pk):
    with transaction.atomic():
        subject = get_object_or_404(managed_members(request.user).select_for_update(), pk=pk)
        if subject.user_id == request.user.pk or subject.user.is_superuser:
            return HttpResponseForbidden()
        if subject.status == "suspended" and not subject.user.is_active:
            return redirect("/account/")
        if subject.user.is_active and subject.status == 'approved' and subject.role == 'admin' and active_accounts(subject.tenant).filter(role='admin').count() <= 1:
            return HttpResponse(status=409)
        changed = Membership.objects.filter(pk=pk, status=subject.status).update(status="suspended", session_version=F("session_version") + 1)
        if not changed:
            return HttpResponse(status=409)
        AuditEvent.objects.create(actor=request.user, subject=subject, action="revoke", previous=subject.status, current="suspended")
        subject.user.is_active = False
        subject.user.save(update_fields=['is_active'])
        for session in Session.objects.iterator():
            if session.get_decoded().get("_auth_user_id") == str(subject.user_id):
                session.delete()
    return redirect("/account/")


@login_required
@require_http_methods(["GET"])
def manage(request):
    members = managed_members(request.user)
    return render(request, "membership/manage.html", {
        "members": members.select_related("user", "tenant").order_by("pk"),
        "tenants": Tenant.objects.all() if request.user.is_superuser else Tenant.objects.filter(pk__in=members.values('tenant_id')),
        "global_admin": request.user.is_superuser,
    })


@sensitive_post_parameters()
@login_required
@require_POST
@authorized_mutation
def assign(request, pk):
    if not request.user.is_superuser:
        return HttpResponseForbidden()
    with transaction.atomic():
        subject = get_object_or_404(Membership.objects.select_for_update(), pk=pk)
        if subject.user_id == request.user.pk:
            return HttpResponseForbidden()
        if subject.status != "pending" or subject.tenant_id is not None:
            return HttpResponse(status=409)
        try:
            tenant_id = int(request.POST.get("tenant", ""))
        except ValueError:
            return HttpResponse(status=400)
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        changed = Membership.objects.filter(pk=pk, status="pending", tenant__isnull=True).update(tenant=tenant)
        if not changed:
            return HttpResponse(status=409)
        AuditEvent.objects.create(actor=request.user, subject=subject, action="assign", previous="pending", current="pending")
    return redirect("/manage/")


@sensitive_post_parameters()
@login_required
@require_POST
@authorized_mutation
def link(request, pk):
    external_id = request.POST.get("external_id", "")
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,128}", external_id) or request.POST.get("ownership_confirmed") != "on":
        return HttpResponse(status=400)
    try:
        with transaction.atomic():
            subject = get_object_or_404(managed_members(request.user).select_for_update(), pk=pk)
            if subject.user_id == request.user.pk:
                return HttpResponseForbidden()
            if subject.status != "approved" or subject.tenant_id is None:
                return HttpResponse(status=409)
            NasBinding.objects.create(membership=subject, tenant_id=subject.tenant_id, external_id=external_id)
            AuditEvent.objects.create(actor=request.user, subject=subject, action="link", previous=subject.status, current=subject.status)
    except IntegrityError:
        return HttpResponse(status=409)
    return redirect("/manage/")


@login_required
def account(request):
    member = Membership.objects.filter(user=request.user).first()
    return render(request, "membership/account.html", {"member": member, "identity": request.user, "global_admin": request.user.is_superuser})


@login_required
@require_http_methods(['GET'])
def service(request):
    from django.contrib.auth import get_user_model
    from .locking import policy_transaction
    from .storage import usage_card

    # Re-read authorization after acquiring the shared revocation policy lock.
    # Render while held; the only reader is deliberately no-I/O.
    with policy_transaction():
        actor = get_user_model().objects.get(pk=request.user.pk)
        member = Membership.objects.select_related('user', 'tenant').filter(user=actor).first()
        if actor.is_active and actor.is_superuser and not member and request.session.get('membership_version') == (member.session_version if member else None):
            return render(request, 'membership/service.html', {
                'global_admin': True, 'tenants': Tenant.objects.order_by('pk'),
            })
        if (not actor.is_active or not member or member.status != 'approved'
                or not member.tenant_id
                or request.session.get('membership_version') != member.session_version):
            return HttpResponseForbidden()
        try:
            cards = [usage_card(member)]
            if member.role == 'admin' or actor.is_superuser:
                cards.append(usage_card(member, kind='group'))
        except ValueError:
            return HttpResponse('NAS 관측값을 확인할 수 없습니다.', status=503)
        return render(request, "membership/service.html", {"member": member, "cards": cards})



@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def signup(request):
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            Membership.objects.create(user=user, tenant=form.cleaned_data['tenant'])
        return redirect("/login/")
    return render(request, "membership/form.html", {"form": form, "title": "포털 가입"})
