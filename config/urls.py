from django.urls import path
from membership import oidc
from membership.policy_settings import policy_settings
from membership.account_settings import settings_view

from config.views import health, landing
from membership.mfa import enroll, verify
from chat import views as chat_views
from support import views as support_views
from membership.groups import limits, role, quota, create
from membership.views import signup, account, service, approve, revoke, manage, assign, link
from django.contrib.auth.views import LoginView, LogoutView

urlpatterns = [path("auth/oidc/login/", oidc.start), path("auth/oidc/callback/", oidc.callback), path("manage/mfa-policy/", policy_settings), path("account/settings/", settings_view), path("mfa/enroll/", enroll), path("mfa/verify/", verify), path("chat/<int:pk>/", chat_views.detail), path("chat/<int:pk>/events/", chat_views.events), path("chat/", chat_views.index), path("support/<int:pk>/replies/", support_views.reply), path("support/", support_views.index), path("support/<int:pk>/", support_views.detail), path("support/new/", support_views.create), path("", landing), path("health/", health), path("signup/", signup), path("manage/", manage), path("manage/<int:pk>/link/", link), path("manage/<int:pk>/assign/", assign), path("manage/<int:pk>/approve/", approve), path("manage/<int:pk>/revoke/", revoke),
    path("manage/groups/new/", create),
    path("manage/groups/<int:pk>/limits/", limits),
    path("manage/<int:pk>/role/", role),
    path("manage/<int:pk>/quota/", quota),
    path("login/", LoginView.as_view(template_name="membership/form.html", extra_context={"title": "포털 로그인"})),
    path("logout/", LogoutView.as_view()), path("account/", account), path("service/", service)]
