from django.conf import settings
from django.db import models
import uuid
from django_otp.models import Device, ThrottlingMixin, TimestampMixin
from django.views.decorators.debug import sensitive_variables


class OIDCIdentity(models.Model):
    """Immutable external principal; never resolved through mutable email."""
    issuer = models.CharField(max_length=512)
    subject = models.CharField(max_length=255)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['issuer', 'subject'], name='oidc_unique_principal')]


class OIDCLoginAttempt(models.Model):
    """Short-lived server-side PKCE transaction, atomically consumed once."""
    state_hash = models.CharField(max_length=64, primary_key=True)
    browser_hash = models.CharField(max_length=64)
    configuration_hash = models.CharField(max_length=64)
    nonce = models.CharField(max_length=128)
    verifier = models.CharField(max_length=128)
    tenant = models.ForeignKey('Tenant', null=True, on_delete=models.CASCADE)
    expires_at = models.DateTimeField(db_index=True)
    consumed = models.BooleanField(default=False)


class AdminOTPDevice(TimestampMixin, ThrottlingMixin, Device):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    confirmed = models.BooleanField(default=False)
    identity = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    ciphertext = models.TextField()
    last_t = models.BigIntegerField(default=-1)
    enrollment_session = models.CharField(max_length=64)

    @property
    def bin_key(self):
        from .mfa_crypto import unseal
        return unseal(self)

    @sensitive_variables()
    def verify_token(self, token):
        import re
        from django_otp.oath import TOTP
        if not self.verify_is_allowed()[0]:
            return False
        verified = False
        if re.fullmatch(r'[0-9]{6}', str(token)):
            totp = TOTP(self.bin_key)
            verified = totp.verify(int(token), tolerance=1, min_t=self.last_t + 1)
            if verified:
                self.last_t = totp.t()
                self.throttle_reset(commit=False)
                self.set_last_used_timestamp(commit=False)
                self.save()
        if not verified:
            self.throttle_increment()
        return verified

    def get_throttle_factor(self):
        return 1



class AdminMFAPolicy(models.Model):
    """Singleton; absence is an error, never an implicit permissive policy."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    required = models.BooleanField(default=False)
    version = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name='single_admin_mfa_policy')]


class MFAPolicyAudit(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    previous = models.BooleanField()
    required = models.BooleanField()
    version = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)


class CredentialAudit(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    username_changed = models.BooleanField()
    password_changed = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)


class BootstrapAdmin(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    must_change_password = models.BooleanField(default=True)


class AuthAttempt(models.Model):
    key = models.CharField(max_length=64, unique=True)
    window = models.BigIntegerField()
    count = models.PositiveIntegerField(default=0)


class Tenant(models.Model):
    slug = models.SlugField(max_length=100, unique=True, null=True, blank=True)
    name = models.CharField(max_length=100, unique=True)
    signup_enabled = models.BooleanField(default=True)
    max_accounts = models.PositiveBigIntegerField(default=0)
    storage_limit_bytes = models.PositiveBigIntegerField(default=0)

    def __str__(self):
        return self.name


class GroupAudit(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    action = models.CharField(max_length=20)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.ForeignKey("Membership", on_delete=models.PROTECT)
    action = models.CharField(max_length=20)
    previous = models.CharField(max_length=12)
    current = models.CharField(max_length=12)
    created_at = models.DateTimeField(auto_now_add=True)


class NasBinding(models.Model):
    membership = models.OneToOneField("Membership", on_delete=models.PROTECT)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    external_id = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Membership(models.Model):
    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(status__in=["pending", "approved", "suspended"]), name="membership_valid_status"),
            models.CheckConstraint(condition=models.Q(role__in=["member", "admin"]), name="membership_valid_role"),
            models.CheckConstraint(condition=~models.Q(status="approved") | models.Q(tenant__isnull=False), name="approved_requires_tenant"),
        ]

    session_version = models.PositiveIntegerField(default=0)
    quota_bytes = models.PositiveBigIntegerField(default=0)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    tenant = models.ForeignKey(Tenant, null=True, blank=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=12, default="pending", choices=[(x, x) for x in ("pending", "approved", "suspended")])
    role = models.CharField(max_length=10, default="member", choices=[("member", "member"), ("admin", "admin")])
