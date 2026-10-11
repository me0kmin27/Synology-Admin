from django.contrib.auth import get_user_model, logout
from .locking import policy_transaction
from .models import Membership


def stamp_session(sender, request, user, **kwargs):
    with policy_transaction():
        fresh = get_user_model().objects.select_for_update().get(pk=user.pk)
        if not fresh.is_active:
            logout(request)
            return
        request.session["membership_version"] = Membership.objects.filter(user=user).values_list("session_version", flat=True).first()
        # Persist before releasing the policy lock so retirement can delete it.
        # A later middleware save cannot resurrect a deleted DB session row.
        request.session.save()


class MembershipSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.session.get('_auth_user_id') and not request.user.is_authenticated:
            request.session.flush()
        if request.user.is_authenticated:
            version = Membership.objects.filter(user=request.user).values_list("session_version", flat=True).first()
            if request.session.get("membership_version") != version:
                logout(request)
        response = self.get_response(request)
        if request.path.startswith(("/account/", "/service/", "/manage/", "/login/", "/signup/")):
            response["Cache-Control"] = "no-store"
        return response
