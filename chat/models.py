from django.conf import settings
from django.db import models
from django.utils import timezone


class Conversation(models.Model):
    tenant = models.ForeignKey('membership.Tenant', on_delete=models.PROTECT)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['tenant', 'id'], name='conversation_tenant_cursor')]
        constraints = [models.UniqueConstraint(fields=['tenant', 'owner'], name='chat_unique_owner_tenant')]


class RateWindow(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    read_started = models.DateTimeField(default=timezone.now)
    write_started = models.DateTimeField(default=timezone.now)
    read_count = models.PositiveIntegerField(default=0)
    write_count = models.PositiveIntegerField(default=0)


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.PROTECT, related_name='messages')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    body = models.TextField(max_length=2000)
    nonce = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['conversation', 'id'])]
        constraints = [models.UniqueConstraint(fields=['conversation', 'author', 'nonce'], name='chat_unique_send')]
