from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache


def landing(request):
    return render(request, "landing.html", {"authenticated": request.user.is_authenticated})


@never_cache
def health(request):
    from django.db import DatabaseError
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable", "database": "unavailable", "nas": "not_configured"}, status=503)
    return JsonResponse({"status": "ok", "database": "ok", "nas": "not_configured"})
