from django.conf import settings
from django.db import models


class AuthAttempt(models.Model):
    key = models.CharField(max_length=64, unique=True)
    window = models.BigIntegerField()
    count = models.PositiveIntegerField(default=0)


class Tenant(models.Model):
    name = models.CharField(max_length=100, unique=True)


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
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    tenant = models.ForeignKey(Tenant, null=True, blank=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=12, default="pending", choices=[(x, x) for x in ("pending", "approved", "suspended")])
    role = models.CharField(max_length=10, default="member", choices=[("member", "member"), ("admin", "admin")])
