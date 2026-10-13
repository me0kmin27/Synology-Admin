"""Display capabilities only; views remain responsible for authorization."""
from .models import Membership


def navigation(request):
    user = request.user
    authenticated = user.is_authenticated and user.is_active
    member = Membership.objects.filter(user=user).first() if authenticated else None
    approved = bool(member and member.status == 'approved' and member.tenant_id)
    global_admin = authenticated and user.is_superuser
    return {'portal_nav': {
        'authenticated': authenticated,
        'username': user.username if authenticated else '',
        'member': approved,
        'services': approved or global_admin,
        'manage': global_admin or (approved and member.role == 'admin'),
        'global_admin': global_admin,
    }}
