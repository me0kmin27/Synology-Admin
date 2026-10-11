import re

from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from .models import AuditEvent, Membership, NasBinding, Tenant


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
def approve(request, pk):
    if not request.user.check_password(request.POST.get("password", "")):
        return HttpResponseForbidden()
    with transaction.atomic():
        subject = get_object_or_404(managed_members(request.user).select_for_update(), pk=pk)
        if subject.user_id == request.user.pk:
            return HttpResponseForbidden()
        if subject.status != "pending" or subject.tenant_id is None:
            return HttpResponse(status=409)
        changed = Membership.objects.filter(pk=pk, status="pending").update(status="approved")
        if not changed:
            return HttpResponse(status=409)
        AuditEvent.objects.create(actor=request.user, subject=subject, action="approve", previous="pending", current="approved")
    return redirect("/account/")



@sensitive_post_parameters()
@login_required
@require_POST
def revoke(request, pk):
    if not request.user.check_password(request.POST.get("password", "")):
        return HttpResponseForbidden()
    with transaction.atomic():
        subject = get_object_or_404(managed_members(request.user).select_for_update(), pk=pk)
        if subject.user_id == request.user.pk:
            return HttpResponseForbidden()
        if subject.status != "approved":
            return HttpResponse(status=409)
        changed = Membership.objects.filter(pk=pk, status="approved").update(status="suspended", session_version=F("session_version") + 1)
        if not changed:
            return HttpResponse(status=409)
        AuditEvent.objects.create(actor=request.user, subject=subject, action="revoke", previous="approved", current="suspended")
        for session in Session.objects.iterator():
            if session.get_decoded().get("_auth_user_id") == str(subject.user_id):
                session.delete()
    return redirect("/account/")


@login_required
@require_http_methods(["GET"])
def manage(request):
    return render(request, "membership/manage.html", {
        "members": managed_members(request.user).select_related("user", "tenant").order_by("pk"),
        "tenants": Tenant.objects.all() if request.user.is_superuser else [],
        "global_admin": request.user.is_superuser,
    })


@sensitive_post_parameters()
@login_required
@require_POST
def assign(request, pk):
    if not request.user.is_superuser or not request.user.check_password(request.POST.get("password", "")):
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
def link(request, pk):
    if not request.user.check_password(request.POST.get("password", "")):
        return HttpResponseForbidden()
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
    return render(request, "membership/account.html", {"member": member})


@login_required
def service(request):
    member = Membership.objects.filter(user=request.user, status="approved", tenant__isnull=False).first()
    if not member:
        return HttpResponseForbidden()
    return render(request, "membership/service.html", {"member": member})



@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def signup(request):
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            Membership.objects.create(user=user)
        return redirect("/login/")
    return render(request, "membership/form.html", {"form": form, "title": "포털 가입"})
