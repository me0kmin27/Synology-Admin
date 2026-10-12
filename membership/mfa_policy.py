"""Fresh authorization state. Call only within the global policy transaction."""
from .models import AdminMFAPolicy, Membership


def current_policy():
    return AdminMFAPolicy.objects.get(pk=1)


def current_session(request, actor):
    from .mfa import role_binding
    return (actor.is_active
            and request.session.exists(request.session.session_key)
            and request.session.get('_auth_user_id') == str(actor.pk)
            and request.session.get('_auth_user_hash') == actor.get_session_auth_hash()
            and request.session.get('auth_scope') == role_binding(actor)
            and request.session.get('membership_version') == Membership.objects.filter(
                user=actor).values_list('session_version', flat=True).first())


def admin_access(request, actor, device):
    from .mfa import verified_session
    policy = current_policy()
    if not current_session(request, actor) or request.session.get('mfa_policy_version') != policy.version:
        return False
    if device and device.confirmed or policy.required:
        return verified_session(request, actor, device)
    # Pending enrollment is not an opt-in until confirmation succeeds.
    return not request.session.get('mfa_device')
