from django.contrib.auth import logout
from .models import Membership


def stamp_session(sender, request, user, **kwargs):
    request.session["membership_version"] = Membership.objects.filter(user=user).values_list("session_version", flat=True).first()


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
