from django.conf import settings
from django.db import models
import uuid
from django_otp.models import Device, ThrottlingMixin, TimestampMixin
from django.views.decorators.debug import sensitive_variables


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



class AuthAttempt(models.Model):
    key = models.CharField(max_length=64, unique=True)
    window = models.BigIntegerField()
    count = models.PositiveIntegerField(default=0)


class Tenant(models.Model):
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
