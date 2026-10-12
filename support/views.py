from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from membership.locking import policy_transaction
from membership.models import Membership
from .pagination import cursor_page
from .forms import TicketForm, ReplyForm
from .models import Ticket, TicketAudit, TicketReply


def actor_membership(request, *, allow_global=False):
    actor = get_user_model().objects.get(pk=request.user.pk)
    member = Membership.objects.filter(user=actor).first()
    version = member.session_version if member else None
    if not actor.is_active or request.session.get('membership_version') != version:
        raise PermissionDenied
    request.user = actor
    if allow_global and actor.is_superuser:
        return member
    if not member or member.status != 'approved' or not member.tenant_id:
        raise PermissionDenied
    return member


def visible_tickets(request):
    member = actor_membership(request, allow_global=True)
    tickets = Ticket.objects.order_by('-pk')
    if request.user.is_superuser:
        return tickets
    tickets = tickets.filter(tenant_id=member.tenant_id)
    return tickets if member.role == 'admin' else tickets.filter(author=request.user)


@login_required
@require_http_methods(['GET'])
def index(request):
    tickets = visible_tickets(request).only('id', 'title')
    if 'page' in request.GET:
        return HttpResponse('Use the before cursor, not page numbers.', status=400)
    try:
        page = cursor_page(tickets, request.GET.get('before'), descending=True)
    except ValueError:
        return HttpResponse('Invalid cursor.', status=400)
    member = Membership.objects.filter(user=request.user).first()
    can_create = bool(member and member.status == 'approved' and member.tenant_id)
    return render(request, 'support/list.html', {**page, 'can_create': can_create})


@login_required
@require_http_methods(['GET'])
def detail(request, pk):
    ticket = get_object_or_404(visible_tickets(request), pk=pk)
    return render_replies(request, ticket, ReplyForm())


def render_replies(request, ticket, form):
    try:
        page = cursor_page(ticket.replies.select_related('author'), request.GET.get('after', '0'))
    except ValueError:
        return HttpResponse('Invalid cursor.', status=400)
    return render(request, 'support/detail.html', {
        'ticket': ticket, 'replies': page['page'], 'form': form,
        'next_cursor': page['next_cursor'],
    })


@sensitive_post_parameters('title', 'body')
@login_required
@require_http_methods(['GET', 'POST'])
def create(request):
    if request.method == 'POST':
        if connection.vendor != 'postgresql' and not settings.MEMBERSHIP_ALLOW_UNSAFE_SQLITE:
            return HttpResponse(status=503)
        with policy_transaction():
            member = actor_membership(request)
            if request.FILES:
                return HttpResponse(status=400)
            form = TicketForm(request.POST)
            if form.is_valid():
                ticket = Ticket.objects.create(tenant_id=member.tenant_id, author=request.user, **form.cleaned_data)
                TicketAudit.objects.create(ticket=ticket, actor=request.user, action='created')
                return redirect(f'/support/{ticket.pk}/')
    else:
        actor_membership(request)
        form = TicketForm()
    return render(request, 'support/form.html', {'form': form})


@sensitive_post_parameters('body')
@login_required
@require_http_methods(['POST'])
def reply(request, pk):
    if connection.vendor != 'postgresql' and not settings.MEMBERSHIP_ALLOW_UNSAFE_SQLITE:
        return HttpResponse(status=503)
    with policy_transaction():
        ticket = get_object_or_404(visible_tickets(request), pk=pk)
        if request.FILES:
            return HttpResponse(status=400)
        form = ReplyForm(request.POST)
        if form.is_valid():
            TicketReply.objects.create(ticket=ticket, author=request.user, **form.cleaned_data)
            TicketAudit.objects.create(ticket=ticket, actor=request.user, action='replied')
            return redirect(f'/support/{ticket.pk}/')
        return render_replies(request, ticket, form)
