import re
from django.conf import settings
from django.views.decorators.debug import sensitive_post_parameters
from .forms import MessageForm
from .throttle import rate_limit
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from support.pagination import cursor_page
from django.views.decorators.http import require_http_methods
from membership.locking import policy_transaction
from support.views import actor_membership
from .models import Conversation, Message


@login_required
@require_http_methods(['GET', 'POST'])
def index(request):
    if connection.vendor != 'postgresql' and not settings.MEMBERSHIP_ALLOW_UNSAFE_SQLITE:
        return HttpResponse(status=503)
    with policy_transaction():
        member = actor_membership(request, allow_global=request.method == 'GET')
        limited = rate_limit(request)
        if limited is not None:
            return limited
        if request.method == 'GET':
            conversations = visible_conversations(request).select_related('owner')
            if 'page' in request.GET:
                return HttpResponse('Use the before cursor, not page numbers.', status=400)
            try:
                page = cursor_page(conversations, request.GET.get('before'), descending=True)
            except ValueError:
                return HttpResponse('Invalid cursor.', status=400)
            return render(request, 'chat/list.html', {**page, 'can_start': member and member.status == 'approved'})
        if request.FILES:
            return HttpResponse(status=400)
        conversation, _ = Conversation.objects.get_or_create(tenant_id=member.tenant_id, owner=request.user)
        return redirect(f'/chat/{conversation.pk}/')


@login_required
@require_http_methods(['GET'])
def detail(request, pk):
    if connection.vendor != 'postgresql' and not settings.MEMBERSHIP_ALLOW_UNSAFE_SQLITE:
        return HttpResponse(status=503)
    with policy_transaction():
        conversations = visible_conversations(request)
        limited = rate_limit(request)
        if limited is not None:
            return limited
        conversation = conversations.filter(pk=pk).first()
        if conversation is None:
            return HttpResponse(status=404)  # Commit rate charge, even for out-of-scope IDs.
        return render(request, 'chat/detail.html', {'conversation': conversation})


def visible_conversations(request):
    member = actor_membership(request, allow_global=True)
    conversations = Conversation.objects.order_by('-pk')
    if request.user.is_superuser:
        return conversations
    conversations = conversations.filter(tenant_id=member.tenant_id)
    return conversations if member.role == 'admin' else conversations.filter(owner=request.user)


@login_required
@require_http_methods(['GET', 'POST'])
@sensitive_post_parameters('body')
def events(request, pk):
    if connection.vendor != 'postgresql' and not settings.MEMBERSHIP_ALLOW_UNSAFE_SQLITE:
        return HttpResponse(status=503)
    with policy_transaction():
        conversations = visible_conversations(request)
        limited = rate_limit(request)
        if limited is not None:
            return limited
        conversation = conversations.filter(pk=pk).first()
        if conversation is None:
            return HttpResponse(status=404)  # Commit rate charge, even for out-of-scope IDs.
        if request.method == 'POST':
            form = MessageForm(request.POST)
            if request.FILES or not form.is_valid():
                return JsonResponse({'error': 'Invalid message (1–2000 characters), nonce, or attachment.'}, status=400)
            message, created = Message.objects.get_or_create(
                conversation=conversation, author=request.user, nonce=form.cleaned_data['nonce'],
                defaults={'body': form.cleaned_data['body']})
            if message.body != form.cleaned_data['body']:
                return JsonResponse({'error': 'Nonce already used for a different message.'}, status=409)
            return JsonResponse({'id': str(message.pk)}, status=201 if created else 200)
        raw = request.GET.get('after', '0')
        if not re.fullmatch(r'[0-9]{1,19}', raw) or int(raw) > 9223372036854775807:
            return JsonResponse({'error': 'Invalid cursor.'}, status=400)
        after = int(raw)
        rows = list(conversation.messages.filter(pk__gt=after).order_by('pk')[:51])
        page = rows[:50]
        return JsonResponse({'messages': [{'id': str(m.pk), 'author': str(m.author_id), 'body': m.body,
                                          'created_at': m.created_at.isoformat()} for m in page],
                             'cursor': str(page[-1].pk) if page else str(after), 'has_more': len(rows) > 50})
