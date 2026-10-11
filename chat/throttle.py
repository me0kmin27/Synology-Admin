import math
from django.http import JsonResponse
from django.utils import timezone
from .models import RateWindow


def rate_limit(request):
    # Caller holds policy_transaction: shared across workers, bounded one row/user.
    window, _ = RateWindow.objects.get_or_create(user=request.user)
    lane, limit = ('read', 60) if request.method == 'GET' else ('write', 20)
    now = timezone.now()
    started = getattr(window, lane + '_started')
    elapsed = (now - started).total_seconds()
    if elapsed >= 60 or elapsed < 0:
        setattr(window, lane + '_started', now)
        setattr(window, lane + '_count', 0)
        elapsed = 0
    count = getattr(window, lane + '_count')
    if count >= limit:
        response = JsonResponse({'error': 'Rate limit exceeded.'}, status=429)
        response['Retry-After'] = str(max(1, math.ceil(60 - elapsed)))
        return response
    setattr(window, lane + '_count', count + 1)
    window.save(update_fields=[lane + '_started', lane + '_count'])
