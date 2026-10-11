from django.conf import settings
from django.db import models


class Ticket(models.Model):
    tenant = models.ForeignKey('membership.Tenant', on_delete=models.PROTECT)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    title = models.CharField(max_length=160)
    body = models.TextField(max_length=10000)
    created_at = models.DateTimeField(auto_now_add=True)


class TicketAudit(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=16, default='created')
    created_at = models.DateTimeField(auto_now_add=True)
