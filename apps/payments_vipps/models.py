from django.db import models


class VippsWebhookEvent(models.Model):
    """Idempotency log for inbound Vipps webhooks.

    Vipps assigns a unique pspReference to every event delivery, so we use it
    as the dedupe key. The unique constraint plus an `INSERT ... ON CONFLICT
    DO NOTHING` lookup makes duplicate deliveries a no-op.
    """

    psp_reference = models.CharField(max_length=64, unique=True, db_index=True)
    event_name = models.CharField(max_length=64)
    reference = models.CharField(max_length=64, db_index=True)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(blank=True)

    class Meta:
        ordering = ['-received_at']
        indexes = [
            models.Index(fields=['reference', 'event_name']),
        ]

    def __str__(self) -> str:
        return f'{self.event_name} {self.reference} ({self.psp_reference})'


class VippsAccessToken(models.Model):
    """Single-row cache of the OAuth access token.

    The Vipps client prefers Django's cache framework when available; this
    table is a persistent fallback so freshly-restarted processes don't all
    stampede the access-token endpoint at boot.
    """

    token = models.TextField()
    expires_at = models.DateTimeField()
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fetched_at']

    def __str__(self) -> str:
        return f'VippsAccessToken(expires_at={self.expires_at.isoformat()})'


class VippsWebhookRegistration(models.Model):
    """Records of webhook subscriptions registered with Vipps.

    Vipps returns the signing secret only once at registration time; we store
    it here so the webhook view can verify HMAC signatures. If the secret is
    lost, the operator must delete the row and re-run vipps_register_webhooks.
    """

    webhook_id = models.CharField(max_length=64, unique=True)
    url = models.URLField(max_length=2000)
    events = models.JSONField()
    secret = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'VippsWebhookRegistration({self.webhook_id}, active={self.is_active})'
