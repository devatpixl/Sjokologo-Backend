from django.conf import settings
from django.db import models


class Order(models.Model):
    STATUS_CHOICES = [
        ('Bekreftet', 'Bekreftet'),
        ('Pakkes', 'Pakkes'),
        ('Sendt', 'Sendt'),
        ('Levert', 'Levert'),
    ]
    PAYMENT_CHOICES = [
        ('vipps', 'Vipps'),
    ]
    PAYMENT_STATUS_CHOICES = [
        ('PENDING',            'Pending — no payment created yet'),
        ('CREATED',            'Payment created with Vipps, awaiting user'),
        ('AUTHORIZED',         'User approved, funds reserved'),
        ('CAPTURED',           'Funds transferred to merchant'),
        ('PARTIALLY_REFUNDED', 'Some amount refunded'),
        ('REFUNDED',           'Fully refunded'),
        ('CANCELLED',          'Cancelled before capture'),
        ('ABORTED',            'User aborted in Vipps'),
        ('EXPIRED',            'Payment request expired'),
        ('TERMINATED',         'Terminated by merchant'),
        ('FAILED',             'Capture failed and could not be recovered'),
    ]

    order_number = models.CharField(max_length=20, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='orders',
    )
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    shipping = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Bekreftet')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES)

    # Shipping address — embedded directly
    ship_first_name = models.CharField(max_length=100)
    ship_last_name = models.CharField(max_length=100)
    ship_email = models.EmailField()
    ship_phone = models.CharField(max_length=30)
    ship_address = models.CharField(max_length=300)
    ship_postal_code = models.CharField(max_length=10)
    ship_city = models.CharField(max_length=100)
    ship_country = models.CharField(max_length=100, default='Norge')

    # ── Shipping method + Profrakt consignment ─────────────────────────
    SHIPPING_METHOD_CHOICES = [
        ('self-pickup',        'Hent i butikk (Ås)'),
        ('bring-pickup-point', 'Bring – hentested'),
        ('postnord-locker',    'PostNord pakkeboks'),
    ]
    shipping_method = models.CharField(
        max_length=24,
        choices=SHIPPING_METHOD_CHOICES,
        null=True, blank=True,
        db_index=True,
    )

    # Bring service partner the customer chose. All NULL when shipping_method
    # is 'self-pickup' or NULL (legacy orders).
    pickup_point_number = models.CharField(max_length=20, null=True, blank=True, db_index=True)
    pickup_point_name = models.CharField(max_length=300, null=True, blank=True)
    pickup_point_address1 = models.CharField(max_length=300, null=True, blank=True)
    pickup_point_postcode = models.CharField(max_length=10, null=True, blank=True)
    pickup_point_city = models.CharField(max_length=120, null=True, blank=True)
    pickup_point_country = models.CharField(max_length=80, null=True, blank=True)
    pickup_point_customer_number = models.CharField(max_length=20, null=True, blank=True)

    # Profrakt consignment, populated from createConsignment response.
    consignment_id = models.CharField(
        max_length=100, null=True, blank=True, db_index=True, unique=True,
    )
    consignment_number = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    consignment_pdf_url = models.URLField(max_length=2000, null=True, blank=True)
    tracking_url = models.URLField(max_length=2000, null=True, blank=True)

    # Quote metadata captured at confirmation. Persisted so admin / customer
    # support can see "we promised X working days" later.
    shipping_working_days = models.PositiveIntegerField(null=True, blank=True)
    shipping_expected_delivery = models.CharField(max_length=20, null=True, blank=True)

    # ── Vipps ePayment fields ──────────────────────────────────────────
    payment_status = models.CharField(
        max_length=24,
        choices=PAYMENT_STATUS_CHOICES,
        default='PENDING',
        db_index=True,
    )
    vipps_reference = models.CharField(
        max_length=64, unique=True, null=True, blank=True, db_index=True,
        help_text='Merchant reference sent to Vipps. Format: sl-{order_id:05d}-{8 hex}',
    )
    vipps_psp_reference = models.CharField(
        max_length=64, null=True, blank=True,
        help_text="Vipps' pspReference for the CREATED event (payment-level ID)",
    )
    vipps_redirect_url = models.URLField(max_length=2000, null=True, blank=True)
    vipps_currency = models.CharField(max_length=3, default='NOK')

    # All Vipps amounts in minor units (øre).
    vipps_authorized_amount = models.PositiveIntegerField(default=0)
    vipps_captured_amount = models.PositiveIntegerField(default=0)
    vipps_refunded_amount = models.PositiveIntegerField(default=0)
    vipps_cancelled_amount = models.PositiveIntegerField(default=0)

    # Persistent idempotency keys — same UUID is reused on every retry so Vipps
    # deduplicates server-side. Generated lazily the first time we need them.
    vipps_capture_idempotency_key = models.UUIDField(null=True, blank=True)
    vipps_cancel_idempotency_key = models.UUIDField(null=True, blank=True)

    authorized_at = models.DateTimeField(null=True, blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    last_vipps_sync_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['payment_status', 'created_at']),
        ]

    def save(self, *args, **kwargs):
        if not self.order_number:
            last = Order.objects.order_by('id').last()
            next_id = (last.id + 1) if last else 347
            self.order_number = f'SL-{next_id:05d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return self.order_number


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('products.Product', on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    variant = models.CharField(max_length=50, blank=True)
    initials = models.CharField(max_length=10, blank=True)
    custom_slots = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f'{self.quantity}× {self.product.name} (#{self.order.order_number})'


class OrderAuditLog(models.Model):
    """Append-only log of meaningful state changes on an Order.

    Single emission point: ``apps/orders/audit.py:record_order_event``. Any
    code path that mutates payment_status / fulfillment status / creates an
    order writes one row here so ops can see who/what changed an order.
    """
    SOURCE_CHOICES = [
        ('storefront', 'Storefront'),
        ('admin',      'Admin'),
        ('webhook',    'Vipps webhook'),
        ('reconciler', 'Vipps reconciler'),
        ('system',     'System / cron'),
    ]
    ACTION_CHOICES = [
        ('order_created',          'Order created'),
        ('payment_status_changed', 'Payment status changed'),
        ('fulfillment_changed',    'Fulfillment status changed'),
    ]

    order = models.ForeignKey(Order, related_name='audit_log', on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
    )
    action = models.CharField(max_length=32, choices=ACTION_CHOICES)
    from_value = models.JSONField(null=True, blank=True)
    to_value = models.JSONField(null=True, blank=True)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [models.Index(fields=['order', 'timestamp'])]

    def __str__(self):
        return f'{self.order.order_number} {self.action} ({self.source}) @ {self.timestamp:%Y-%m-%d %H:%M}'
