from django.apps import AppConfig


class MembershipConfig(AppConfig):
    name = "membership"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in
        from .middleware import stamp_session
        user_logged_in.connect(stamp_session, dispatch_uid="membership.session-version")
